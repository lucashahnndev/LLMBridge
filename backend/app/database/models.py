import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database.base import Base


class KeyStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    COOLDOWN = "COOLDOWN"
    INVALID = "INVALID"
    SUSPENDED_BILLING = "SUSPENDED_BILLING"


class EnvironmentType(str, enum.Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class QueueStrategy(str, enum.Enum):
    ORDERED = "ordered"
    SMART = "smart"
    LATENCY = "latency"


class ProviderKey(Base):
    __tablename__ = "provider_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[KeyStatus] = mapped_column(
        Enum(KeyStatus, name="key_status"),
        default=KeyStatus.ACTIVE,
        nullable=False,
    )
    blocked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )

    logs: Mapped[List["UsageLog"]] = relationship(back_populates="provider_key")


class ModelQueue(Base):
    __tablename__ = "model_queues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    strategy: Mapped[QueueStrategy] = mapped_column(
        Enum(QueueStrategy, name="queue_strategy"),
        default=QueueStrategy.ORDERED,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )

    candidates: Mapped[List["ModelQueueCandidate"]] = relationship(
        back_populates="queue",
        cascade="all, delete-orphan",
    )


class AppToken(Base):
    __tablename__ = "app_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    environment: Mapped[EnvironmentType] = mapped_column(
        Enum(EnvironmentType, name="environment_type"),
        default=EnvironmentType.DEVELOPMENT,
        nullable=False,
    )
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rpm_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )

    logs: Mapped[List["UsageLog"]] = relationship(back_populates="app_token")


class UsageLog(Base):
    __tablename__ = "usage_logs"
    __table_args__ = (
        Index("ix_usage_logs_app_token_created_at", "app_token_id", "created_at"),
        Index("ix_usage_logs_provider_key_created_at", "provider_key_id", "created_at"),
        Index("ix_usage_logs_queue_name_created_at", "queue_name", "created_at"),
        Index("ix_usage_logs_resolved_model_created_at", "resolved_model", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_token_id: Mapped[int] = mapped_column(ForeignKey("app_tokens.id", ondelete="CASCADE"), nullable=False)
    provider_key_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("provider_keys.id", ondelete="SET NULL"),
        nullable=True,
    )
    protocol_in: Mapped[str] = mapped_column(String(20), default="openai", nullable=False)
    protocol_out: Mapped[str] = mapped_column(String(20), default="openai", nullable=False)
    route_kind: Mapped[str] = mapped_column(String(20), default="provider", nullable=False)
    queue_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model_requested: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_used: Mapped[str] = mapped_column(String(50), nullable=False)
    resolved_model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    was_rotated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tool_calling: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )

    app_token: Mapped["AppToken"] = relationship(back_populates="logs")
    provider_key: Mapped[Optional["ProviderKey"]] = relationship(back_populates="logs")


class SchemaVersion(Base):
    __tablename__ = "schema_versions"

    key: Mapped[str] = mapped_column(String(32), primary_key=True, default="schema")
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )


class AlertSettings(Base):
    __tablename__ = "alert_settings"

    key: Mapped[str] = mapped_column(String(32), primary_key=True, default="global")
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    telegram_bot_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    alert_proxy_failures: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    alert_queue_exhausted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    alert_provider_pool_exhausted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    alert_provider_key_status_changes: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )

    @property
    def telegram_bot_token_configured(self) -> bool:
        return bool(self.telegram_bot_token_encrypted)


class ProviderKeyModelCooldown(Base):
    __tablename__ = "provider_key_model_cooldowns"
    __table_args__ = (
        Index(
            "ix_provider_key_model_cooldowns_provider_key_model_name",
            "provider_key_id",
            "model_name",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_key_id: Mapped[int] = mapped_column(
        ForeignKey("provider_keys.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    blocked_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )


class ModelQueueCandidate(Base):
    __tablename__ = "model_queue_candidates"
    __table_args__ = (
        Index(
            "ix_model_queue_candidates_queue_position",
            "queue_id",
            "position",
        ),
        Index(
            "ix_model_queue_candidates_queue_route",
            "queue_id",
            "provider",
            "model_name",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("model_queues.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )

    queue: Mapped["ModelQueue"] = relationship(back_populates="candidates")


class AdminTokenRevocation(Base):
    __tablename__ = "admin_token_revocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        nullable=False,
    )
