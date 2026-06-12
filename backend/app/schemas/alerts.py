from datetime import datetime

from pydantic import BaseModel, Field

from backend.app.schemas.common import ORMModel


class AlertSettingsResponse(ORMModel):
    key: str
    telegram_enabled: bool = Field(default=False)
    telegram_bot_token_configured: bool = Field(default=False)
    telegram_chat_id: str | None = None
    alert_proxy_failures: bool = Field(default=True)
    alert_queue_exhausted: bool = Field(default=True)
    alert_provider_pool_exhausted: bool = Field(default=True)
    alert_provider_key_status_changes: bool = Field(default=True)
    created_at: datetime
    updated_at: datetime


class AlertSettingsUpdate(BaseModel):
    telegram_enabled: bool | None = None
    telegram_bot_token: str | None = Field(default=None, description="Telegram bot token in plain text.")
    telegram_chat_id: str | None = None
    alert_proxy_failures: bool | None = None
    alert_queue_exhausted: bool | None = None
    alert_provider_pool_exhausted: bool | None = None
    alert_provider_key_status_changes: bool | None = None


class AlertTelegramTestRequest(BaseModel):
    telegram_bot_token: str | None = Field(default=None, description="Optional Telegram bot token override in plain text.")
    telegram_chat_id: str | None = Field(default=None, description="Optional Telegram chat ID override.")


class AlertTelegramTestResponse(BaseModel):
    sent: bool = True
    detail: str
