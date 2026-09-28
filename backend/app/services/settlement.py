"""保障结算业务规则：状态流转、付款累计、驳回回退与汇总口径都收在这里。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "settlement"
REQUIRED_FIELDS = ["结算单号", "关联协议", "结算周期", "应付金额"]
STATUS_DRAFT = "待核算"
STATUS_REVIEW = "待审核"
STATUS_PAID = "已付款"
STATUSES = [STATUS_DRAFT, STATUS_REVIEW, STATUS_PAID]
ACTION_SUBMIT = "提交审核"
ACTION_PAY = "确认付款"
ACTION_REJECT = "驳回结算"
MONEY_EPS = 0.001


def _to_amount(value: Any) -> float | None:
    """把入参解析成正数金额；无法解析或非正数时返回 None。"""
    try:
        amount = round(float(value), 2)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


class SettlementService:
    # ---- 查询与汇总：列表与汇总必须走同一份筛选口径 ----
    def _query(
        self,
        *,
        keyword: str | None = None,
        agreement: str | None = None,
        period: str | None = None,
        status: str | None = None,
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
        agreement: str | None = None,
        period: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._query(keyword=keyword, agreement=agreement, period=period, status=status)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def summarize(
        self,
        *,
        keyword: str | None = None,
        agreement: str | None = None,
        period: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """按当前筛选条件汇总：卡片指标与按结算周期分组的数字都来自这里，保证和列表同源。"""
        rows = self._query(keyword=keyword, agreement=agreement, period=period, status=status)
        month_prefix = date.today().strftime("%Y-%m")
        pending_review = 0
        rejected_total = 0
        month_paid = 0.0
        groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            payable = round(float(row.get("应付金额") or 0), 2)
            paid = round(float(row.get("已付金额") or 0), 2)
            if row.get("status") == STATUS_REVIEW:
                pending_review += 1
            rejected_total += int(row.get("驳回次数") or 0)
            for record in row.get("付款记录") or []:
                if str(record.get("付款日期", "")).startswith(month_prefix):
                    month_paid += float(record.get("付款金额") or 0)
            name = str(row.get("结算周期") or "未填周期")
            group = groups.setdefault(
                name,
                {"结算周期": name, "单据数": 0, "应付金额合计": 0.0, "已付金额合计": 0.0},
            )
            group["单据数"] += 1
            group["应付金额合计"] = round(group["应付金额合计"] + payable, 2)
            group["已付金额合计"] = round(group["已付金额合计"] + paid, 2)
        return {
            "cards": [
                {"label": "待审核结算", "value": pending_review},
                {"label": "本月付款金额", "value": round(month_paid, 2)},
                {"label": "已驳回单据", "value": rejected_total},
            ],
            "periods": [groups[key] for key in sorted(groups)],
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        code = str(values["结算单号"]).strip()
        rows = store.rows(MODULE)
        if any(str(row.get("结算单号") or "").strip() == code for row in rows):
            return None, f"结算单号 {code} 已存在，编号重复，请勿重复登记"
        payable = _to_amount(values.get("应付金额"))
        if payable is None:
            return None, "应付金额必须是大于 0 的数字，结算单未登记"
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({
            "结算单号": code,
            "关联协议": str(values["关联协议"]).strip(),
            "结算周期": str(values["结算周期"]).strip(),
            "应付金额": payable,
        })
        entry["status"] = STATUS_DRAFT
        entry["结算状态"] = STATUS_DRAFT
        entry["pending"] = True
        entry["abnormal"] = False
        entry["已付金额"] = 0.0
        entry["审核人员"] = ""
        entry["付款日期"] = ""
        entry["付款记录"] = []
        entry["驳回次数"] = 0
        rows.append(entry)
        return entry, ""

    # ---- 状态流转 ----
    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"结算单 {entry_id} 不存在或已归档"
        if action == ACTION_SUBMIT:
            return self._submit(entry)
        if action == ACTION_PAY:
            return self._pay(entry, values or {})
        if action == ACTION_REJECT:
            return self._reject(entry)
        return None, f"动作「{action}」不属于保障结算可执行范围"

    def _submit(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        status = entry.get("status")
        if status != STATUS_DRAFT:
            return None, f"当前状态为「{status}」，只有待核算的结算单可以提交审核"
        # 驳回回退时已清空付款信息，这里提交后从零开始累计
        entry["status"] = STATUS_REVIEW
        entry["结算状态"] = STATUS_REVIEW
        entry["pending"] = True
        entry["abnormal"] = False
        return entry, "结算单已提交审核，等待确认付款"

    def _pay(
        self, entry: dict[str, Any], values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        status = entry.get("status")
        if status != STATUS_REVIEW:
            return None, f"当前状态为「{status}」，只有待审核的结算单可以确认付款"
        code = str(values.get("付款编号") or "").strip()
        if not code:
            return None, "付款失败：缺少付款编号，无法登记本次付款记录"
        amount = _to_amount(values.get("付款金额"))
        if amount is None:
            return None, "付款失败：本次付款金额必须是大于 0 的数字"
        pay_date = str(values.get("付款日期") or "").strip() or date.today().isoformat()
        for row in store.rows(MODULE):
            if any(str(record.get("付款编号") or "") == code for record in row.get("付款记录") or []):
                return None, f"付款失败：付款编号 {code} 已存在，编号重复，请勿重复登记"
        payable = round(float(entry.get("应付金额") or 0), 2)
        paid = round(float(entry.get("已付金额") or 0), 2)
        remaining = round(payable - paid, 2)
        if amount > remaining + MONEY_EPS:
            overflow = round(amount - remaining, 2)
            return (
                None,
                f"付款失败：本次付款 {amount:.2f} 元，超出剩余可付金额 {remaining:.2f} 元，"
                f"超额 {overflow:.2f} 元，请调整金额后重试",
            )
        records = entry.setdefault("付款记录", [])
        records.append({"付款编号": code, "付款金额": amount, "付款日期": pay_date})
        new_paid = round(paid + amount, 2)
        entry["已付金额"] = new_paid
        entry["付款日期"] = pay_date
        if new_paid + MONEY_EPS >= payable:
            entry["status"] = STATUS_PAID
            entry["结算状态"] = STATUS_PAID
            entry["pending"] = False
            entry["abnormal"] = False
            return entry, f"付款成功：本次登记 {amount:.2f} 元，已结清应付 {payable:.2f} 元"
        entry["status"] = STATUS_REVIEW
        entry["结算状态"] = STATUS_REVIEW
        entry["pending"] = True
        return (
            entry,
            f"付款成功：本次登记 {amount:.2f} 元，累计已付 {new_paid:.2f} 元，"
            f"剩余可付 {round(payable - new_paid, 2):.2f} 元",
        )

    def _reject(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        status = entry.get("status")
        if status != STATUS_REVIEW:
            return None, f"当前状态为「{status}」，只有待审核的结算单可以驳回"
        # 退回待核算并清空本次付款信息，重新提交时从零开始累计
        entry["status"] = STATUS_DRAFT
        entry["结算状态"] = STATUS_DRAFT
        entry["pending"] = True
        entry["abnormal"] = True
        entry["付款记录"] = []
        entry["已付金额"] = 0.0
        entry["付款日期"] = ""
        entry["驳回次数"] = int(entry.get("驳回次数") or 0) + 1
        return entry, "结算单已驳回并退回待核算，本次付款记录与付款日期已清空"
