from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from backend.app.schemas.common import ORMModel, QueueStrategySchema


class ModelQueueCandidateBase(BaseModel):
    provider: str = Field(..., examples=["github", "google", "openai", "openrouter"])
    model_name: str = Field(..., examples=["gemini-3-flash-preview", "gpt-4o-mini"])
    position: int = Field(default=0, ge=0)
    is_active: bool = True
    base_degradation: float = Field(default=0.0, ge=0.0)


class ModelQueueCandidateCreate(ModelQueueCandidateBase):
    pass


class ModelQueueCandidateUpdate(BaseModel):
    provider: Optional[str] = None
    model_name: Optional[str] = None
    position: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None
    base_degradation: Optional[float] = Field(default=None, ge=0.0)


class ModelQueueCandidateResponse(ORMModel, ModelQueueCandidateBase):
    id: int
    queue_id: int
    base_degradation: float = Field(default=0.0)
    latency_score: float = Field(default=0.0)
    error_score: float = Field(default=0.0)
    final_rank: float = Field(default=0.0)
    score: float = Field(default=0.0)
    failure_count: int = Field(default=0, ge=0)
    success_count: int = Field(default=0, ge=0)
    avg_latency_ms: float = Field(default=0.0, ge=0)
    last_used_at: Optional[datetime] = None
    last_error_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ModelQueueBase(BaseModel):
    name: str = Field(..., max_length=100, examples=["production", "fallback"])
    description: Optional[str] = None
    strategy: QueueStrategySchema = QueueStrategySchema.ORDERED


class ModelQueueCreate(ModelQueueBase):
    pass


class ModelQueueUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    strategy: Optional[QueueStrategySchema] = None
    is_active: Optional[bool] = None


class ModelQueueResponse(ORMModel, ModelQueueBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    candidates: list[ModelQueueCandidateResponse] = Field(default_factory=list)
