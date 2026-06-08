from pydantic import BaseModel, Field


class RuntimeConfigResponse(BaseModel):
    host: str = Field(..., examples=["127.0.0.1"])
    port: int = Field(..., examples=[8000])
    api_base_url: str = Field(..., examples=["http://127.0.0.1:8000/api/v1"])
    restart_required: bool = True


class RuntimeConfigUpdate(BaseModel):
    host: str | None = Field(default=None, examples=["127.0.0.1"])
    port: int | None = Field(default=None, ge=1, le=65535, examples=[8080])
