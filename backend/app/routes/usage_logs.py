from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database.models import UsageLog
from backend.app.database.session import get_session
from backend.app.schemas.usage_logs import UsageLogCreate, UsageLogPageResponse, UsageLogResponse
from backend.app.services.auth import require_admin
from backend.app.services.records import usage_log_response


router = APIRouter(prefix="/usage-logs", tags=["usage-logs"], dependencies=[Depends(require_admin)])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_usage_log_or_404(session: AsyncSession, usage_log_id: int) -> UsageLog:
    stmt = (
        select(UsageLog)
        .options(selectinload(UsageLog.app_token), selectinload(UsageLog.provider_key))
        .where(UsageLog.id == usage_log_id)
    )
    result = await session.execute(stmt)
    usage_log = result.scalar_one_or_none()
    if usage_log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usage log not found")
    return usage_log


async def get_usage_log_with_relations(session: AsyncSession, usage_log_id: int) -> UsageLog:
    return await get_usage_log_or_404(session, usage_log_id)


@router.post("", response_model=UsageLogResponse, status_code=status.HTTP_201_CREATED)
async def create_usage_log(payload: UsageLogCreate, session: SessionDep) -> UsageLogResponse:
    usage_log = UsageLog(**payload.model_dump())
    session.add(usage_log)
    await session.commit()
    await session.refresh(usage_log)
    return usage_log_response(await get_usage_log_with_relations(session, usage_log.id))


@router.get("", response_model=UsageLogPageResponse)
async def list_usage_logs(
    session: SessionDep,
    app_token_id: int | None = None,
    provider_key_id: int | None = None,
    queue_name: str | None = None,
    protocol_in: str | None = None,
    protocol_out: str | None = None,
    route_kind: str | None = None,
    tool_calling: bool | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> UsageLogPageResponse:
    stmt = (
        select(UsageLog)
        .options(selectinload(UsageLog.app_token), selectinload(UsageLog.provider_key))
        .order_by(desc(UsageLog.created_at), desc(UsageLog.id))
    )
    if app_token_id is not None:
        stmt = stmt.where(UsageLog.app_token_id == app_token_id)
    if provider_key_id is not None:
        stmt = stmt.where(UsageLog.provider_key_id == provider_key_id)
    if queue_name is not None:
        stmt = stmt.where(UsageLog.queue_name == queue_name)
    if protocol_in is not None:
        stmt = stmt.where(UsageLog.protocol_in == protocol_in)
    if protocol_out is not None:
        stmt = stmt.where(UsageLog.protocol_out == protocol_out)
    if route_kind is not None:
        stmt = stmt.where(UsageLog.route_kind == route_kind)
    if tool_calling is not None:
        stmt = stmt.where(UsageLog.tool_calling.is_(tool_calling))

    total_stmt = select(func.count(UsageLog.id))
    if app_token_id is not None:
        total_stmt = total_stmt.where(UsageLog.app_token_id == app_token_id)
    if provider_key_id is not None:
        total_stmt = total_stmt.where(UsageLog.provider_key_id == provider_key_id)
    if queue_name is not None:
        total_stmt = total_stmt.where(UsageLog.queue_name == queue_name)
    if protocol_in is not None:
        total_stmt = total_stmt.where(UsageLog.protocol_in == protocol_in)
    if protocol_out is not None:
        total_stmt = total_stmt.where(UsageLog.protocol_out == protocol_out)
    if route_kind is not None:
        total_stmt = total_stmt.where(UsageLog.route_kind == route_kind)
    if tool_calling is not None:
        total_stmt = total_stmt.where(UsageLog.tool_calling.is_(tool_calling))

    total = int((await session.execute(total_stmt)).scalar_one())
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    items = [usage_log_response(row) for row in result.scalars().all()]
    return UsageLogPageResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{usage_log_id}", response_model=UsageLogResponse)
async def get_usage_log(usage_log_id: int, session: SessionDep) -> UsageLogResponse:
    usage_log = await get_usage_log_with_relations(session, usage_log_id)
    return usage_log_response(usage_log)
