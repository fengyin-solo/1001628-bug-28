"""保障结算接口：维护结算单，覆盖提交审核、确认付款、驳回结算等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.settlement import STATUS_ORDER, SettlementService

router = APIRouter(prefix="/api/settlement", tags=["保障结算"])

service = SettlementService()

LIST_FIELDS = ["结算单号", "关联协议", "结算周期", "应付金额", "已付金额", "审核人员", "付款日期", "结算状态"]
STATUSES = STATUS_ORDER


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按结算单号检索"),
    status: str | None = Query(default=None, description="待核算、待审核、已付款"),
    agreement: str | None = Query(default=None, description="按关联协议检索"),
    period: str | None = Query(default=None, description="按结算周期检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按结算单号与状态过滤保障结算列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, status=status, agreement=agreement, period=period, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/summary")
def summarize(
    keyword: str | None = Query(default=None, description="按结算单号检索，与列表同口径"),
    status: str | None = Query(default=None, description="待核算、待审核、已付款"),
    agreement: str | None = Query(default=None, description="按关联协议检索"),
    period: str | None = Query(default=None, description="按结算周期检索"),
) -> dict[str, Any]:
    """汇总卡片与按结算周期的分组数字，筛选条件与列表页完全一致。"""
    return service.summarize(keyword=keyword, status=status, agreement=agreement, period=period)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出保障结算清单：返回当前过滤条件下的全量数据。"""
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
    entry, missing, error = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if entry is None:
        return ActionResult(ok=False, message=error)
    return ActionResult(ok=True, message="结算单已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条结算单执行提交审核、确认付款、驳回结算；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
