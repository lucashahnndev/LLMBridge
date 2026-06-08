from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.database.models import KeyStatus, ProviderKey
from backend.app.database.session import get_session
from backend.app.schemas.provider_keys import (
    ProviderKeyCreate,
    ProviderKeyPeekRequest,
    ProviderKeyPeekResponse,
    ProviderKeyResponse,
    ProviderKeyUpdate,
)
from backend.app.services.auth import require_admin
from backend.app.services.crypto import decrypt_text, encrypt_text
from backend.app.services.records import provider_key_response
from backend.app.services.alerts import send_telegram_alert
from backend.app.services.metrics import format_key_status_alert, format_provider_pool_alert
from backend.app.services.records import ensure_utc_datetime


router = APIRouter(prefix="/provider-keys", tags=["provider-keys"], dependencies=[Depends(require_admin)])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_provider_key_or_404(session: AsyncSession, provider_key_id: int) -> ProviderKey:
    provider_key = await session.get(ProviderKey, provider_key_id)
    if provider_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider key not found")
    return provider_key


@router.post("", response_model=ProviderKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_provider_key(payload: ProviderKeyCreate, session: SessionDep) -> ProviderKeyResponse:
    provider_key = ProviderKey(
        name=payload.name,
        description=payload.description,
        provider=payload.provider,
        encrypted_token=encrypt_text(payload.token),
        status=KeyStatus.ACTIVE,
    )
    session.add(provider_key)
    await session.commit()
    await session.refresh(provider_key)
    return provider_key_response(provider_key)


@router.get("", response_model=list[ProviderKeyResponse])
async def list_provider_keys(
    session: SessionDep,
    provider: str | None = None,
    status_filter: KeyStatus | None = Query(default=None, alias="status"),
) -> list[ProviderKeyResponse]:
    stmt = select(ProviderKey).order_by(ProviderKey.id.desc())
    if provider:
        stmt = stmt.where(ProviderKey.provider == provider)
    if status_filter is not None:
        stmt = stmt.where(ProviderKey.status == status_filter)
    result = await session.execute(stmt)
    return [provider_key_response(row) for row in result.scalars().all()]


@router.get("/{provider_key_id}", response_model=ProviderKeyResponse)
async def get_provider_key(provider_key_id: int, session: SessionDep) -> ProviderKeyResponse:
    provider_key = await get_provider_key_or_404(session, provider_key_id)
    return provider_key_response(provider_key)


@router.patch("/{provider_key_id}", response_model=ProviderKeyResponse)
async def update_provider_key(
    provider_key_id: int,
    payload: ProviderKeyUpdate,
    session: SessionDep,
) -> ProviderKeyResponse:
    provider_key = await get_provider_key_or_404(session, provider_key_id)
    previous_status = provider_key.status

    update_data = payload.model_dump(exclude_unset=True)
    if "status" in update_data and update_data["status"] is not None:
        update_data["status"] = KeyStatus(update_data["status"].value)
        if update_data["status"] == KeyStatus.COOLDOWN and "blocked_until" not in update_data:
            update_data["blocked_until"] = datetime.now(timezone.utc) + timedelta(
                seconds=get_settings().key_cooldown_seconds
            )
        elif update_data["status"] == KeyStatus.ACTIVE:
            update_data.setdefault("blocked_until", None)
            update_data.setdefault("failure_count", 0)

    for field, value in update_data.items():
        setattr(provider_key, field, value)

    await session.commit()
    await session.refresh(provider_key)

    if provider_key.status != previous_status and provider_key.status in {
        KeyStatus.COOLDOWN,
        KeyStatus.INVALID,
        KeyStatus.SUSPENDED_BILLING,
    }:
        await send_telegram_alert(
            format_key_status_alert(
                provider=provider_key.provider,
                key_name=provider_key.name,
                new_status=provider_key.status.value,
                blocked_until=ensure_utc_datetime(provider_key.blocked_until).isoformat()
                if ensure_utc_datetime(provider_key.blocked_until)
                else None,
            )
        )

        total_stmt = select(func.count(ProviderKey.id)).where(ProviderKey.provider == provider_key.provider)
        active_stmt = select(func.count(ProviderKey.id)).where(
            ProviderKey.provider == provider_key.provider,
            ProviderKey.status == KeyStatus.ACTIVE,
        )
        total_count = int((await session.execute(total_stmt)).scalar_one())
        active_count = int((await session.execute(active_stmt)).scalar_one())
        if total_count > 0 and active_count == 0:
            await send_telegram_alert(
                format_provider_pool_alert(provider=provider_key.provider, active_count=active_count, total_count=total_count)
            )

    return provider_key_response(provider_key)


@router.delete("/{provider_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_key(provider_key_id: int, session: SessionDep) -> Response:
    provider_key = await get_provider_key_or_404(session, provider_key_id)
    await session.delete(provider_key)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{provider_key_id}/peek", response_model=ProviderKeyPeekResponse)
async def peek_provider_key(
    provider_key_id: int,
    payload: ProviderKeyPeekRequest,
    session: SessionDep,
) -> ProviderKeyPeekResponse:
    settings = get_settings()
    if not settings.admin_password:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Admin password not configured")
    if payload.admin_password != settings.admin_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin password")

    provider_key = await get_provider_key_or_404(session, provider_key_id)
    token = decrypt_text(provider_key.encrypted_token)
    return ProviderKeyPeekResponse(token=token)
