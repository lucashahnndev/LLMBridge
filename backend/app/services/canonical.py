from __future__ import annotations

import json
from typing import Any

from backend.app.schemas.anthropic import AnthropicMessage, AnthropicMessagesRequest
from backend.app.schemas.canonical import (
    CanonicalCleanupPolicy,
    CanonicalContentBlock,
    CanonicalGeneration,
    CanonicalMessage,
    CanonicalRequest,
    CanonicalResponse,
    CanonicalRoute,
    CanonicalTelemetry,
    CanonicalToolCall,
    CanonicalToolDefinition,
    CanonicalToolFunction,
    CanonicalUsage,
)
from backend.app.schemas.proxy import ChatCompletionRequest, ChatMessage


def _json_or_raw(value: Any) -> Any:
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    return str(value)


def _parse_json_arguments(arguments: Any) -> tuple[Any, str | None]:
    if isinstance(arguments, (dict, list)):
        return arguments, json.dumps(arguments, ensure_ascii=False)
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {"raw": arguments}, arguments
        return parsed, arguments
    return {}, None


def _content_to_blocks(content: Any) -> list[CanonicalContentBlock]:
    if content is None:
        return []
    if isinstance(content, str):
        return [CanonicalContentBlock(type="text", text=content, raw={"content": content})]
    if not isinstance(content, list):
        return [CanonicalContentBlock(type="text", text=str(content), raw={"content": str(content)})]

    blocks: list[CanonicalContentBlock] = []
    for block in content:
        if not isinstance(block, dict):
            blocks.append(CanonicalContentBlock(type="unknown", raw={"value": _json_or_raw(block)}))
            continue
        block_type = str(block.get("type") or "unknown")
        if block_type == "text":
            text = block.get("text")
            blocks.append(
                CanonicalContentBlock(
                    type="text",
                    text=text if isinstance(text, str) else None,
                    raw=block,
                )
            )
            continue
        if block_type == "tool_use":
            tool_name = block.get("name")
            tool_input = block.get("input")
            normalized_input, raw_arguments_text = _parse_json_arguments(tool_input)
            tool_call = CanonicalToolCall(
                id=str(block.get("id") or ""),
                function=CanonicalToolFunction(
                    name=str(tool_name or ""),
                    arguments=normalized_input,
                    raw_arguments_text=raw_arguments_text,
                ),
            )
            blocks.append(
                CanonicalContentBlock(
                    type="tool_use",
                    tool_call=tool_call,
                    tool_use_id=str(block.get("id")) if block.get("id") is not None else None,
                    name=str(tool_name) if isinstance(tool_name, str) else None,
                    input=normalized_input,
                    raw=block,
                )
            )
            continue
        if block_type == "tool_result":
            blocks.append(
                CanonicalContentBlock(
                    type="tool_result",
                    tool_use_id=str(block.get("tool_use_id")) if block.get("tool_use_id") is not None else None,
                    name=str(block.get("name")) if isinstance(block.get("name"), str) else None,
                    tool_result=block.get("content"),
                    raw=block,
                )
            )
            continue
        blocks.append(CanonicalContentBlock(type=block_type, raw=block))
    return blocks


def _tool_calls_to_blocks(tool_calls: list[dict[str, Any]] | None) -> list[CanonicalToolCall]:
    normalized_tool_calls: list[CanonicalToolCall] = []
    if not isinstance(tool_calls, list):
        return normalized_tool_calls
    for index, tool_call in enumerate(tool_calls):
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function")
        if isinstance(function, dict):
            function_name = function.get("name")
            arguments = function.get("arguments")
        else:
            function_name = tool_call.get("name")
            arguments = tool_call.get("arguments")
        if not isinstance(function_name, str) or not function_name.strip():
            continue
        parsed_arguments, raw_arguments_text = _parse_json_arguments(arguments)
        normalized_tool_calls.append(
            CanonicalToolCall(
                id=str(tool_call.get("id") or f"tool_{index}"),
                function=CanonicalToolFunction(
                    name=function_name.strip(),
                    arguments=parsed_arguments,
                    raw_arguments_text=raw_arguments_text,
                ),
            )
        )
    return normalized_tool_calls


def _tool_calls_to_openai(tool_calls: list[CanonicalToolCall]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        serialized.append(
            {
                "id": tool_call.id,
                "type": tool_call.type,
                "function": {
                    "name": tool_call.function.name,
                    "arguments": (
                        tool_call.function.raw_arguments_text
                        if tool_call.function.raw_arguments_text is not None
                        else json.dumps(tool_call.function.arguments, ensure_ascii=False)
                        if isinstance(tool_call.function.arguments, (dict, list))
                        else tool_call.function.arguments
                        if isinstance(tool_call.function.arguments, str)
                        else json.dumps({}, ensure_ascii=False)
                    ),
                },
            }
        )
    return serialized


def _blocks_to_openai_content(blocks: list[CanonicalContentBlock]) -> Any:
    if not blocks:
        return None
    text_parts: list[str] = []
    for block in blocks:
        if block.type == "text" and isinstance(block.text, str):
            text_parts.append(block.text)
    if text_parts:
        return "\n".join(text_parts)
    return None


def _block_to_anthropic_block(block: CanonicalContentBlock) -> dict[str, Any]:
    if block.type == "text":
        return {"type": "text", "text": block.text or ""}
    if block.type == "tool_use":
        return {
            "type": "tool_use",
            "id": block.tool_use_id or (block.tool_call.id if block.tool_call else None),
            "name": block.name or (block.tool_call.function.name if block.tool_call else ""),
            "input": (
                block.input
                if block.input is not None
                else block.tool_call.function.arguments
                if block.tool_call is not None
                else {}
            ),
        }
    if block.type == "tool_result":
        content = block.tool_result
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False)
        elif content is None:
            content = ""
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "name": block.name,
            "content": content,
        }
    if isinstance(block.raw, dict):
        raw_type = block.raw.get("type")
        if raw_type == "text" and isinstance(block.raw.get("text"), str):
            return {"type": "text", "text": block.raw["text"]}
        if raw_type == "tool_use":
            tool_input = block.raw.get("input")
            if isinstance(tool_input, (dict, list)):
                return {
                    "type": "tool_use",
                    "id": str(block.raw.get("id") or ""),
                    "name": str(block.raw.get("name") or ""),
                    "input": tool_input,
                }
        if raw_type == "tool_result":
            result_content = block.raw.get("content")
            if isinstance(result_content, (dict, list)):
                result_content = json.dumps(result_content, ensure_ascii=False)
            elif result_content is None:
                result_content = ""
            return {
                "type": "tool_result",
                "tool_use_id": block.raw.get("tool_use_id"),
                "name": block.raw.get("name"),
                "content": result_content,
            }
    return {"type": block.type}


def anthropic_message_to_canonical(message: AnthropicMessage) -> CanonicalMessage:
    blocks = _content_to_blocks(message.content)
    tool_calls = [block.tool_call for block in blocks if block.type == "tool_use" and block.tool_call is not None]
    return CanonicalMessage(
        role=message.role,
        content=message.content,
        blocks=blocks,
        tool_calls=[tool_call for tool_call in tool_calls if tool_call is not None],
        raw={"content": message.content},
    )


def anthropic_request_to_canonical(payload: AnthropicMessagesRequest) -> CanonicalRequest:
    system_blocks = _content_to_blocks(payload.system)
    messages = [anthropic_message_to_canonical(message) for message in payload.messages]
    tools = [
        CanonicalToolDefinition(
            name=str(tool.get("name") or ""),
            description=tool.get("description") if isinstance(tool.get("description"), str) else None,
            parameters=tool.get("input_schema") or tool.get("parameters") or {},
            raw=tool,
        )
        for tool in (payload.tools or [])
        if isinstance(tool, dict) and isinstance(tool.get("name"), str) and tool.get("name")
    ]
    metadata = dict(payload.metadata or {})
    route = CanonicalRoute(kind="provider", requested_model=payload.model)
    generation = CanonicalGeneration(
        stream=payload.stream,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        top_p=payload.top_p,
        top_k=payload.top_k,
        stop_sequences=list(payload.stop_sequences or []),
        tool_choice=payload.tool_choice,
    )
    return CanonicalRequest(
        protocol_in="anthropic",
        route=route,
        messages=messages,
        system=system_blocks,
        tools=tools,
        generation=generation,
        metadata=metadata,
        raw=payload.model_dump(exclude_none=False),
    )


def openai_request_to_canonical(
    payload: ChatCompletionRequest,
    *,
    protocol_in: str = "openai",
    route_kind: str = "provider",
    queue_name: str | None = None,
    queue_id: int | None = None,
    candidate_id: int | None = None,
    provider: str | None = None,
    model_name: str | None = None,
    requested_model: str | None = None,
) -> CanonicalRequest:
    messages: list[CanonicalMessage] = []
    for message in payload.messages:
        blocks = _content_to_blocks(message.content)
        tool_calls = _tool_calls_to_blocks(message.tool_calls)
        messages.append(
            CanonicalMessage(
                role=message.role,
                content=message.content,
                blocks=blocks,
                name=message.name,
                tool_call_id=message.tool_call_id,
                tool_calls=tool_calls,
                raw=message.model_dump(exclude_none=False),
            )
        )

    tools_raw = payload.model_extra.get("tools") if payload.model_extra else None
    tools: list[CanonicalToolDefinition] = []
    legacy_functions = payload.model_extra.get("functions") if payload.model_extra else None
    candidate_tools: list[dict[str, Any]] = []
    if isinstance(tools_raw, list):
        candidate_tools.extend([tool for tool in tools_raw if isinstance(tool, dict)])
    if isinstance(legacy_functions, list):
        candidate_tools.extend(
            [
                {"type": "function", "function": function_spec}
                for function_spec in legacy_functions
                if isinstance(function_spec, dict)
            ]
        )
    for tool in candidate_tools:
        function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        name = function.get("name") if isinstance(function, dict) else None
        if not isinstance(name, str) or not name.strip():
            continue
        parameters = function.get("parameters") if isinstance(function, dict) else None
        tools.append(
            CanonicalToolDefinition(
                name=name.strip(),
                description=function.get("description") if isinstance(function, dict) else None,
                parameters=parameters if isinstance(parameters, dict) else {},
                raw=tool,
            )
        )

    tool_choice_value = payload.model_extra.get("tool_choice") if payload.model_extra else None
    if tool_choice_value is None and payload.model_extra and payload.model_extra.get("function_call") is not None:
        function_call = payload.model_extra.get("function_call")
        if isinstance(function_call, str):
            if function_call in {"auto", "none"}:
                tool_choice_value = function_call
            elif function_call == "required":
                tool_choice_value = "auto"
        elif isinstance(function_call, dict):
            function_name = function_call.get("name")
            if isinstance(function_name, str) and function_name.strip():
                tool_choice_value = {
                    "type": "function",
                    "function": {
                        "name": function_name.strip(),
                    },
                }

    stop_sequences_value: list[str] = []
    if payload.model_extra:
        stop_value = payload.model_extra.get("stop")
        if isinstance(stop_value, list):
            stop_sequences_value = [str(item) for item in stop_value if isinstance(item, (str, int, float))]
        elif isinstance(stop_value, str) and stop_value:
            stop_sequences_value = [stop_value]
        elif stop_value is not None:
            stop_sequences_value = [str(stop_value)]

    generation = CanonicalGeneration(
        stream=payload.stream,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        top_p=payload.top_p,
        stop_sequences=stop_sequences_value,
        tool_choice=tool_choice_value,
        response_format=payload.model_extra.get("response_format") if payload.model_extra else None,
        parallel_tool_calls=payload.model_extra.get("parallel_tool_calls") if payload.model_extra else None,
    )
    route = CanonicalRoute(
        kind=route_kind,
        requested_model=requested_model or payload.model,
        provider=provider,
        model_name=model_name,
        queue_name=queue_name,
        queue_id=queue_id,
        candidate_id=candidate_id,
        resolved_route=f"{provider}/{model_name}" if provider and model_name else None,
    )
    return CanonicalRequest(
        protocol_in=protocol_in,
        route=route,
        messages=messages,
        tools=tools,
        generation=generation,
        metadata=dict(payload.model_extra.get("metadata") or {}) if payload.model_extra else {},
        raw=payload.model_dump(exclude_none=False),
    )


def canonical_request_to_chat_completion(canonical: CanonicalRequest, *, model_override: str | None = None) -> ChatCompletionRequest:
    messages: list[ChatMessage] = []
    if canonical.system:
        system_content = canonical.system
        system_text = system_content
        if isinstance(system_content, list):
            system_text = _blocks_to_openai_content([
                block if isinstance(block, CanonicalContentBlock) else CanonicalContentBlock.model_validate(block)
                for block in system_content
            ])
        messages.append(ChatMessage(role="system", content=system_text or ""))

    for message in canonical.messages:
        openai_message = ChatMessage(
            role=message.role,
            content=message.content if message.content is not None else _blocks_to_openai_content(message.blocks),
            name=message.name,
            tool_call_id=message.tool_call_id,
            tool_calls=_tool_calls_to_openai(message.tool_calls) or None,
        )
        messages.append(openai_message)

    extra: dict[str, Any] = {}
    if canonical.tools:
        extra["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in canonical.tools
        ]
    if canonical.generation.tool_choice is not None:
        extra["tool_choice"] = canonical.generation.tool_choice
    if canonical.generation.response_format is not None:
        extra["response_format"] = canonical.generation.response_format
    if canonical.generation.parallel_tool_calls is not None:
        extra["parallel_tool_calls"] = canonical.generation.parallel_tool_calls
    if canonical.generation.stop_sequences:
        extra["stop"] = canonical.generation.stop_sequences
    if canonical.metadata:
        extra["metadata"] = canonical.metadata

    return ChatCompletionRequest(
        model=model_override or canonical.route.requested_model,
        messages=messages,
        stream=canonical.generation.stream,
        temperature=canonical.generation.temperature,
        max_tokens=canonical.generation.max_tokens,
        top_p=canonical.generation.top_p,
        **extra,
    )


def chat_completion_body_to_canonical_response(
    response_body: dict[str, object],
    *,
    model_name: str,
    protocol_out: str = "openai",
    upstream_protocol: str | None = None,
    route: CanonicalRoute | None = None,
) -> CanonicalResponse | dict[str, object]:
    if "choices" not in response_body:
        return response_body

    choices = response_body.get("choices")
    first_choice: dict[str, object] = {}
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        first_choice = choices[0]

    message = first_choice.get("message") if isinstance(first_choice, dict) else None
    content_blocks: list[CanonicalContentBlock] = []
    tool_calls: list[CanonicalToolCall] = []
    content_value: Any = None
    if isinstance(message, dict):
        content_value = message.get("content")
        if isinstance(content_value, str) and content_value.strip():
            content_blocks.append(CanonicalContentBlock(type="text", text=content_value, raw={"content": content_value}))
        elif isinstance(content_value, list):
            content_blocks = _content_to_blocks(content_value)

        tool_calls = _tool_calls_to_blocks(message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else None)

    usage = response_body.get("usage")
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    if isinstance(usage, dict):
        input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or (input_tokens + output_tokens))

    return CanonicalResponse(
        request_id=str(response_body.get("id")) if isinstance(response_body.get("id"), str) else None,
        protocol_out=protocol_out,
        upstream_protocol=upstream_protocol,
        route=route or CanonicalRoute(kind="provider", requested_model=model_name, provider=model_name.split("/", 1)[0] if "/" in model_name else None, model_name=model_name.split("/", 1)[1] if "/" in model_name else model_name, resolved_route=model_name),
        model=str(response_body.get("model") or model_name),
        role="assistant",
        content=content_value,
        blocks=content_blocks,
        tool_calls=tool_calls,
        finish_reason=str(first_choice.get("finish_reason")) if isinstance(first_choice.get("finish_reason"), str) else None,
        usage=CanonicalUsage(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens),
        raw=response_body,
    )


def canonical_response_to_anthropic(response: CanonicalResponse | dict[str, object]) -> dict[str, object]:
    if isinstance(response, dict):
        return response
    content_blocks = [_block_to_anthropic_block(block) for block in response.blocks]
    if not content_blocks and isinstance(response.content, str) and response.content.strip():
        content_blocks = [{"type": "text", "text": response.content}]
    if response.tool_calls:
        content_blocks.extend(
            {
                "type": "tool_use",
                "id": tool_call.id,
                "name": tool_call.function.name,
                "input": tool_call.function.arguments if tool_call.function.arguments is not None else {},
            }
            for tool_call in response.tool_calls
        )
    return {
        "id": response.request_id or f"msg_{response.model.replace('/', '_')}",
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": response.model,
        "stop_reason": {
            "stop": "end_turn",
            "length": "max_tokens",
            "tool_calls": "tool_use",
            "function_call": "tool_use",
            "content_filter": "refusal",
            "refusal": "refusal",
            "pause_turn": "pause_turn",
        }.get((response.finish_reason or "stop").lower(), "end_turn"),
        "stop_sequence": None,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }
