"""保障结算接口：维护结算单，覆盖提交审核、确认付款、驳回结算等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.settlement import (
    ACTION_PAY,
    ACTION_REJECT,
    ACTION_SUBMIT,
    SettlementService,
)

router = APIRouter(prefix="/api/settlement", tags=["保障结算"])

service = SettlementService()

LIST_FIELDS = ["结算单号", "关联协议", "结算周期", "应付金额", "已付金额", "审核人员", "付款日期", "结算状态"]
STATUSES = ["待核算", "待审核", "已付款"]
ACTION_FIELDS = {
    ACTION_SUBMIT: [],
    ACTION_PAY: ["付款编号", "付款金额", "付款日期"],
    ACTION_REJECT: [],
}


def _list_kwargs(
    keyword: str | None,
    agreement: str | None,
    period: str | None,
    status: str | None,
) -> dict[str, Any]:
    return {"keyword": keyword, "agreement": agreement, "period": period, "status": status}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按结算单号检索"),
    agreement: str | None = Query(default=None, alias="关联协议", description="按关联协议检索"),
    period: str | None = Query(default=None, alias="结算周期", description="按结算周期检索"),
    status: str | None = Query(default=None, description="待核算、待审核、已付款"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按结算单号、关联协议、结算周期与状态过滤保障结算列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        **_list_kwargs(keyword, agreement, period, status), page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/summary")
def summarize(
    keyword: str | None = Query(default=None, description="按结算单号检索"),
    agreement: str | None = Query(default=None, alias="关联协议", description="按关联协议检索"),
    period: str | None = Query(default=None, alias="结算周期", description="按结算周期检索"),
    status: str | None = Query(default=None, description="待核算、待审核、已付款"),
) -> dict[str, Any]:
    """汇总卡片与按结算周期的分组金额；筛选口径与列表接口完全一致。"""
    return service.summarize(**_list_kwargs(keyword, agreement, period, status))


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出保障结算清单：返回当前全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "settlement", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条结算单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"结算单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条结算单，缺字段或编号重复时说明原因而不是静默丢弃。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message="结算单已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条结算单执行提交审核、确认付款、驳回结算；超额付款与编号重复等校验失败会原样说明原因。"""
    values = payload.values or {}
    action = str(values.get("action") or "").strip()
    if action not in ACTION_FIELDS:
        return ActionResult(ok=False, message=f"动作「{action}」不属于保障结算可执行范围")
    extra = {field: values.get(field) for field in ACTION_FIELDS[action] if values.get(field) is not None}
    entry, message = service.run_action(entry_id, action, extra)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
