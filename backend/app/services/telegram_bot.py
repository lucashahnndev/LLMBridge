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


def _bold(text: str) -> str:
    return f"*{_escape_markdown_v2(text)}*"


def _italic(text: str) -> str:
    return f"_{_escape_markdown_v2(text)}_"


def _code(text: str) -> str:
    return f"`{_escape_code_block(text)}`"


def _truncate(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]
    return text[: max_length - 3] + "..."


def build_help_message() -> str:
    lines = [
        _bold("🤖 LLMBridge Telegram Control Panel"),
        "",
        "Use the following commands to monitor and manage your instances:",
        "",
        f"• {_code('/status')} \\- {_italic('Show overall service status')}",
        f"• {_code('/runtime')} \\- {_italic('Show runtime host, port, and API URLs')}",
        f"• {_code('/apps')} \\- {_italic('List all app tokens and their metrics')}",
        f"• {_code('/app <id|name>')} \\- {_italic('Show detailed metrics for a specific app token')}",
        f"• {_code('/providers')} \\- {_italic('List all configured providers and key counts')}",
        f"• {_code('/provider <name>')} \\- {_italic('Show detailed metrics for a specific provider')}",
        f"• {_code('/queues')} \\- {_italic('List all model routing queues and their requests')}",
        f"• {_code('/queue <name>')} \\- {_italic('Show details and model breakdown of a queue')}",
        "",
        _bold("🔔 Alert Management"),
        f"• {_code('/alerts')} \\- {_italic('Show current alert configuration')}",
        f"• {_code('/alerts on|off')} \\- {_italic('Enable or disable Telegram alerts globally')}",
        f"• {_code('/alerts proxy on|off')} \\- {_italic('Toggle proxy error alerts')}",
        f"• {_code('/alerts queue on|off')} \\- {_italic('Toggle queue exhaustion alerts')}",
        f"• {_code('/alerts provider on|off')} \\- {_italic('Toggle provider pool empty alerts')}",
        f"• {_code('/alerts key on|off')} \\- {_italic('Toggle provider API key status change alerts')}",
        "",
        _bold("🔗 Connection"),
        f"• {_code('/link')} \\- {_italic('Bind this Telegram chat to receive alerts and commands')}",
    ]
    return "\n".join(lines)


def build_status_message(*, runtime_base_url: str) -> str:
    return "\n".join(
        [
            _bold("📊 LLMBridge Status Overview"),
            "",
            f"• {_bold('Service:')} {_escape_markdown_v2(get_settings().app_name)}",
            f"• {_bold('Version:')} {_code(APP_VERSION)}",
            f"• {_bold('Schema:')} {_code(str(SCHEMA_VERSION))}",
            f"• {_bold('Runtime URL:')} {_code(runtime_base_url)}",
            f"• {_bold('Checked At:')} {_code(_utc_now())}",
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
        return "\n".join([_bold("📱 LLMBridge App Tokens"), "", _escape_markdown_v2("No app tokens found.")])
    lines = [
        _bold("📱 LLMBridge App Tokens"),
        _italic("Showing the latest active tokens:"),
        ""
    ]
    for row in rows[:8]:
        status_icon = "🟢" if row.is_active else "🔴"
        lines.append(
            f"{status_icon} {_bold(row.name)} \\({_code(row.environment.value)}\\)\n"
            f"  • Status: {_italic('Active' if row.is_active else 'Inactive')}\n"
            f"  • Requests: {_code(str(int(row.requests_count or 0)))}\n"
            f"  • Tokens Consumed: {_code(str(int(row.total_tokens_consumed or 0)))}"
        )
        lines.append("")
    return "\n".join(lines)


async def _build_providers_list_message(session: AsyncSession) -> str:
    result = await session.execute(
        select(ProviderKey.provider, func.count(ProviderKey.id).label("key_count")).group_by(ProviderKey.provider)
    )
    rows = result.all()
    if not rows:
        return "\n".join([_bold("🔌 LLMBridge Providers"), "", _escape_markdown_v2("No provider activity yet.")])
    provider_counts = await _provider_request_counts(session)
    lines = [
        _bold("🔌 LLMBridge Providers"),
        _italic("Summary of active providers:"),
        ""
    ]
    for provider, key_count in rows[:8]:
        req_count = provider_counts.get(provider, 0)
        lines.append(
            f"• {_bold(provider.upper())}\n"
            f"  • Requests: {_code(str(req_count))}\n"
            f"  • Keys Configured: {_code(str(int(key_count or 0)))}"
        )
        lines.append("")
    return "\n".join(lines)


async def _build_queues_list_message(session: AsyncSession) -> str:
    result = await session.execute(select(ModelQueue.name, ModelQueue.strategy, ModelQueue.is_active).order_by(ModelQueue.id.desc()))
    queues = result.all()
    if not queues:
        return "\n".join([_bold("⛓️ LLMBridge Queues"), "", _escape_markdown_v2("No queues found.")])
    queue_counts = await _queue_request_counts(session)
    lines = [
        _bold("⛓️ LLMBridge Routing Queues"),
        _italic("Configured queues:"),
        ""
    ]
    for name, strategy, is_active in queues[:8]:
        status_icon = "🟢" if is_active else "🔴"
        req_count = queue_counts.get(name, 0)
        lines.append(
            f"{status_icon} {_bold(name)}\n"
            f"  • Strategy: {_code(strategy.value)}\n"
            f"  • Status: {_italic('Active' if is_active else 'Inactive')}\n"
            f"  • Total Requests: {_code(str(req_count))}"
        )
        lines.append("")
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
        return "\n".join([_bold("📱 LLMBridge App Token Overview"), "", _escape_markdown_v2(f"App token '{identifier}' not found.")])
    overview = await build_app_token_overview(session, app_token.id, "24h")
    summary = overview.summary
    lines = [
        f"📱 {_bold('LLMBridge App Token Overview')}",
        "",
        f"• {_bold('App Name:')} {overview.context_label}",
        f"• {_bold('Environment:')} {_code(app_token.environment.value)}",
        f"• {_bold('Masked Token:')} {_code(app_token.masked_token)}",
        "",
        _bold("📊 Performance (Last 24h):"),
        f"  • Total Requests: {_code(str(summary.total_requests))}",
        f"  • Success Rate: {_code(f'{summary.success_rate:.1f}%')}",
        f"  • Avg Latency: {_code(f'{summary.avg_latency_ms:.1f} ms')}",
        f"  • Tokens Consumed: {_code(str(summary.total_tokens_consumed))}",
        f"  • Key Rotations: {_code(str(summary.total_rotations_triggered))}",
    ]
    if overview.models:
        lines.extend(["", _bold("🤖 Top Models Used:")])
        for model in overview.models[:3]:
            lines.append(
                f"  • {_bold(model.model_name)}: {_code(str(model.requests_count))} reqs / {_code(str(model.total_tokens_consumed))} tokens"
            )
    return "\n".join(lines)


async def _build_provider_overview_message(session: AsyncSession, provider: str) -> str:
    overview = await build_provider_overview(session, provider, "24h")
    key_result = await session.execute(
        select(ProviderKey).where(ProviderKey.provider == provider).order_by(ProviderKey.id.desc())
    )
    keys = key_result.scalars().all()
    active_keys = [key for key in keys if key.status == KeyStatus.ACTIVE]
    lines = [
        f"🔌 {_bold('LLMBridge Provider Overview')}",
        "",
        f"• {_bold('Provider:')} {overview.context_label.upper()}",
        f"• {_bold('API Keys:')} {_code(f'{len(keys)} total / {len(active_keys)} active')}",
        "",
        _bold("📊 Performance (Last 24h):"),
        f"  • Total Requests: {_code(str(overview.summary.total_requests))}",
        f"  • Success Rate: {_code(f'{overview.summary.success_rate:.1f}%')}",
        f"  • Avg Latency: {_code(f'{overview.summary.avg_latency_ms:.1f} ms')}",
        f"  • Tokens Consumed: {_code(str(overview.summary.total_tokens_consumed))}",
        f"  • Key Rotations: {_code(str(overview.summary.total_rotations_triggered))}",
    ]
    if overview.models:
        lines.extend(["", _bold("🤖 Top Models Used:")])
        for model in overview.models[:3]:
            lines.append(
                f"  • {_bold(model.model_name)}: {_code(str(model.requests_count))} reqs / {_code(str(model.total_tokens_consumed))} tokens"
            )
    return "\n".join(lines)


async def _build_queue_overview_message(session: AsyncSession, queue_name: str) -> str:
    overview = await build_queue_overview(session, queue_name, "24h")
    lines = [
        f"⛓️ {_bold('LLMBridge Queue Overview')}",
        "",
        f"• {_bold('Queue Name:')} {overview.context_label}",
        "",
        _bold("📊 Performance (Last 24h):"),
        f"  • Total Requests: {_code(str(overview.summary.total_requests))}",
        f"  • Success Rate: {_code(f'{overview.summary.success_rate:.1f}%')}",
        f"  • Avg Latency: {_code(f'{overview.summary.avg_latency_ms:.1f} ms')}",
        f"  • Tokens Consumed: {_code(str(overview.summary.total_tokens_consumed))}",
        f"  • Key Rotations: {_code(str(overview.summary.total_rotations_triggered))}",
    ]
    if overview.models:
        lines.extend(["", _bold("🤖 Top Models Used:")])
        for model in overview.models[:5]:
            lines.append(
                f"  • {_bold(model.model_name)}: {_code(str(model.requests_count))} reqs / {_code(str(model.total_tokens_consumed))} tokens"
            )
    return "\n".join(lines)


def build_runtime_message(*, host: str, port: int, restart_required: bool) -> str:
    restart_status = "⚠️ Yes (restart required)" if restart_required else "✅ No"
    return "\n".join(
        [
            _bold("⚙️ LLMBridge Runtime Config"),
            "",
            f"• {_bold('Host:')} {_code(host)}",
            f"• {_bold('Port:')} {_code(str(port))}",
            f"• {_bold('API Base URL:')} {_code(f'http://{host}:{port}/api/v1')}",
            f"• {_bold('Restart Required:')} {restart_status}",
        ]
    )


def build_alerts_message(alert_settings: AlertSettings) -> str:
    def _status_emoji(enabled: bool) -> str:
        return "🔔 Enabled" if enabled else "🔕 Disabled"

    chat_id = alert_settings.telegram_chat_id or "not configured"
    return "\n".join(
        [
            _bold("🔔 LLMBridge Alert Settings"),
            "",
            f"• {_bold('Telegram Alerts:')} {_status_emoji(alert_settings.telegram_enabled)}",
            f"• {_bold('Active Chat ID:')} {_code(chat_id)}",
            "",
            _bold("Alert Channels:"),
            f"• {_bold('Proxy Failures:')} {_status_emoji(alert_settings.alert_proxy_failures)}",
            f"• {_bold('Queue Exhausted:')} {_status_emoji(alert_settings.alert_queue_exhausted)}",
            f"• {_bold('Provider Pool Exhausted:')} {_status_emoji(alert_settings.alert_provider_pool_exhausted)}",
            f"• {_bold('API Key Status Changes:')} {_status_emoji(alert_settings.alert_provider_key_status_changes)}",
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


TELEGRAM_BOT_COMMANDS = [
    {"command": "status", "description": "Show overall service status"},
    {"command": "runtime", "description": "Show runtime host and port config"},
    {"command": "apps", "description": "List configured app tokens"},
    {"command": "app", "description": "Show detailed metrics for an app token"},
    {"command": "providers", "description": "List configured providers and key counts"},
    {"command": "provider", "description": "Show detailed metrics for a provider"},
    {"command": "queues", "description": "List routing queues and their requests"},
    {"command": "queue", "description": "Show details and model breakdown of a queue"},
    {"command": "alerts", "description": "View or configure alert channel settings"},
    {"command": "link", "description": "Bind this chat to receive LLMBridge alerts"},
    {"command": "help", "description": "Show available commands list"},
]


class TelegramBotWorker:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._offset = 0
        self._commands_set_token: str | None = None

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

    async def _set_bot_commands(self, client: httpx.AsyncClient, bot_token: str) -> None:
        payload = {
            "commands": TELEGRAM_BOT_COMMANDS
        }
        try:
            await _telegram_request(client, bot_token, "setMyCommands", payload)
            logger.info("Successfully registered Telegram bot commands via API.")
        except Exception as exc:
            logger.warning("Failed to register Telegram bot commands: %s", exc)

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

                        if self._commands_set_token != bot_token:
                            await self._set_bot_commands(client, bot_token)
                            self._commands_set_token = bot_token

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
                        f"❌ {_bold('LLMBridge Command Failed')}",
                        "",
                        f"• {_bold('Command:')} {_code(command)}",
                        f"• {_bold('Status:')} failed",
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
                return f"⚠️ {_bold('Usage:')} {_code('/app <id|name>')}"
            return await _build_app_overview_message(session, args[0])

        if command == "providers":
            return await _build_providers_list_message(session)

        if command == "provider":
            if not args:
                return f"⚠️ {_bold('Usage:')} {_code('/provider <name>')}"
            return await _build_provider_overview_message(session, args[0].lower())

        if command == "queues":
            return await _build_queues_list_message(session)

        if command == "queue":
            if not args:
                return f"⚠️ {_bold('Usage:')} {_code('/queue <name>')}"
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
            return f"⚠️ {_bold('Usage:')} {_code('/alerts [on|off|proxy on|queue on|provider on|key on]')}"

        if command == "link":
            alert_settings = await update_alert_settings(
                session,
                telegram_enabled=True,
                telegram_chat_id=chat_id,
            )
            return "\n".join(
                [
                    f"🔗 {_bold('LLMBridge Chat Linked')}",
                    "",
                    f"• {_bold('Chat ID:')} {_code(chat_id)}",
                    f"• {_bold('Telegram Alerts:')} 🔔 Enabled",
                ]
            )

        return None


def create_telegram_bot_worker(sessionmaker: async_sessionmaker[AsyncSession]) -> TelegramBotWorker:
    return TelegramBotWorker(sessionmaker)
