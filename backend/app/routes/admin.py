from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database.session import get_session
from backend.app.schemas.alerts import AlertSettingsResponse, AlertSettingsUpdate, AlertTelegramTestRequest, AlertTelegramTestResponse
from backend.app.schemas.runtime import RuntimeConfigResponse, RuntimeConfigUpdate
from backend.app.services.auth import require_admin
from backend.app.services.alerts import get_alert_settings, send_telegram_test_message, update_alert_settings
from backend.app.services.runtime import read_runtime_config, update_runtime_config


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/runtime", response_model=RuntimeConfigResponse)
async def get_runtime_config() -> RuntimeConfigResponse:
    return read_runtime_config()


@router.patch("/runtime", response_model=RuntimeConfigResponse)
async def patch_runtime_config(payload: RuntimeConfigUpdate) -> RuntimeConfigResponse:
    return update_runtime_config(host=payload.host, port=payload.port)


@router.get("/alerts", response_model=AlertSettingsResponse)
async def get_alert_preferences(session: SessionDep) -> AlertSettingsResponse:
    return await get_alert_settings(session)


@router.patch("/alerts", response_model=AlertSettingsResponse)
async def patch_alert_preferences(payload: AlertSettingsUpdate, session: SessionDep) -> AlertSettingsResponse:
    return await update_alert_settings(
        session,
        telegram_enabled=payload.telegram_enabled,
        telegram_bot_token=payload.telegram_bot_token,
        telegram_chat_id=payload.telegram_chat_id,
        alert_proxy_failures=payload.alert_proxy_failures,
        alert_queue_exhausted=payload.alert_queue_exhausted,
        alert_provider_pool_exhausted=payload.alert_provider_pool_exhausted,
        alert_provider_key_status_changes=payload.alert_provider_key_status_changes,
    )


@router.post("/alerts/test", response_model=AlertTelegramTestResponse)
async def post_alert_test(payload: AlertTelegramTestRequest, session: SessionDep) -> AlertTelegramTestResponse:
    try:
        chat_id = await send_telegram_test_message(
            session,
            telegram_bot_token=payload.telegram_bot_token,
            telegram_chat_id=payload.telegram_chat_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return AlertTelegramTestResponse(detail=f"Telegram test message sent to chat {chat_id}.")
