from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from backend.app.schemas.common import ORMModel


class UsageLogBase(BaseModel):
    app_token_id: int
    provider_key_id: Optional[int] = None
    protocol_in: str = Field(default="openai", max_length=20)
    protocol_out: str = Field(default="openai", max_length=20)
    upstream_protocol: str = Field(default="openai", max_length=20)
    route_kind: str = Field(default="provider", max_length=20)
    queue_name: Optional[str] = None
    model_requested: str = Field(..., max_length=100)
    provider_used: str = Field(..., max_length=50)
    resolved_model: str | None = Field(default=None, max_length=120)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    latency_ms: float = Field(..., ge=0)
    status_code: int
    was_rotated: bool = False
    tool_calling: bool = False
    error_message: Optional[str] = None


class UsageLogCreate(UsageLogBase):
    pass


class UsageLogResponse(ORMModel, UsageLogBase):
    id: int
    app_token_name: str | None = None
    provider_key_name: str | None = None
    gateway_provider: str | None = None
    downstream_provider: str | None = None
    downstream_model_name: str | None = None
    operational_route: str | None = None
    queue_name: str | None = None
    created_at: datetime


class UsageLogPageResponse(ORMModel):
    items: list[UsageLogResponse] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1)
    offset: int = Field(default=0, ge=0)
