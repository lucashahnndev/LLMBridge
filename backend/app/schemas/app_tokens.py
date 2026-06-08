from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from backend.app.schemas.common import ORMModel, EnvironmentTypeSchema


class AppTokenBase(BaseModel):
    name: str = Field(..., max_length=100, examples=["Chatbot Suporte"])
    environment: EnvironmentTypeSchema = EnvironmentTypeSchema.DEVELOPMENT
    rpm_limit: Optional[int] = Field(default=None, ge=1)


class AppTokenCreate(AppTokenBase):
    pass


class AppTokenResponse(ORMModel, AppTokenBase):
    id: int
    is_active: bool
    created_at: datetime
    masked_token: str = Field(..., examples=["lk-key...abcd"])


class AppTokenCreateResponse(AppTokenResponse):
    token: str


class AppTokenUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    environment: Optional[EnvironmentTypeSchema] = None
    rpm_limit: Optional[int] = Field(default=None, ge=1)
    is_active: Optional[bool] = None
