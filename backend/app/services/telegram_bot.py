from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.core.config import get_settings
from backend.app.core.version import APP_VERSION, SCHEMA_VERSION
from backend.app.database.models import AlertSettings, AppToken, KeyStatus, ModelQueue, ProviderKey, UsageLog
from backend.app.services.alerts import get_alert_settings, update_alert_settings
from backend.app.services.metrics import build_app_token_overview, build_provider_overview, build_queue_overview
from backend.app.services.runtime import read_runtime_config


logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_POLL_TIMEOUT = 20
TELEGRAM_POLL_IDLE_SECONDS = 5
TELEGRAM_ERROR_BACKOFF_SECONDS = 10

_MARKDOWN_V2_SPECIALS = "\\_*[]()~`>#+-=|{}.!\""


@dataclass(slots=True)
class TelegramMessage:
    chat_id: str
    text: str
    reply_to_message_id: int | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def parse_telegram_command(text: str | None) -> tuple[str, list[str]]:
    if not text:
        return "", []
    cleaned = text.strip()
    if not cleaned.startswith("/"):
        return "", []
    first_line = cleaned.splitlines()[0].strip()
    parts = first_line.split()
    if not parts:
        return "", []
    command = parts[0][1:]
    if "@" in command:
        command = command.split("@", 1)[0]
    command = command.lower()
    args = [part.strip() for part in parts[1:] if part.strip()]
    return command, args


def _toggle_label(enabled: bool) -> str:
    return "on" if enabled else "off"


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


def _format_kv_block(items: list[tuple[str, str]]) -> str:
    width = max((len(label) for label, _ in items), default=0)
    return _format_code_block([f"{label.ljust(width)}  {value}" for label, value in items])


def _title(text: str) -> str:
    return f"*{_escape_markdown_v2(text)}*"


def _truncate(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]
    return text[: max_length - 3] + "..."


def build_help_message() -> str:
    return "\n".join(
        [
            _title("LLMBridge Telegram"),
            _format_code_block(
                [
                    "/status                service status",
                    "/runtime               runtime host and port",
                    "/apps                  app token summary",
                    "/app <id|name>         app token overview",
                    "/providers             provider summary",
                    "/provider <name>       provider overview",
                    "/queues                queue summary",
                    "/queue <name>          queue overview",
                    "/alerts                alert switches",
                    "/alerts on|off         enable or disable Telegram",
                    "/alerts proxy on|off   proxy failure alerts",
                    "/alerts queue on|off   queue exhausted alerts",
                    "/alerts provider on|off provider pool alerts",
                    "/alerts key on|off     provider key alerts",
                    "/link                  bind this chat if no chat is configured",
                ]
            ),
        ]
    )


def build_status_message(*, runtime_base_url: str) -> str:
    return "\n".join(
        [
            _title("LLMBridge status"),
            _format_kv_block(
                [
                    ("Service", get_settings().app_name),
                    ("Version", APP_VERSION),
                    ("Schema", SCHEMA_VERSION),
                    ("Runtime", runtime_base_url),
                    ("Checked", _utc_now()),
                ]
            ),
        ]
    )


def _format_summary_block(*, total_requests: int, success_rate: float, avg_latency_ms: float, total_tokens: int, rotations: int) -> list[str]:
    return [
        f"Requests: {total_requests}",
        f"Success: {success_rate:.1f}%",
        f"Latency: {avg_latency_ms:.1f} ms",
        f"Tokens: {total_tokens}",
        f"Rotations: {rotations}",
    ]


async def _provider_request_counts(session: AsyncSession) -> dict[str, int]:
    stmt = (
        select(UsageLog.provider_used, func.count(UsageLog.id))
        .group_by(UsageLog.provider_used)
        .order_by(func.count(UsageLog.id).desc(), UsageLog.provider_used.asc())
    )
    result = await session.execute(stmt)
    return {provider: int(count or 0) for provider, count in result.all() if provider}


async def _queue_request_counts(session: AsyncSession) -> dict[str, int]:
    stmt = (
        select(UsageLog.queue_name, func.count(UsageLog.id))
        .where(UsageLog.queue_name.is_not(None))
        .group_by(UsageLog.queue_name)
        .order_by(func.count(UsageLog.id).desc(), UsageLog.queue_name.asc())
    )
    result = await session.execute(stmt)
    return {queue_name: int(count or 0) for queue_name, count in result.all() if queue_name}


async def _build_apps_list_message(session: AsyncSession) -> str:
    stmt = (
        select(
            AppToken.id,
            AppToken.name,
            AppToken.environment,
            AppToken.is_active,
            func.count(UsageLog.id).label("requests_count"),
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("total_tokens_consumed"),
            func.coalesce(func.avg(UsageLog.latency_ms), 0.0).label("avg_latency_ms"),
        )
        .select_from(AppToken)
        .outerjoin(UsageLog, UsageLog.app_token_id == AppToken.id)
        .group_by(AppToken.id, AppToken.name, AppToken.environment, AppToken.is_active)
        .order_by(AppToken.id.desc())
    )
    result = await session.execute(stmt)
    rows = result.all()
    if not rows:
        return "\n".join([_title("LLMBridge app tokens"), _escape_markdown_v2("No app tokens found.")])
    lines = [_title("LLMBridge app tokens")]
    lines.append(
        _format_code_block(
            [
                "TOKEN NAME              ENVIRONMENT   STATUS    REQUESTS   TOKENS",
                "----------------------   -----------   -------   --------   -------",
            ]
        )
    )
    for row in rows[:8]:
        lines.append(
            _format_code_block(
                [
                    f"{_truncate(row.name, 22).ljust(22)}   {_truncate(row.environment.value, 11).ljust(11)}   "
                    f"{_truncate('ACTIVE' if row.is_active else 'OFF', 7).ljust(7)}   "
                    f"{str(int(row.requests_count or 0)).ljust(8)}   {str(int(row.total_tokens_consumed or 0)).ljust(7)}"
                ]
            )
        )
    return "\n".join(lines)


async def _build_providers_list_message(session: AsyncSession) -> str:
    result = await session.execute(
        select(ProviderKey.provider, func.count(ProviderKey.id).label("key_count")).group_by(ProviderKey.provider)
    )
    rows = result.all()
    if not rows:
        return "\n".join([_title("LLMBridge providers"), _escape_markdown_v2("No provider activity yet.")])
    provider_counts = await _provider_request_counts(session)
    lines = [_title("LLMBridge providers"), _format_code_block(["PROVIDER             REQUESTS   KEYS", "-------------------   --------   ----"])]
    for provider, key_count in rows[:8]:
        lines.append(
            _format_code_block(
                [
                    f"{_truncate(provider, 19).ljust(19)}   {str(provider_counts.get(provider, 0)).ljust(8)}   {str(int(key_count or 0)).ljust(4)}"
                ]
            )
        )
    return "\n".join(lines)


async def _build_queues_list_message(session: AsyncSession) -> str:
    result = await session.execute(select(ModelQueue.name, ModelQueue.strategy, ModelQueue.is_active).order_by(ModelQueue.id.desc()))
    queues = result.all()
    if not queues:
        return "\n".join([_title("LLMBridge queues"), _escape_markdown_v2("No queues found.")])
    queue_counts = await _queue_request_counts(session)
    lines = [_title("LLMBridge queues"), _format_code_block(["QUEUE                STRATEGY      STATUS    REQUESTS", "-------------------   ----------   -------   --------"])]
    for name, strategy, is_active in queues[:8]:
        lines.append(
            _format_code_block(
                [
                    f"{_truncate(name, 19).ljust(19)}   {_truncate(strategy.value, 10).ljust(10)}   {_truncate('ACTIVE' if is_active else 'OFF', 7).ljust(7)}   {str(queue_counts.get(name, 0)).ljust(8)}"
                ]
            )
        )
    return "\n".join(lines)


async def _resolve_app_token(session: AsyncSession, identifier: str) -> AppToken | None:
    if identifier.isdigit():
        return await session.get(AppToken, int(identifier))
    result = await session.execute(
        select(AppToken).where(func.lower(AppToken.name) == identifier.strip().lower()).order_by(AppToken.id.desc())
    )
    return result.scalar_one_or_none()


async def _build_app_overview_message(session: AsyncSession, identifier: str) -> str:
    app_token = await _resolve_app_token(session, identifier)
    if app_token is None:
        return "\n".join([_title("LLMBridge app token"), _escape_markdown_v2(f"App token '{identifier}' not found.")])
    overview = await build_app_token_overview(session, app_token.id, "24h")
    summary = overview.summary
    lines = [
        _title("LLMBridge app token"),
        _format_kv_block(
            [
                ("App", overview.context_label),
                ("Environment", app_token.environment.value),
                ("Token", app_token.masked_token),
            ]
        ),
        _format_kv_block(
            [
                ("Requests", str(summary.total_requests)),
                ("Success", f"{summary.success_rate:.1f}%"),
                ("Latency", f"{summary.avg_latency_ms:.1f} ms"),
                ("Tokens", str(summary.total_tokens_consumed)),
                ("Rotations", str(summary.total_rotations_triggered)),
            ]
        ),
    ]
    if overview.models:
        top_models = overview.models[:3]
        model_lines = ["MODELS               REQUESTS   TOKENS", "-------------------   --------   ------"]
        for model in top_models:
            model_lines.append(
                f"{_truncate(model.model_name, 19).ljust(19)}   {str(model.requests_count).ljust(8)}   {str(model.total_tokens_consumed).ljust(6)}"
            )
        lines.append(_format_code_block(model_lines))
    return "\n".join(lines)


async def _build_provider_overview_message(session: AsyncSession, provider: str) -> str:
    overview = await build_provider_overview(session, provider, "24h")
    key_result = await session.execute(
        select(ProviderKey).where(ProviderKey.provider == provider).order_by(ProviderKey.id.desc())
    )
    keys = key_result.scalars().all()
    active_keys = [key for key in keys if key.status == KeyStatus.ACTIVE]
    lines = [
        _title("LLMBridge provider"),
        _format_kv_block(
            [
                ("Provider", overview.context_label),
                ("Keys", f"{len(keys)} total / {len(active_keys)} active"),
            ]
        ),
        _format_kv_block(
            [
                ("Requests", str(overview.summary.total_requests)),
                ("Success", f"{overview.summary.success_rate:.1f}%"),
                ("Latency", f"{overview.summary.avg_latency_ms:.1f} ms"),
                ("Tokens", str(overview.summary.total_tokens_consumed)),
                ("Rotations", str(overview.summary.total_rotations_triggered)),
            ]
        ),
    ]
    if overview.models:
        model_lines = ["MODELS               REQUESTS   TOKENS", "-------------------   --------   ------"]
        for model in overview.models[:3]:
            model_lines.append(
                f"{_truncate(model.model_name, 19).ljust(19)}   {str(model.requests_count).ljust(8)}   {str(model.total_tokens_consumed).ljust(6)}"
            )
        lines.append(_format_code_block(model_lines))
    return "\n".join(lines)


async def _build_queue_overview_message(session: AsyncSession, queue_name: str) -> str:
    overview = await build_queue_overview(session, queue_name, "24h")
    lines = [
        _title("LLMBridge queue"),
        _format_kv_block(
            [
                ("Queue", overview.context_label),
                ("Requests", str(overview.summary.total_requests)),
                ("Success", f"{overview.summary.success_rate:.1f}%"),
                ("Latency", f"{overview.summary.avg_latency_ms:.1f} ms"),
                ("Tokens", str(overview.summary.total_tokens_consumed)),
                ("Rotations", str(overview.summary.total_rotations_triggered)),
            ]
        ),
    ]
    if overview.models:
        model_lines = ["MODELS               REQUESTS   TOKENS", "-------------------   --------   ------"]
        for model in overview.models[:5]:
            model_lines.append(
                f"{_truncate(model.model_name, 19).ljust(19)}   {str(model.requests_count).ljust(8)}   {str(model.total_tokens_consumed).ljust(6)}"
            )
        lines.append(_format_code_block(model_lines))
    return "\n".join(lines)


def build_runtime_message(*, host: str, port: int, restart_required: bool) -> str:
    return "\n".join(
        [
            _title("LLMBridge runtime"),
            _format_kv_block(
                [
                    ("Host", host),
                    ("Port", str(port)),
                    ("API base", f"http://{host}:{port}/api/v1"),
                    ("Restart required", "yes" if restart_required else "no"),
                ]
            ),
        ]
    )


def build_alerts_message(alert_settings: AlertSettings) -> str:
    chat_id = alert_settings.telegram_chat_id or "not configured"
    return "\n".join(
        [
            _title("LLMBridge alerts"),
            _format_kv_block(
                [
                    ("Telegram", _toggle_label(alert_settings.telegram_enabled)),
                    ("Chat ID", chat_id),
                    ("Proxy failures", _toggle_label(alert_settings.alert_proxy_failures)),
                    ("Queue exhausted", _toggle_label(alert_settings.alert_queue_exhausted)),
                    ("Provider pool", _toggle_label(alert_settings.alert_provider_pool_exhausted)),
                    ("Provider key", _toggle_label(alert_settings.alert_provider_key_status_changes)),
                ]
            ),
        ]
    )


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


async def send_telegram_message(
    client: httpx.AsyncClient,
    *,
    bot_token: str,
    chat_id: str,
    text: str,
    reply_to_message_id: int | None = None,
    parse_mode: str | None = "MarkdownV2",
) -> None:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = reply_to_message_id
    if parse_mode is not None:
        payload["parse_mode"] = parse_mode
    await _telegram_request(client, bot_token, "sendMessage", payload)


def _message_chat_id(update: dict[str, Any]) -> str | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return None
    chat_id = chat.get("id")
    if chat_id is None:
        return None
    return str(chat_id)


def _message_text(update: dict[str, Any]) -> str | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    text = message.get("text")
    return text if isinstance(text, str) else None


def _message_id(update: dict[str, Any]) -> int | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    message_id = message.get("message_id")
    return message_id if isinstance(message_id, int) else None


class TelegramBotWorker:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._offset = 0

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="telegram-bot-worker")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _run(self) -> None:
        timeout = httpx.Timeout(TELEGRAM_POLL_TIMEOUT + 10, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            while not self._stop_event.is_set():
                try:
                    async with self._sessionmaker() as session:
                        alert_settings = await get_alert_settings(session)
                        bot_token = self._resolve_bot_token(alert_settings)
                        chat_id = self._resolve_chat_id(alert_settings)
                        if not bot_token:
                            await asyncio.sleep(TELEGRAM_POLL_IDLE_SECONDS)
                            continue

                        updates = await self._poll_updates(client, bot_token)
                        if not updates:
                            await asyncio.sleep(TELEGRAM_POLL_IDLE_SECONDS)
                            continue

                        for update in updates:
                            await self._handle_update(
                                client=client,
                                session=session,
                                update=update,
                                bot_token=bot_token,
                                configured_chat_id=chat_id,
                            )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Telegram bot worker error: %s", exc, exc_info=True)
                    await asyncio.sleep(TELEGRAM_ERROR_BACKOFF_SECONDS)

    def _resolve_bot_token(self, alert_settings: AlertSettings) -> str:
        settings = get_settings()
        if alert_settings.telegram_bot_token_encrypted:
            from backend.app.services.crypto import decrypt_text

            return decrypt_text(alert_settings.telegram_bot_token_encrypted).strip()
        return settings.telegram_bot_token.strip()

    def _resolve_chat_id(self, alert_settings: AlertSettings) -> str:
        settings = get_settings()
        return (alert_settings.telegram_chat_id or settings.telegram_chat_id or "").strip()

    async def _poll_updates(self, client: httpx.AsyncClient, bot_token: str) -> list[dict[str, Any]]:
        payload = {
            "timeout": TELEGRAM_POLL_TIMEOUT,
            "offset": self._offset,
            "allowed_updates": ["message"],
        }
        data = await _telegram_request(client, bot_token, "getUpdates", payload)
        updates = data.get("result")
        if not isinstance(updates, list):
            return []
        return [update for update in updates if isinstance(update, dict)]

    async def _handle_update(
        self,
        *,
        client: httpx.AsyncClient,
        session: AsyncSession,
        update: dict[str, Any],
        bot_token: str,
        configured_chat_id: str,
    ) -> None:
        update_id = update.get("update_id")
        if isinstance(update_id, int) and update_id >= self._offset:
            self._offset = update_id + 1

        text = _message_text(update)
        chat_id = _message_chat_id(update)
        message_id = _message_id(update)
        if not text or not chat_id:
            return

        command, args = parse_telegram_command(text)
        if not command:
            return

        try:
            if configured_chat_id:
                if chat_id != configured_chat_id:
                    return
            elif command not in {"help", "start", "link"}:
                # No chat is bound yet. Only allow the onboarding commands.
                return

            response = await self._execute_command(session=session, chat_id=chat_id, command=command, args=args)
            if response is None:
                return

            await send_telegram_message(
                client,
                bot_token=bot_token,
                chat_id=chat_id,
                text=response,
                reply_to_message_id=message_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram command failed | command=%s chat_id=%s error=%s", command, chat_id, exc, exc_info=True)
            await send_telegram_message(
                client,
                bot_token=bot_token,
                chat_id=chat_id,
                text="\n".join(
                    [
                        _title("LLMBridge command failed"),
                        _format_kv_block(
                            [
                                ("Command", command),
                                ("Status", "failed"),
                            ]
                        ),
                    ]
                ),
                reply_to_message_id=message_id,
            )

    async def _execute_command(
        self,
        *,
        session: AsyncSession,
        chat_id: str,
        command: str,
        args: list[str],
    ) -> str | None:
        runtime = read_runtime_config()

        if command in {"start", "help"}:
            return build_help_message()

        if command == "status":
            return build_status_message(runtime_base_url=runtime.api_base_url)

        if command == "runtime":
            return build_runtime_message(host=runtime.host, port=runtime.port, restart_required=runtime.restart_required)

        if command == "apps":
            return await _build_apps_list_message(session)

        if command == "app":
            if not args:
                return "Usage: /app <id|name>"
            return await _build_app_overview_message(session, args[0])

        if command == "providers":
            return await _build_providers_list_message(session)

        if command == "provider":
            if not args:
                return "Usage: /provider <name>"
            return await _build_provider_overview_message(session, args[0].lower())

        if command == "queues":
            return await _build_queues_list_message(session)

        if command == "queue":
            if not args:
                return "Usage: /queue <name>"
            return await _build_queue_overview_message(session, args[0])

        if command == "alerts":
            if not args:
                alert_settings = await get_alert_settings(session)
                return build_alerts_message(alert_settings)
            if args[0].lower() == "on":
                alert_settings = await update_alert_settings(session, telegram_enabled=True, telegram_chat_id=chat_id)
                return build_alerts_message(alert_settings)
            if args[0].lower() == "off":
                alert_settings = await update_alert_settings(session, telegram_enabled=False)
                return build_alerts_message(alert_settings)
            if len(args) >= 2:
                target = args[0].lower()
                value = args[1].lower() in {"on", "true", "1", "yes", "enable", "enabled"}
                updates: dict[str, bool] = {}
                if target in {"proxy", "failure", "failures"}:
                    updates["alert_proxy_failures"] = value
                elif target in {"queue", "queues"}:
                    updates["alert_queue_exhausted"] = value
                elif target in {"provider", "pool"}:
                    updates["alert_provider_pool_exhausted"] = value
                elif target in {"key", "keys"}:
                    updates["alert_provider_key_status_changes"] = value
                else:
                    return "Unknown alerts switch."
                alert_settings = await update_alert_settings(session, **updates)
                return build_alerts_message(alert_settings)
            return "Usage: /alerts [on|off|proxy on|queue on|provider on|key on]"

        if command == "link":
            alert_settings = await update_alert_settings(
                session,
                telegram_enabled=True,
                telegram_chat_id=chat_id,
            )
            return "\n".join(
                [
                    _title("LLMBridge chat linked"),
                    _format_kv_block(
                        [
                            ("Chat ID", chat_id),
                            ("Telegram", _toggle_label(alert_settings.telegram_enabled)),
                        ]
                    ),
                ]
            )

        return None


def create_telegram_bot_worker(sessionmaker: async_sessionmaker[AsyncSession]) -> TelegramBotWorker:
    return TelegramBotWorker(sessionmaker)
