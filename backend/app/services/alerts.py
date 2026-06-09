from __future__ import annotations

import enum
import json
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.database.models import AlertSettings
from backend.app.services.crypto import decrypt_text, encrypt_text


class AlertChannel(str, enum.Enum):
    PROXY_FAILURE = "proxy_failure"
    QUEUE_EXHAUSTED = "queue_exhausted"
    PROVIDER_POOL_EXHAUSTED = "provider_pool_exhausted"
    PROVIDER_KEY_STATUS_CHANGE = "provider_key_status_change"


ALERT_SETTINGS_KEY = "global"


def _default_alert_settings() -> AlertSettings:
    settings = get_settings()
    telegram_token = settings.telegram_bot_token.strip() if settings.telegram_bot_token else ""
    telegram_chat_id = settings.telegram_chat_id.strip() if settings.telegram_chat_id else ""
    return AlertSettings(
        key=ALERT_SETTINGS_KEY,
        telegram_enabled=bool(telegram_token and telegram_chat_id),
        telegram_bot_token_encrypted=encrypt_text(telegram_token) if telegram_token else None,
        telegram_chat_id=telegram_chat_id or None,
        alert_proxy_failures=True,
        alert_queue_exhausted=True,
        alert_provider_pool_exhausted=True,
        alert_provider_key_status_changes=True,
    )


async def get_alert_settings(session: AsyncSession) -> AlertSettings:
    result = await session.execute(select(AlertSettings).where(AlertSettings.key == ALERT_SETTINGS_KEY))
    alert_settings = result.scalar_one_or_none()
    if alert_settings is None:
        alert_settings = _default_alert_settings()
        session.add(alert_settings)
        await session.commit()
        await session.refresh(alert_settings)
    return alert_settings


async def update_alert_settings(
    session: AsyncSession,
    *,
    telegram_enabled: bool | None = None,
    telegram_bot_token: str | None = None,
    telegram_chat_id: str | None = None,
    alert_proxy_failures: bool | None = None,
    alert_queue_exhausted: bool | None = None,
    alert_provider_pool_exhausted: bool | None = None,
    alert_provider_key_status_changes: bool | None = None,
) -> AlertSettings:
    alert_settings = await get_alert_settings(session)

    if telegram_enabled is not None:
        alert_settings.telegram_enabled = telegram_enabled
    if telegram_bot_token is not None:
        cleaned_token = telegram_bot_token.strip()
        alert_settings.telegram_bot_token_encrypted = encrypt_text(cleaned_token) if cleaned_token else None
    if telegram_chat_id is not None:
        cleaned_chat_id = telegram_chat_id.strip()
        alert_settings.telegram_chat_id = cleaned_chat_id or None
    if alert_proxy_failures is not None:
        alert_settings.alert_proxy_failures = alert_proxy_failures
    if alert_queue_exhausted is not None:
        alert_settings.alert_queue_exhausted = alert_queue_exhausted
    if alert_provider_pool_exhausted is not None:
        alert_settings.alert_provider_pool_exhausted = alert_provider_pool_exhausted
    if alert_provider_key_status_changes is not None:
        alert_settings.alert_provider_key_status_changes = alert_provider_key_status_changes

    await session.commit()
    await session.refresh(alert_settings)
    return alert_settings


def _is_channel_enabled(alert_settings: AlertSettings, channel: AlertChannel | None) -> bool:
    if channel is None:
        return alert_settings.telegram_enabled
    if channel == AlertChannel.PROXY_FAILURE:
        return alert_settings.telegram_enabled and alert_settings.alert_proxy_failures
    if channel == AlertChannel.QUEUE_EXHAUSTED:
        return alert_settings.telegram_enabled and alert_settings.alert_queue_exhausted
    if channel == AlertChannel.PROVIDER_POOL_EXHAUSTED:
        return alert_settings.telegram_enabled and alert_settings.alert_provider_pool_exhausted
    if channel == AlertChannel.PROVIDER_KEY_STATUS_CHANGE:
        return alert_settings.telegram_enabled and alert_settings.alert_provider_key_status_changes
    return alert_settings.telegram_enabled


async def send_telegram_alert(
    message: str,
    *,
    session: AsyncSession | None = None,
    channel: AlertChannel | str | None = None,
) -> bool:
    settings = get_settings()
    alert_settings: AlertSettings | None = None
    if session is not None:
        alert_settings = await get_alert_settings(session)
        if isinstance(channel, str):
            channel = AlertChannel(channel)
        if not _is_channel_enabled(alert_settings, channel):
            return False
        bot_token = (
            decrypt_text(alert_settings.telegram_bot_token_encrypted)
            if alert_settings.telegram_bot_token_encrypted
            else settings.telegram_bot_token
        )
        chat_id = alert_settings.telegram_chat_id or settings.telegram_chat_id
    else:
        bot_token = settings.telegram_bot_token
        chat_id = settings.telegram_chat_id

    if not bot_token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
    return True


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _coerce_error_message(error: str | dict[str, object] | list[object] | None) -> str:
    if error is None:
        return "Proxy request failed"
    if isinstance(error, str):
        text = error.strip()
        return text or "Proxy request failed"
    if isinstance(error, list):
        return json.dumps(error, ensure_ascii=False)
    detail = error.get("detail") if isinstance(error, dict) else None
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    nested_error = error.get("error") if isinstance(error, dict) else None
    if isinstance(nested_error, dict):
        message = nested_error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return json.dumps(error, ensure_ascii=False)


def format_proxy_failure_alert(
    *,
    app_token_name: str,
    requested_model: str,
    final_route: str | None,
    route_kind: str,
    queue_name: str | None,
    protocol_in: str,
    protocol_out: str,
    status_code: int,
    attempts: int,
    tool_calling: bool,
    rotated: bool,
    error: str | dict[str, object] | list[object] | None,
) -> str:
    lines = [
        "[LLMBridge] Proxy failure",
        f"Time: {_now_utc()}",
        f"App token: {app_token_name}",
        f"Requested model: {requested_model}",
        f"Final route: {final_route or 'n/a'}",
        f"Route kind: {route_kind}",
    ]
    if queue_name:
        lines.append(f"Queue: {queue_name}")
    lines.extend(
        [
            f"Protocol in/out: {protocol_in}/{protocol_out}",
            f"Status: {status_code}",
            f"Attempts: {attempts}",
            f"Rotated: {'yes' if rotated else 'no'}",
            f"Tool calling: {'yes' if tool_calling else 'no'}",
            f"Error: {_coerce_error_message(error)}",
        ]
    )
    return "\n".join(lines)


def format_queue_exhausted_alert(
    *,
    app_token_name: str,
    queue_name: str,
    requested_model: str,
    protocol_in: str,
    protocol_out: str,
    error: str | dict[str, object] | list[object] | None,
) -> str:
    return "\n".join(
        [
            "[LLMBridge] Queue exhausted",
            f"Time: {_now_utc()}",
            f"App token: {app_token_name}",
            f"Queue: {queue_name}",
            f"Requested model: {requested_model}",
            f"Protocol in/out: {protocol_in}/{protocol_out}",
            f"Error: {_coerce_error_message(error)}",
        ]
    )


def format_provider_pool_exhausted_alert(
    *,
    app_token_name: str,
    provider: str,
    requested_model: str,
    protocol_in: str,
    protocol_out: str,
    error: str | dict[str, object] | list[object] | None,
) -> str:
    return "\n".join(
        [
            "[LLMBridge] Provider pool exhausted",
            f"Time: {_now_utc()}",
            f"App token: {app_token_name}",
            f"Provider: {provider}",
            f"Requested model: {requested_model}",
            f"Protocol in/out: {protocol_in}/{protocol_out}",
            f"Error: {_coerce_error_message(error)}",
        ]
    )
