from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from backend.app.schemas.common import ORMModel, KeyStatusSchema


class ProviderKeyBase(BaseModel):
    name: str = Field(..., max_length=100, examples=["Chave Gemini Reserva"])
    description: Optional[str] = None
    provider: str = Field(..., examples=["github", "google", "openai", "openrouter"])


class ProviderKeyCreate(ProviderKeyBase):
    token: str = Field(..., description="Token em texto claro para ser criptografado antes de salvar.")


class ProviderKeyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    provider: Optional[str] = None
    status: Optional[KeyStatusSchema] = None
    blocked_until: Optional[datetime] = None
    failure_count: Optional[int] = None


class ProviderKeyResponse(ORMModel, ProviderKeyBase):
    id: int
    status: KeyStatusSchema
    blocked_until: Optional[datetime] = None
    failure_count: int
    created_at: datetime
    updated_at: datetime
    masked_token: str = Field(..., examples=["AIzaSy...x9W2"])


class ProviderKeyPeekRequest(BaseModel):
    admin_password: str = Field(..., description="Senha do admin para reautenticacao/consentimento.")


class ProviderKeyPeekResponse(BaseModel):
    token: str
