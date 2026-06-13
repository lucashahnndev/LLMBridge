from __future__ import annotations

import enum
import json
from datetime import datetime, timezone
from typing import Any

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
TELEGRAM_API_BASE = "https://api.telegram.org"

_MARKDOWN_V2_SPECIALS = "\\_*[]()~`>#+-=|{}.!\""


def _escape_markdown_v2(text: str) -> str:
    escaped = text.replace("\\", "\\\\")
    for char in _MARKDOWN_V2_SPECIALS:
        if char == "\\":
            continue
        escaped = escaped.replace(char, f"\\{char}")
    return escaped


def _escape_code_block(text: str) -> str:
    return text.replace("\\", "\\\\").replace("`", "\\`")


def _format_code_block(lines: list[str]) -> str:
    return "```text\n" + "\n".join(_escape_code_block(line) for line in lines) + "\n```"


def _format_summary_block(items: list[tuple[str, str]]) -> str:
    width = max((len(label) for label, _ in items), default=0)
    lines = [f"{label.ljust(width)}  {value}" for label, value in items]
    return _format_code_block(lines)


def _build_telegram_test_message() -> str:
    return "\n".join(
        [
            "LLMBridge Telegram test",
            f"Time: {_now_utc()}",
            "If you received this, Telegram delivery is working.",
        ]
    )


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


def _resolve_telegram_credentials(
    alert_settings: AlertSettings | None = None,
    *,
    telegram_bot_token: str | None = None,
    telegram_chat_id: str | None = None,
) -> tuple[str, str]:
    settings = get_settings()

    override_token = telegram_bot_token.strip() if telegram_bot_token else ""
    override_chat_id = telegram_chat_id.strip() if telegram_chat_id else ""

    stored_token = ""
    stored_chat_id = ""
    if alert_settings is not None:
        stored_token = (
            decrypt_text(alert_settings.telegram_bot_token_encrypted)
            if alert_settings.telegram_bot_token_encrypted
            else settings.telegram_bot_token
        ).strip()
        stored_chat_id = (alert_settings.telegram_chat_id or settings.telegram_chat_id).strip()
    else:
        stored_token = settings.telegram_bot_token.strip()
        stored_chat_id = settings.telegram_chat_id.strip()

    bot_token = override_token or stored_token
    chat_id = override_chat_id or stored_chat_id

    if not bot_token:
        raise RuntimeError("Telegram bot token is not configured")
    if not chat_id:
        raise RuntimeError("Telegram chat ID is not configured")

    return bot_token, chat_id


async def _send_telegram_message(
    *,
    bot_token: str,
    chat_id: str,
    text: str,
    reply_to_message_id: int | None = None,
    parse_mode: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
    if parse_mode is not None:
        payload["parse_mode"] = parse_mode

    async with httpx.AsyncClient(timeout=10.0) as client:
        await _telegram_request(client, bot_token, "sendMessage", payload)


async def _telegram_request(
    client: httpx.AsyncClient,
    bot_token: str,
    method: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/{method}"
    response = await client.post(url, json=payload)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Telegram API returned a non-object payload")
    if data.get("ok") is False:
        raise RuntimeError(f"Telegram API error: {data}")
    return data


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
    parse_mode: str | None = None,
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

    await _send_telegram_message(
        bot_token=bot_token,
        chat_id=chat_id,
        text=message,
        parse_mode=parse_mode,
    )
    return True


async def send_telegram_test_message(
    session: AsyncSession,
    *,
    telegram_bot_token: str | None = None,
    telegram_chat_id: str | None = None,
) -> str:
    alert_settings = await get_alert_settings(session)
    bot_token, chat_id = _resolve_telegram_credentials(
        alert_settings,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
    )
    message = _build_telegram_test_message()
    await _send_telegram_message(bot_token=bot_token, chat_id=chat_id, text=message)
    return chat_id


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def _coerce_error_log(error: str | dict[str, object] | list[object] | None) -> str:
    if error is None:
        return "Proxy request failed"
    if isinstance(error, str):
        text = error.strip()
        return text or "Proxy request failed"
    if isinstance(error, list):
        return json.dumps(error, ensure_ascii=False, indent=2)
    detail = error.get("detail") if isinstance(error, dict) else None
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    nested_error = error.get("error") if isinstance(error, dict) else None
    if isinstance(nested_error, dict):
        message = nested_error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return json.dumps(error, ensure_ascii=False, indent=2)


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
    summary = _format_summary_block(
        [
            ("Time", _now_utc()),
            ("App token", app_token_name),
            ("Requested model", requested_model),
            ("Final route", final_route or "n/a"),
            ("Route kind", route_kind),
            ("Queue", queue_name or "n/a"),
            ("Protocol in/out", f"{protocol_in} / {protocol_out}"),
            ("Status", str(status_code)),
            ("Attempts", str(attempts)),
            ("Rotated", "yes" if rotated else "no"),
            ("Tool calling", "yes" if tool_calling else "no"),
        ]
    )
    error_log = _format_code_block([_coerce_error_log(error)])
    return "\n".join(
        [
            f"*{_escape_markdown_v2('LLMBridge Proxy failure')}*",
            summary,
            "*Error log*",
            error_log,
        ]
    )


def format_queue_exhausted_alert(
    *,
    app_token_name: str,
    queue_name: str,
    requested_model: str,
    protocol_in: str,
    protocol_out: str,
    error: str | dict[str, object] | list[object] | None,
) -> str:
    summary = _format_summary_block(
        [
            ("Time", _now_utc()),
            ("App token", app_token_name),
            ("Queue", queue_name),
            ("Requested model", requested_model),
            ("Protocol in/out", f"{protocol_in} / {protocol_out}"),
        ]
    )
    error_log = _format_code_block([_coerce_error_log(error)])
    return "\n".join(
        [
            f"*{_escape_markdown_v2('LLMBridge Queue exhausted')}*",
            summary,
            "*Error log*",
            error_log,
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
    summary = _format_summary_block(
        [
            ("Time", _now_utc()),
            ("App token", app_token_name),
            ("Provider", provider),
            ("Requested model", requested_model),
            ("Protocol in/out", f"{protocol_in} / {protocol_out}"),
        ]
    )
    error_log = _format_code_block([_coerce_error_log(error)])
    return "\n".join(
        [
            f"*{_escape_markdown_v2('LLMBridge Provider pool exhausted')}*",
            summary,
            "*Error log*",
            error_log,
        ]
    )
