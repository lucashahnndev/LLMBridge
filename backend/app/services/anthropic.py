from __future__ import annotations

import json
from typing import Any

from fastapi.responses import JSONResponse, StreamingResponse

from backend.app.schemas.anthropic import AnthropicMessage, AnthropicMessagesRequest
from backend.app.schemas.proxy import ChatCompletionRequest, ChatMessage
from backend.app.services.canonical import (
    anthropic_request_to_canonical,
    canonical_request_to_chat_completion,
    canonical_response_to_anthropic,
    chat_completion_body_to_canonical_response,
)


def _content_blocks_to_text(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    text_parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                text_parts.append(text)
        elif block_type == "tool_result":
            result_content = block.get("content")
            if isinstance(result_content, str) and result_content:
                text_parts.append(result_content)
            elif isinstance(result_content, (dict, list)):
                text_parts.append(json.dumps(result_content, ensure_ascii=False))
    combined = "\n".join(part for part in text_parts if part)
    return combined or None


def _tool_choice_to_openai(tool_choice: Any) -> Any:
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        lowered = tool_choice.lower()
        if lowered in {"auto", "none"}:
            return lowered
        if lowered == "any":
            return "auto"
        return "auto"
    if isinstance(tool_choice, dict):
        choice_type = str(tool_choice.get("type") or "").lower()
        if choice_type in {"auto", "none"}:
            return choice_type
        if choice_type in {"tool", "function"}:
            name = tool_choice.get("name")
            if isinstance(name, str) and name.strip():
                return {"type": "function", "function": {"name": name.strip()}}
    return "auto"


def anthropic_tools_to_openai(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    normalized_tools: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        normalized_tools.append(
            {
                "type": "function",
                "function": {
                    "name": name.strip(),
                    "description": tool.get("description"),
                    "parameters": tool.get("input_schema") or tool.get("parameters") or {"type": "object", "properties": {}},
                },
            }
        )
    return normalized_tools or None


def anthropic_message_to_chat_messages(message: AnthropicMessage) -> list[ChatMessage]:
    if isinstance(message.content, str) or message.content is None:
        return [ChatMessage(role=message.role, content=message.content or "")]

    if not isinstance(message.content, list):
        return [ChatMessage(role=message.role, content=_content_blocks_to_text(message.content) or "")]

    if message.role == "assistant":
        text_parts: list[str] = []
        tool_calls: list[dict[str, object]] = []
        for index, block in enumerate(message.content):
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text")
                if isinstance(text, str) and text:
                    text_parts.append(text)
                continue
            if block_type != "tool_use":
                continue
            tool_name = block.get("name")
            if not isinstance(tool_name, str) or not tool_name.strip():
                continue
            tool_input = block.get("input")
            if isinstance(tool_input, str):
                arguments = tool_input
            elif isinstance(tool_input, (dict, list)):
                arguments = json.dumps(tool_input, ensure_ascii=False)
            else:
                arguments = "{}"
            tool_calls.append(
                {
                    "id": block.get("id") or f"tool_{index}",
                    "type": "function",
                    "function": {
                        "name": tool_name.strip(),
                        "arguments": arguments,
                    },
                }
            )

        assistant_message = ChatMessage(
            role="assistant",
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls or None,
        )
        return [assistant_message]

    user_messages: list[ChatMessage] = []
    tool_result_messages: list[ChatMessage] = []
    text_parts: list[str] = []

    for block in message.content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "tool_result":
            tool_use_id = block.get("tool_use_id")
            result_content = block.get("content")
            if isinstance(result_content, str):
                text_value = result_content
            elif isinstance(result_content, (dict, list)):
                text_value = json.dumps(result_content, ensure_ascii=False)
            else:
                text_value = ""
            tool_result_messages.append(
                ChatMessage(
                    role="tool",
                    content=text_value,
                    tool_call_id=str(tool_use_id) if tool_use_id is not None else None,
                    name=block.get("name") if isinstance(block.get("name"), str) else None,
                )
            )
        elif block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                text_parts.append(text)

    if tool_result_messages:
        user_messages.extend(tool_result_messages)
    if text_parts:
        user_messages.append(ChatMessage(role="user", content="\n".join(text_parts)))

    if user_messages:
        return user_messages

    return [ChatMessage(role=message.role, content=_content_blocks_to_text(message.content) or "")]


def anthropic_request_to_chat_completion(payload: AnthropicMessagesRequest) -> ChatCompletionRequest:
    canonical_request = anthropic_request_to_canonical(payload)
    canonical_request.generation.tool_choice = _tool_choice_to_openai(payload.tool_choice)
    canonical_request.generation.stop_sequences = list(payload.stop_sequences or [])
    if payload.top_k is not None:
        canonical_request.generation.top_k = payload.top_k
    canonical_request.metadata = dict(payload.metadata or {})
    return canonical_request_to_chat_completion(canonical_request, model_override=payload.model)


def _map_stop_reason(finish_reason: Any) -> str:
    if not isinstance(finish_reason, str):
        return "end_turn"
    lowered = finish_reason.lower()
    return {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
        "function_call": "tool_use",
        "content_filter": "refusal",
        "refusal": "refusal",
        "pause_turn": "pause_turn",
    }.get(lowered, "end_turn")


def _parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, list):
        return {"items": arguments}
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {"raw": arguments}
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
        return {"raw": arguments}
    return {}


def chat_completion_body_to_anthropic(response_body: dict[str, object], model_name: str) -> dict[str, object]:
    canonical_response = chat_completion_body_to_canonical_response(
        response_body,
        model_name=model_name,
        protocol_out="anthropic",
    )
    anthropic_response = canonical_response_to_anthropic(canonical_response)
    if isinstance(anthropic_response, dict):
        return anthropic_response
    return response_body


def anthropic_error_response(message: str, error_type: str = "invalid_request_error") -> dict[str, object]:
    return {
        "type": "error",
        "error": {
            "type": error_type,
            "message": message,
        },
    }


def anthropic_sse_event(event_type: str, payload: dict[str, object]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
