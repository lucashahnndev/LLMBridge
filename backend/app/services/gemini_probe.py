from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from backend.app.drivers.google import GoogleDriver
from backend.app.schemas.canonical import CanonicalRequest
from backend.app.services.canonical import canonical_request_to_chat_completion


ProbeStrategy = Literal[
    "baseline",
    "strict-schema",
    "drop-parameterless",
    "drop-parameterless-strict",
    "auto",
]

ProbeTransport = Literal["openai", "native"]


STRICT_SCHEMA_KEYS = {
    "type",
    "properties",
    "required",
    "items",
    "enum",
    "additionalProperties",
    "description",
    "format",
    "nullable",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "pattern",
    "minItems",
    "maxItems",
    "minProperties",
    "maxProperties",
    "default",
    "title",
}

NATIVE_SCHEMA_KEYS = {
    "type",
    "properties",
    "required",
    "items",
    "enum",
    "description",
    "format",
    "nullable",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "pattern",
    "minItems",
    "maxItems",
    "prefixItems",
    "title",
}


@dataclass(slots=True)
class GeminiProbeCandidate:
    transport: str
    strategy: str
    model_name: str
    payload: dict[str, Any]


def load_trace(trace_path: str | Path) -> dict[str, Any]:
    return json.loads(Path(trace_path).read_text(encoding="utf-8"))


def _selected_model_name(trace: dict[str, Any], model_name: str | None = None) -> str:
    if model_name:
        return model_name
    route = trace.get("route")
    if isinstance(route, dict):
        selected = route.get("selected")
        if isinstance(selected, dict):
            selected_model_name = selected.get("model_name")
            if isinstance(selected_model_name, str) and selected_model_name.strip():
                return selected_model_name.strip()
    canonical = trace.get("canonical")
    if isinstance(canonical, dict):
        request = canonical.get("request")
        if isinstance(request, dict):
            route_data = request.get("route")
            if isinstance(route_data, dict):
                canonical_model_name = route_data.get("model_name")
                if isinstance(canonical_model_name, str) and canonical_model_name.strip():
                    return canonical_model_name.strip()
    raise ValueError("trace does not include a resolvable Google model_name")


def _compact_schema(value: Any, *, strict: bool) -> Any:
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for key, item in value.items():
            if key == "$schema":
                continue
            if strict and key not in STRICT_SCHEMA_KEYS:
                continue
            compacted[key] = _compact_schema(item, strict=strict)
        return compacted
    if isinstance(value, list):
        return [_compact_schema(item, strict=strict) for item in value]
    return value


def _compact_native_schema(value: Any) -> Any:
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        properties = value.get("properties")
        if isinstance(properties, dict):
            compacted["properties"] = {
                property_name: _compact_native_schema(property_schema)
                for property_name, property_schema in properties.items()
                if isinstance(property_schema, dict)
            }
        items = value.get("items")
        if isinstance(items, dict):
            compacted["items"] = _compact_native_schema(items)
        elif isinstance(items, list):
            compacted["items"] = [_compact_native_schema(item) for item in items if isinstance(item, dict)]

        for key, item in value.items():
            if key in {"properties", "items", "$schema"}:
                continue
            if key not in NATIVE_SCHEMA_KEYS:
                continue
            if key == "required" and isinstance(item, list):
                continue
            compacted[key] = _compact_native_schema(item)
        properties = compacted.get("properties")
        required = value.get("required")
        if isinstance(properties, dict) and isinstance(required, list):
            filtered_required = [name for name in required if name in properties]
            if filtered_required:
                compacted["required"] = filtered_required
            else:
                compacted.pop("required", None)
        return compacted
    if isinstance(value, list):
        return [_compact_native_schema(item) for item in value]
    return value


def _unredact_placeholders(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _unredact_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_unredact_placeholders(item) for item in value]
    if value == "[redacted]":
        return None
    return value


def _sanitize_google_payload(payload: dict[str, Any], *, strategy: str) -> dict[str, Any]:
    cleaned = dict(payload)
    for key in (
        "metadata",
        "thinking",
        "context_management",
        "output_config",
        "reasoning",
        "citations",
        "stream_options",
    ):
        cleaned.pop(key, None)

    if isinstance(cleaned.get("tools"), list):
        sanitized_tools: list[dict[str, Any]] = []
        for tool in cleaned["tools"]:
            if not isinstance(tool, dict):
                continue
            function = tool.get("function")
            if not isinstance(function, dict):
                sanitized_tools.append(tool)
                continue
            sanitized_function = dict(function)
            parameters = sanitized_function.get("parameters")
            if parameters is not None:
                sanitized_function["parameters"] = _compact_schema(
                    parameters,
                    strict=strategy == "strict-schema",
                )
            if strategy in {"drop-parameterless", "drop-parameterless-strict"}:
                function_parameters = sanitized_function.get("parameters")
                if isinstance(function_parameters, dict):
                    properties = function_parameters.get("properties")
                    required = function_parameters.get("required")
                    if (
                        isinstance(properties, dict)
                        and not properties
                        and not required
                    ):
                        continue
            sanitized_tool = dict(tool)
            sanitized_tool["function"] = sanitized_function
            sanitized_tools.append(sanitized_tool)
        cleaned["tools"] = sanitized_tools

    return cleaned


def _canonical_text_from_blocks(blocks: list[Any]) -> str | None:
    texts: list[str] = []
    for block in blocks:
        block_type = getattr(block, "type", None)
        if block_type != "text":
            continue
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            texts.append(text)
    if texts:
        return "\n".join(texts)
    return None


def _json_safe_response(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        return {"content": content}
    if content is None:
        return {}
    return {"content": content}


def _tool_history_text(title: str, payload: Any) -> str:
    if isinstance(payload, str):
        serialized = payload
    else:
        serialized = json.dumps(payload, ensure_ascii=False)
    return f"{title}\n{serialized}"


def _canonical_to_gemini_native_payload(canonical: CanonicalRequest, *, model_name: str) -> dict[str, Any]:
    contents: list[dict[str, Any]] = []
    tool_call_names: dict[str, str] = {}

    system_text = _canonical_text_from_blocks(canonical.system or [])
    system_instruction: dict[str, Any] | None = None
    if system_text:
        system_instruction = {"parts": [{"text": system_text}]}

    for message in canonical.messages:
        parts: list[dict[str, Any]] = []
        for block in message.blocks:
            if block.type == "text" and isinstance(block.text, str):
                parts.append({"text": block.text})
                continue
            if block.type == "tool_use" and block.tool_call is not None:
                tool_call_id = block.tool_call.id or block.tool_use_id
                tool_name = block.tool_call.function.name
                if tool_call_id and tool_name:
                    tool_call_names[str(tool_call_id)] = tool_name
                parts.append(
                    {
                        "text": _tool_history_text(
                            f"[Previous tool call: {tool_name}]",
                            {
                                "id": tool_call_id,
                                "arguments": block.tool_call.function.arguments or {},
                            },
                        )
                    }
                )
                continue
            if block.type == "tool_result":
                name = block.name or (tool_call_names.get(str(block.tool_use_id)) if block.tool_use_id else None) or "tool_result"
                response = _json_safe_response(block.tool_result)
                parts.append(
                    {
                        "text": _tool_history_text(
                            f"[Previous tool result: {name}]",
                            {
                                "id": block.tool_use_id,
                                "result": response,
                            },
                        )
                    }
                )
                continue

        if not parts and isinstance(message.content, str) and message.content.strip():
            parts.append({"text": message.content})

        if not parts:
            continue

        role = "model" if message.role in {"assistant", "model"} else "user"
        contents.append({"role": role, "parts": parts})

    tools: list[dict[str, Any]] = []
    function_declarations: list[dict[str, Any]] = []
    for tool in canonical.tools:
        declaration: dict[str, Any] = {"name": tool.name}
        if tool.description:
            declaration["description"] = tool.description
        if tool.parameters:
            declaration["parameters"] = _compact_schema(tool.parameters, strict=False)
        function_declarations.append(declaration)
    if function_declarations:
        tools.append({"functionDeclarations": function_declarations})

    generation_config: dict[str, Any] = {}
    if canonical.generation.temperature is not None:
        generation_config["temperature"] = canonical.generation.temperature
    if canonical.generation.max_tokens is not None:
        generation_config["maxOutputTokens"] = canonical.generation.max_tokens
    if canonical.generation.top_p is not None:
        generation_config["topP"] = canonical.generation.top_p

    tool_config: dict[str, Any] = {}
    if canonical.generation.tool_choice is not None:
        tool_choice = canonical.generation.tool_choice
        if isinstance(tool_choice, str):
            tool_config["functionCallingConfig"] = {
                "mode": "ANY" if tool_choice in {"required", "auto"} else "AUTO"
            }
        elif isinstance(tool_choice, dict):
            function_name = None
            function = tool_choice.get("function")
            if isinstance(function, dict):
                function_name = function.get("name")
            if isinstance(function_name, str) and function_name.strip():
                tool_config["functionCallingConfig"] = {
                    "mode": "ANY",
                    "allowedFunctionNames": [function_name.strip()],
                }

    payload: dict[str, Any] = {
        "model": model_name,
        "contents": contents,
    }
    if system_instruction:
        payload["system_instruction"] = system_instruction
    if tools:
        payload["tools"] = tools
    if generation_config:
        payload["generationConfig"] = generation_config
    if tool_config:
        payload["toolConfig"] = tool_config
    return payload


def build_google_probe_candidates(
    trace: dict[str, Any],
    *,
    base_url: str,
    model_name: str | None = None,
    strategy: ProbeStrategy = "auto",
    transport: ProbeTransport = "openai",
) -> list[GeminiProbeCandidate]:
    canonical_payload = trace.get("canonical", {}).get("request")
    if not isinstance(canonical_payload, dict):
        raise ValueError("trace does not contain canonical.request")

    canonical = CanonicalRequest.model_validate(_unredact_placeholders(canonical_payload))
    driver = GoogleDriver("google", base_url)
    resolved_model_name = driver.resolve_model_name(_selected_model_name(trace, model_name))
    route_model = f"google/{resolved_model_name}"
    candidates: list[GeminiProbeCandidate] = []
    if transport == "openai":
        normalized = canonical_request_to_chat_completion(
            canonical,
            model_override=route_model,
        ).model_dump(exclude_none=True, exclude={"model"})
        payload = driver.build_payload(normalized, resolved_model_name)

        if strategy in {"baseline", "auto"}:
            candidates.append(
                GeminiProbeCandidate(
                    transport="openai",
                    strategy="baseline",
                    model_name=resolved_model_name,
                    payload=payload,
                )
            )
        if strategy in {"strict-schema", "auto"}:
            candidates.append(
                GeminiProbeCandidate(
                    transport="openai",
                    strategy="strict-schema",
                    model_name=resolved_model_name,
                    payload=_sanitize_google_payload(payload, strategy="strict-schema"),
                )
            )
        if strategy in {"drop-parameterless", "auto"}:
            candidates.append(
                GeminiProbeCandidate(
                    transport="openai",
                    strategy="drop-parameterless",
                    model_name=resolved_model_name,
                    payload=_sanitize_google_payload(payload, strategy="drop-parameterless"),
                )
            )
        if strategy in {"drop-parameterless-strict", "auto"}:
            candidates.append(
                GeminiProbeCandidate(
                    transport="openai",
                    strategy="drop-parameterless-strict",
                    model_name=resolved_model_name,
                    payload=_sanitize_google_payload(payload, strategy="drop-parameterless-strict"),
                )
            )
    elif transport == "native":
        payload = driver.build_native_payload(canonical, resolved_model_name)
        if strategy in {"baseline", "auto"}:
            candidates.append(
                GeminiProbeCandidate(
                    transport="native",
                    strategy="baseline",
                    model_name=resolved_model_name,
                    payload=payload,
                )
            )
        if strategy in {"strict-schema", "auto"}:
            candidates.append(
                GeminiProbeCandidate(
                    transport="native",
                    strategy="strict-schema",
                    model_name=resolved_model_name,
                    payload=payload,
                )
            )
        if strategy in {"drop-parameterless", "auto"}:
            filtered_payload = dict(payload)
            filtered_tools: list[dict[str, Any]] = []
            for tool in payload.get("tools", []):
                if not isinstance(tool, dict):
                    continue
                function_declarations = tool.get("functionDeclarations")
                if not isinstance(function_declarations, list):
                    filtered_tools.append(tool)
                    continue
                filtered_declarations: list[dict[str, Any]] = []
                for declaration in function_declarations:
                    if not isinstance(declaration, dict):
                        continue
                    parameters = declaration.get("parameters")
                    if isinstance(parameters, dict):
                        properties = parameters.get("properties")
                        required = parameters.get("required")
                        if isinstance(properties, dict) and not properties and not required:
                            continue
                    filtered_declarations.append(declaration)
                if filtered_declarations:
                    filtered_tools.append({"functionDeclarations": filtered_declarations})
            if filtered_tools:
                filtered_payload["tools"] = filtered_tools
            candidates.append(
                GeminiProbeCandidate(
                    transport="native",
                    strategy="drop-parameterless",
                    model_name=resolved_model_name,
                    payload=filtered_payload,
                )
            )
        if strategy in {"drop-parameterless-strict", "auto"}:
            filtered_payload = dict(payload)
            filtered_tools = []
            for tool in payload.get("tools", []):
                if not isinstance(tool, dict):
                    continue
                function_declarations = tool.get("functionDeclarations")
                if not isinstance(function_declarations, list):
                    filtered_tools.append(tool)
                    continue
                filtered_declarations = []
                for declaration in function_declarations:
                    if not isinstance(declaration, dict):
                        continue
                    sanitized_declaration = dict(declaration)
                    parameters = sanitized_declaration.get("parameters")
                    if parameters is not None:
                        sanitized_declaration["parameters"] = _compact_native_schema(parameters)
                    parameters = sanitized_declaration.get("parameters")
                    if isinstance(parameters, dict):
                        properties = parameters.get("properties")
                        required = parameters.get("required")
                        if isinstance(properties, dict) and not properties and not required:
                            continue
                    filtered_declarations.append(sanitized_declaration)
                if filtered_declarations:
                    filtered_tools.append({"functionDeclarations": filtered_declarations})
            if filtered_tools:
                filtered_payload["tools"] = filtered_tools
            candidates.append(
                GeminiProbeCandidate(
                    transport="native",
                    strategy="drop-parameterless-strict",
                    model_name=resolved_model_name,
                    payload=filtered_payload,
                )
            )
    else:
        raise ValueError(f"unsupported transport: {transport}")
    return candidates
