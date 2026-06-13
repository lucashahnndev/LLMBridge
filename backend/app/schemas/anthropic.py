from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AnthropicMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: Any = Field(default=None)


class AnthropicMessagesRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = Field(..., examples=["queue/github", "queue/google"])
    max_tokens: int = Field(..., ge=1)
    messages: list[AnthropicMessage]
    system: Any | None = None
    stream: bool = False
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    stop_sequences: list[str] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any | None = None
    metadata: dict[str, Any] | None = None
