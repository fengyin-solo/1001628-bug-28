"""保障结算业务规则：状态流转、字段校验与筛选口径都收在这里。

驳回不是终态：被驳回的结算单退回「待核算」并清空本次付款信息，重新提交后
从 0 开始累计付款。确认付款支持分次到账，累计已付不得超过应付；结算单号
全表唯一，重复登记按失败处理。汇总与列表共用同一份筛选结果，保证口径一致。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "settlement"
REQUIRED_FIELDS = ["结算单号", "关联协议", "结算周期"]
STATUS_DRAFT = "待核算"
STATUS_REVIEW = "待审核"
STATUS_PAID = "已付款"
STATUS_ORDER = [STATUS_DRAFT, STATUS_REVIEW, STATUS_PAID]
# 允许在什么状态下执行什么动作，驳回必须先把单子退回核算而不是丢进终态。
ACTION_RULES: dict[str, tuple[str, tuple[str, ...]]] = {
    "提交审核": (STATUS_REVIEW, (STATUS_DRAFT,)),
    "确认付款": (None, (STATUS_REVIEW,)),
    "驳回结算": (STATUS_DRAFT, (STATUS_REVIEW,)),
}


def _parse_amount(value: Any) -> float | None:
    """把前端传来的金额解析成数字；空值按 0 处理，无法解析时返回 None。"""
    if value is None or str(value).strip() == "":
        return 0.0
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if amount != amount:  # NaN
        return None
    return round(amount, 2)


def _money(amount: float) -> str:
    """统一金额展示，避免 12.50 与 12.5 对不上账。"""
    return f"{amount:.2f}"


class SettlementService:
    def _filter_rows(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        agreement: str | None = None,
        period: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("结算单号", ""))]
        if agreement:
            rows = [row for row in rows if agreement in str(row.get("关联协议", ""))]
        if period:
            rows = [row for row in rows if period in str(row.get("结算周期", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        agreement: str | None = None,
        period: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._filter_rows(
            keyword=keyword, status=status, agreement=agreement, period=period
        )
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def summarize(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        agreement: str | None = None,
        period: str | None = None,
    ) -> dict[str, Any]:
        """按列表相同的筛选口径汇总：待审核量、本月付款额、已驳回量及周期汇总。"""
        rows = self._filter_rows(
            keyword=keyword, status=status, agreement=agreement, period=period
        )
        month_prefix = date.today().strftime("%Y-%m")
        month_paid = 0.0
        rejected = 0
        periods: dict[str, dict[str, Any]] = {}
        for row in rows:
            payable = _parse_amount(row.get("应付金额")) or 0.0
            paid = _parse_amount(row.get("已付金额")) or 0.0
            period = str(row.get("结算周期") or "未填写周期")
            bucket = periods.setdefault(
                period,
                {"结算周期": period, "单据数": 0, "应付金额": 0.0, "已付金额": 0.0},
            )
            bucket["单据数"] += 1
            bucket["应付金额"] = round(bucket["应付金额"] + payable, 2)
            bucket["已付金额"] = round(bucket["已付金额"] + paid, 2)
            if int(row.get("驳回次数") or 0) > 0:
                rejected += 1
            if str(row.get("status")) == STATUS_PAID and str(row.get("付款日期") or "").startswith(month_prefix):
                month_paid = round(month_paid + paid, 2)
        pending_review = sum(1 for row in rows if str(row.get("status")) == STATUS_REVIEW)
        return {
            "待审核结算": pending_review,
            "本月付款金额": round(month_paid, 2),
            "已驳回单据": rejected,
            "周期汇总": sorted(periods.values(), key=lambda item: item["结算周期"], reverse=True),
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, ""
        code = str(values.get("结算单号")).strip()
        if any(str(row.get("结算单号") or "").strip() == code for row in store.rows(MODULE)):
            return None, [], f"登记失败：结算单号 {code} 已存在，编号不可重复"
        payable = _parse_amount(values.get("应付金额"))
        if payable is None:
            return None, [], "登记失败：应付金额必须是数字"
        if payable < 0:
            return None, [], "登记失败：应付金额不能为负数"
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: str(values.get(field)).strip() for field in REQUIRED_FIELDS})
        entry["应付金额"] = payable
        # 新单尚未发生付款，本次付款信息保持空白。
        entry["已付金额"] = 0.0
        entry["审核人员"] = str(values.get("审核人员") or "").strip()
        entry["付款日期"] = ""
        entry["status"] = STATUS_DRAFT
        entry["结算状态"] = STATUS_DRAFT
        entry["pending"] = True
        entry["abnormal"] = False
        entry["驳回次数"] = 0
        rows.append(entry)
        return entry, [], ""

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"结算单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于保障结算可执行范围"
        target, allowed = ACTION_RULES[action]
        current = str(entry.get("status"))
        if current not in allowed:
            return None, f"结算单当前为{current}，不能{action}（仅{'、'.join(allowed)}状态可执行）"

        if action == "提交审核":
            # 重新提交视为新一轮付款：上次残留的已付金额与付款日期必须清零。
            entry["已付金额"] = 0.0
            entry["付款日期"] = ""
            entry["status"] = target
            entry["结算状态"] = target
            entry["pending"] = True
            auditor = str(values.get("审核人员") or entry.get("审核人员") or "").strip()
            if auditor:
                entry["审核人员"] = auditor
            return entry, "结算单已提交审核，付款信息从零开始累计"

        if action == "驳回结算":
            # 退回待核算并清空本次付款信息，单据留在列表里可再次提交。
            entry["已付金额"] = 0.0
            entry["付款日期"] = ""
            entry["status"] = STATUS_DRAFT
            entry["结算状态"] = STATUS_DRAFT
            entry["pending"] = True
            entry["abnormal"] = True
            entry["驳回次数"] = int(entry.get("驳回次数") or 0) + 1
            return entry, "结算单已驳回并退回待核算，本次付款信息已清空"

        # 确认付款：本次付款金额累计到已付，超额直接判失败且不落任何字段。
        payment = _parse_amount(values.get("本次付款金额", values.get("付款金额")))
        if payment is None:
            return None, "确认付款失败：本次付款金额必须是数字"
        if payment <= 0:
            return None, "确认付款失败：本次付款金额必须大于 0"
        payable = _parse_amount(entry.get("应付金额"))
        if payable is None:
            return None, "确认付款失败：应付金额数据异常，请先在待核算环节修正"
        paid_before = _parse_amount(entry.get("已付金额")) or 0.0
        paid_after = round(paid_before + payment, 2)
        if paid_after > payable:
            over = round(paid_after - payable, 2)
            return (
                None,
                f"确认付款失败：累计已付 {_money(paid_after)} 元超过应付 {_money(payable)} 元，"
                f"差额 {_money(over)} 元，请调减本次付款金额",
            )
        pay_date = str(values.get("付款日期") or "").strip() or date.today().isoformat()
        auditor = str(values.get("审核人员") or entry.get("审核人员") or "").strip()
        entry["已付金额"] = paid_after
        entry["付款日期"] = pay_date
        if auditor:
            entry["审核人员"] = auditor
        if paid_after == payable:
            entry["status"] = STATUS_PAID
            entry["结算状态"] = STATUS_PAID
            entry["pending"] = False
            return entry, f"付款已确认，累计 {_money(paid_after)} 元，结算单结清"
        entry["status"] = STATUS_REVIEW
        entry["结算状态"] = STATUS_REVIEW
        entry["pending"] = True
        remaining = round(payable - paid_after, 2)
        return entry, f"本次付款 {_money(payment)} 元已登记，剩余 {_money(remaining)} 元待付"
