from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = ROOT_DIR / "backend" / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "LLMBridge"
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000)
    frontend_host: str = Field(default="127.0.0.1")
    frontend_port: int = Field(default=4173)
    secret_key: str = Field(default="")
    admin_password: str = Field(default="")
    admin_token_ttl_minutes: int = Field(default=720)
    jwt_algorithm: str = Field(default="HS256")
    database_url: str = Field(default="sqlite+aiosqlite:///./backend/data/database.db")
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")
    proxy_max_attempts: int = Field(default=3)
    proxy_timeout_seconds: int = Field(default=90)
    key_soft_reservation_ms: int = Field(default=250)
    key_next_available_delay_ms: int = Field(default=150)
    key_cooldown_seconds: int = Field(default=300)
    provider_model_not_found_cooldown_seconds: int = Field(default=3600)
    provider_transient_failure_cooldown_seconds: int = Field(default=30)
    smart_queue_latency_weight: float = Field(default=0.55)
    smart_queue_error_weight: float = Field(default=0.30)
    smart_queue_base_weight: float = Field(default=0.15)
    legacy_cooldown_mirror_enabled: bool = Field(default=True)
    log_file_enabled: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    log_file_path: str = Field(default="logs/backend.log")
    logging_control_key: str = Field(default="")
    trace_proxy_enabled: bool = Field(default=False)
    trace_proxy_dir: str = Field(default="traces")
    trace_proxy_redact: bool = Field(default=True)
    openai_api_base: str = Field(default="https://api.openai.com/v1")
    openrouter_api_base: str = Field(default="https://openrouter.ai/api/v1")
    google_api_base: str = Field(default="https://generativelanguage.googleapis.com/v1beta/openai")
    github_models_api_base: str = Field(default="https://models.github.ai/inference")
    github_models_api_version: str = Field(default="2022-11-28")


@lru_cache
def get_settings() -> Settings:
    return Settings()
