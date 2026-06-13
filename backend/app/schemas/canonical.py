from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CanonicalCleanupPolicy(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    mode: Literal["off", "conservative", "aggressive"] = "off"
    compress_metadata: bool = True
    drop_transport_noise: bool = True
    preserve_tool_semantics: bool = True


class CanonicalRoute(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: Literal["provider", "queue"] = "provider"
    requested_model: str
    provider: str | None = None
    model_name: str | None = None
    queue_name: str | None = None
    queue_id: int | None = None
    candidate_id: int | None = None
    resolved_route: str | None = None


class CanonicalToolFunction(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    arguments: Any = None
    raw_arguments_text: str | None = None


class CanonicalToolCall(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: Literal["function"] = "function"
    function: CanonicalToolFunction


class CanonicalContentBlock(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    text: str | None = None
    tool_call: CanonicalToolCall | None = None
    tool_use_id: str | None = None
    tool_result: Any = None
    name: str | None = None
    input: Any = None
    raw: dict[str, Any] | None = None


class CanonicalMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: Any = None
    blocks: list[CanonicalContentBlock] = Field(default_factory=list)
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[CanonicalToolCall] = Field(default_factory=list)
    raw: dict[str, Any] | None = None


class CanonicalToolDefinition(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] | None = None


class CanonicalGeneration(BaseModel):
    model_config = ConfigDict(extra="allow")

    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    top_k: int | None = None
    stop_sequences: list[str] = Field(default_factory=list)
    tool_choice: Any = None
    response_format: dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None


class CanonicalTelemetry(BaseModel):
    model_config = ConfigDict(extra="allow")

    protocol_in: str
    protocol_out: str | None = None
    upstream_protocol: str | None = None
    app_token_id: int | None = None
    provider_key_id: int | None = None
    route_kind: str | None = None
    queue_name: str | None = None


class CanonicalRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    request_id: str | None = None
    protocol_in: str
    route: CanonicalRoute
    messages: list[CanonicalMessage] = Field(default_factory=list)
    system: Any = None
    tools: list[CanonicalToolDefinition] = Field(default_factory=list)
    generation: CanonicalGeneration = Field(default_factory=CanonicalGeneration)
    optimization: CanonicalCleanupPolicy = Field(default_factory=CanonicalCleanupPolicy)
    metadata: dict[str, Any] = Field(default_factory=dict)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    telemetry: CanonicalTelemetry | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class CanonicalUsage(BaseModel):
    model_config = ConfigDict(extra="allow")

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class CanonicalResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    request_id: str | None = None
    protocol_out: str
    upstream_protocol: str | None = None
    route: CanonicalRoute
    model: str
    role: str = "assistant"
    content: Any = None
    blocks: list[CanonicalContentBlock] = Field(default_factory=list)
    tool_calls: list[CanonicalToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: CanonicalUsage = Field(default_factory=CanonicalUsage)
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)
