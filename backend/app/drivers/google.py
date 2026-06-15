from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.app.drivers.base import OpenAICompatibleDriver
from backend.app.schemas.canonical import CanonicalRequest


class GoogleDriver(OpenAICompatibleDriver):
    MODEL_ALIASES = {
        "gemini-3.1-flash": "gemini-3-flash-preview",
        "gemini-3-flash": "gemini-3-flash-preview",
        "gemini-3.1-pro": "gemini-3-pro-preview",
        "gemini-3-pro": "gemini-3-pro-preview",
    }

    def resolve_model_name(self, model_name: str) -> str:
        return self.MODEL_ALIASES.get(model_name, model_name)

    def build_native_url(self, model_name: str) -> str:
        native_base_url = self.base_url.removesuffix("/openai")
        return f"{native_base_url}/models/{self.resolve_model_name(model_name)}:generateContent"

    def build_native_headers(self, provider_token: str) -> dict[str, str]:
        return {
            "x-goog-api-key": provider_token,
            "Content-Type": "application/json",
        }

    def _strip_transport_noise(self, payload: dict[str, object]) -> dict[str, object]:
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
        return cleaned

    def _sanitize_json_schema(self, value: object) -> object:
        if isinstance(value, dict):
            sanitized: dict[str, object] = {}
            for key, item in value.items():
                if key == "$schema":
                    continue
                sanitized[key] = self._sanitize_json_schema(item)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize_json_schema(item) for item in value]
        return value

    def build_payload(self, normalized_payload: dict[str, object], model_name: str) -> dict[str, object]:
        payload = self._strip_transport_noise(
            super().build_payload(normalized_payload, self.resolve_model_name(model_name))
        )

        if isinstance(payload.get("tools"), list):
            sanitized_tools: list[dict[str, object]] = []
            for tool in payload["tools"]:
                if not isinstance(tool, dict):
                    continue
                function = tool.get("function")
                if not isinstance(function, dict):
                    sanitized_tools.append(tool)
                    continue
                sanitized_function = dict(function)
                parameters = sanitized_function.get("parameters")
                if parameters is not None:
                    sanitized_function["parameters"] = self._sanitize_json_schema(parameters)
                sanitized_tool = dict(tool)
                sanitized_tool["function"] = sanitized_function
                sanitized_tools.append(sanitized_tool)
            payload["tools"] = sanitized_tools

        # Gemini's OpenAI-compatible endpoint is narrower than generic OpenAI chat.
        # Keep the request OpenAI-like for callers, but strip or soften fields that trigger
        # unsupported response mime / forced function-calling modes upstream.
        has_tooling = bool(payload.get("tools")) or payload.get("tool_choice") is not None
        if has_tooling:
            payload.pop("response_format", None)
            payload.pop("parallel_tool_calls", None)

        tool_choice = payload.get("tool_choice")
        if tool_choice == "none":
            if not payload.get("tools"):
                payload.pop("tool_choice", None)
        elif tool_choice not in (None, "auto"):
            payload["tool_choice"] = "auto"

        return payload

    def _compact_native_schema(self, value: object) -> object:
        native_schema_keys = {
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
        if isinstance(value, dict):
            compacted: dict[str, object] = {}
            properties = value.get("properties")
            if isinstance(properties, dict):
                compacted["properties"] = {
                    property_name: self._compact_native_schema(property_schema)
                    for property_name, property_schema in properties.items()
                    if isinstance(property_schema, dict)
                }

            items = value.get("items")
            if isinstance(items, dict):
                compacted["items"] = self._compact_native_schema(items)
            elif isinstance(items, list):
                compacted["items"] = [
                    self._compact_native_schema(item)
                    for item in items
                    if isinstance(item, dict)
                ]

            for key, item in value.items():
                if key in {"properties", "items", "$schema"}:
                    continue
                if key not in native_schema_keys:
                    continue
                if key == "required" and isinstance(item, list):
                    continue
                compacted[key] = self._compact_native_schema(item)

            compacted_properties = compacted.get("properties")
            required = value.get("required")
            if isinstance(compacted_properties, dict) and isinstance(required, list):
                filtered_required = [name for name in required if name in compacted_properties]
                if filtered_required:
                    compacted["required"] = filtered_required
            return compacted
        if isinstance(value, list):
            return [self._compact_native_schema(item) for item in value]
        return value

    def _canonical_text_from_blocks(self, blocks: list[Any]) -> str | None:
        texts: list[str] = []
        for block in blocks:
            if getattr(block, "type", None) != "text":
                continue
            text = getattr(block, "text", None)
            if isinstance(text, str) and text.strip():
                texts.append(text)
        return "\n".join(texts) if texts else None

    def _json_safe_function_response(self, content: object) -> dict[str, object]:
        if isinstance(content, dict):
            return content
        if isinstance(content, list):
            return {"content": content}
        if content is None:
            return {}
        return {"content": content}

    def _tool_history_text(self, title: str, payload: object) -> str:
        if isinstance(payload, str):
            serialized = payload
        else:
            serialized = json.dumps(payload, ensure_ascii=False)
        return f"{title}\n{serialized}"

    def _trim_contents_for_native_request(self, contents: list[dict[str, object]]) -> list[dict[str, object]]:
        # Gemini native requests are stricter about the final turn than OpenAI-style chat.
        # If the conversation ends on an assistant/model message, drop trailing model turns
        # so the payload still ends on a user turn or becomes empty.
        trimmed = list(contents)
        while trimmed and trimmed[-1].get("role") != "user":
            trimmed.pop()
        return trimmed

    def build_native_payload(self, canonical: CanonicalRequest, model_name: str) -> dict[str, object]:
        resolved_model_name = self.resolve_model_name(model_name)
        contents: list[dict[str, object]] = []
        tool_call_names: dict[str, str] = {}

        system_text = self._canonical_text_from_blocks(canonical.system or [])
        system_instruction: dict[str, object] | None = None
        if system_text:
            system_instruction = {"parts": [{"text": system_text}]}

        for message in canonical.messages:
            parts: list[dict[str, object]] = []
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
                            "text": self._tool_history_text(
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
                    tool_result_name = block.name
                    if not tool_result_name and block.tool_use_id:
                        tool_result_name = tool_call_names.get(str(block.tool_use_id))
                    parts.append(
                        {
                            "text": self._tool_history_text(
                                f"[Previous tool result: {tool_result_name or 'tool_result'}]",
                                {
                                    "id": block.tool_use_id,
                                    "result": self._json_safe_function_response(block.tool_result),
                                },
                            )
                        }
                    )

            if not parts and isinstance(message.content, str) and message.content.strip():
                parts.append({"text": message.content})
            if not parts:
                continue

            role = "model" if message.role in {"assistant", "model"} else "user"
            contents.append({"role": role, "parts": parts})

        contents = self._trim_contents_for_native_request(contents)

        function_declarations: list[dict[str, object]] = []
        for tool in canonical.tools:
            declaration: dict[str, object] = {"name": tool.name}
            if tool.description:
                declaration["description"] = tool.description
            if tool.parameters:
                declaration["parameters"] = self._compact_native_schema(tool.parameters)
            function_declarations.append(declaration)

        generation_config: dict[str, object] = {}
        if canonical.generation.temperature is not None:
            generation_config["temperature"] = canonical.generation.temperature
        if canonical.generation.max_tokens is not None:
            generation_config["maxOutputTokens"] = canonical.generation.max_tokens
        if canonical.generation.top_p is not None:
            generation_config["topP"] = canonical.generation.top_p

        tool_config: dict[str, object] = {}
        tool_choice = canonical.generation.tool_choice
        if tool_choice is not None and function_declarations:
            if isinstance(tool_choice, str):
                if tool_choice == "none":
                    tool_config["functionCallingConfig"] = {"mode": "NONE"}
                elif tool_choice in {"required", "auto"}:
                    tool_config["functionCallingConfig"] = {"mode": "ANY"}
            elif isinstance(tool_choice, dict):
                function = tool_choice.get("function")
                function_name = function.get("name") if isinstance(function, dict) else None
                if isinstance(function_name, str) and function_name.strip():
                    tool_config["functionCallingConfig"] = {
                        "mode": "ANY",
                        "allowedFunctionNames": [function_name.strip()],
                    }

        payload: dict[str, object] = {
            "model": resolved_model_name,
            "contents": contents,
        }
        if system_instruction:
            payload["system_instruction"] = system_instruction
        if function_declarations:
            payload["tools"] = [{"functionDeclarations": function_declarations}]
        if generation_config:
            payload["generationConfig"] = generation_config
        if tool_config:
            payload["toolConfig"] = tool_config
        return payload

    async def send_native_chat_completion(
        self,
        client: httpx.AsyncClient,
        provider_token: str,
        canonical: CanonicalRequest,
        model_name: str,
    ) -> httpx.Response:
        return await client.post(
            self.build_native_url(model_name),
            headers=self.build_native_headers(provider_token),
            json=self.build_native_payload(canonical, model_name),
        )

    def normalize_response_body(
        self,
        response_body: dict[str, object] | list[object] | str,
        model_name: str,
    ) -> dict[str, object] | list[object] | str:
        normalized_body = super().normalize_response_body(response_body, model_name)
        if isinstance(normalized_body, dict) and "choices" in normalized_body:
            return normalized_body

        if not isinstance(response_body, dict) or "choices" in response_body:
            return response_body

        candidates = response_body.get("candidates")
        if not isinstance(candidates, list):
            return response_body

        choices: list[dict[str, object]] = []
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            parts = content.get("parts") if isinstance(content, dict) else []
            if not isinstance(parts, list):
                parts = []

            text_parts: list[str] = []
            tool_calls: list[dict[str, object]] = []
            for part_index, part in enumerate(parts):
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text:
                    text_parts.append(text)

                function_call = part.get("functionCall") or part.get("function_call")
                if isinstance(function_call, dict):
                    name = function_call.get("name")
                    if not isinstance(name, str) or not name.strip():
                        continue
                    arguments = function_call.get("args")
                    if arguments is None:
                        arguments = function_call.get("arguments")
                    if isinstance(arguments, str):
                        arguments_text = arguments
                    elif isinstance(arguments, (dict, list)):
                        arguments_text = json.dumps(arguments, ensure_ascii=False)
                    else:
                        arguments_text = "{}"
                    tool_calls.append(
                        {
                            "id": function_call.get("id") or f"call_{index}_{part_index}",
                            "type": "function",
                            "function": {
                                "name": name.strip(),
                                "arguments": arguments_text,
                            },
                        }
                    )

            finish_reason = candidate.get("finishReason") or candidate.get("finish_reason")
            normalized_finish_reason = {
                "STOP": "stop",
                "MAX_TOKENS": "length",
                "SAFETY": "content_filter",
                "RECITATION": "content_filter",
                "TOOL_CALL": "tool_calls",
                "FUNCTION_CALL": "tool_calls",
            }.get(str(finish_reason).upper(), "stop")
            if tool_calls:
                normalized_finish_reason = "tool_calls"

            content_text = "\n".join(text_parts) if text_parts else None
            message: dict[str, object] = {
                "role": "assistant",
                "content": content_text,
            }
            if tool_calls:
                message["tool_calls"] = tool_calls

            choices.append(
                {
                    "index": index,
                    "message": message,
                    "finish_reason": normalized_finish_reason,
                }
            )

        usage = response_body.get("usageMetadata")
        usage_payload: dict[str, int] = {}
        if isinstance(usage, dict):
            prompt_tokens = usage.get("promptTokenCount")
            completion_tokens = usage.get("candidatesTokenCount")
            total_tokens = usage.get("totalTokenCount")
            if isinstance(prompt_tokens, int):
                usage_payload["prompt_tokens"] = prompt_tokens
            if isinstance(completion_tokens, int):
                usage_payload["completion_tokens"] = completion_tokens
            if isinstance(total_tokens, int):
                usage_payload["total_tokens"] = total_tokens

        created = response_body.get("created")
        if not isinstance(created, int):
            created = int(datetime.now(timezone.utc).timestamp())

        normalized: dict[str, object] = {
            "id": response_body.get("id") or f"chatcmpl-{self.resolve_model_name(model_name)}",
            "object": "chat.completion",
            "created": created,
            "model": self.resolve_model_name(model_name),
            "choices": choices,
        }
        if usage_payload:
            normalized["usage"] = usage_payload
        return normalized

    def normalize_stream_event(
        self,
        event_body: dict[str, object] | list[object] | str,
        model_name: str,
    ) -> dict[str, object] | list[object] | str:
        normalized_event = super().normalize_stream_event(event_body, self.resolve_model_name(model_name))
        if isinstance(normalized_event, dict) and "choices" in normalized_event:
            return normalized_event

        if not isinstance(event_body, dict) or "choices" in event_body:
            return event_body

        candidates = event_body.get("candidates")
        if not isinstance(candidates, list):
            return event_body

        choices: list[dict[str, object]] = []
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            parts = content.get("parts") if isinstance(content, dict) else []
            if not isinstance(parts, list):
                parts = []

            text_parts: list[str] = []
            tool_calls: list[dict[str, object]] = []
            for part_index, part in enumerate(parts):
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text:
                    text_parts.append(text)

                function_call = part.get("functionCall") or part.get("function_call")
                if isinstance(function_call, dict):
                    name = function_call.get("name")
                    if not isinstance(name, str) or not name.strip():
                        continue
                    arguments = function_call.get("args")
                    if arguments is None:
                        arguments = function_call.get("arguments")
                    if isinstance(arguments, str):
                        arguments_text = arguments
                    elif isinstance(arguments, (dict, list)):
                        arguments_text = json.dumps(arguments, ensure_ascii=False)
                    else:
                        arguments_text = "{}"
                    tool_calls.append(
                        {
                            "id": function_call.get("id") or f"call_{index}_{part_index}",
                            "type": "function",
                            "function": {
                                "name": name.strip(),
                                "arguments": arguments_text,
                            },
                        }
                    )

            finish_reason = candidate.get("finishReason") or candidate.get("finish_reason")
            normalized_finish_reason = {
                "STOP": "stop",
                "MAX_TOKENS": "length",
                "SAFETY": "content_filter",
                "RECITATION": "content_filter",
                "TOOL_CALL": "tool_calls",
                "FUNCTION_CALL": "tool_calls",
            }.get(str(finish_reason).upper(), None)

            delta: dict[str, object] = {
                "role": "assistant",
            }
            if tool_calls:
                delta["tool_calls"] = tool_calls
            content_text = "\n".join(text_parts) if text_parts else None
            if content_text is not None:
                delta["content"] = content_text

            choices.append(
                {
                    "index": index,
                    "delta": delta,
                    "finish_reason": normalized_finish_reason,
                }
            )

        usage = event_body.get("usageMetadata")
        usage_payload: dict[str, int] = {}
        if isinstance(usage, dict):
            prompt_tokens = usage.get("promptTokenCount")
            completion_tokens = usage.get("candidatesTokenCount")
            total_tokens = usage.get("totalTokenCount")
            if isinstance(prompt_tokens, int):
                usage_payload["prompt_tokens"] = prompt_tokens
            if isinstance(completion_tokens, int):
                usage_payload["completion_tokens"] = completion_tokens
            if isinstance(total_tokens, int):
                usage_payload["total_tokens"] = total_tokens

        created = event_body.get("created")
        if not isinstance(created, int):
            created = int(datetime.now(timezone.utc).timestamp())

        normalized: dict[str, object] = {
            "id": event_body.get("id") or f"chatcmpl-{self.resolve_model_name(model_name)}",
            "object": "chat.completion.chunk",
            "created": created,
            "model": self.resolve_model_name(model_name),
            "choices": choices,
        }
        if usage_payload:
            normalized["usage"] = usage_payload
        return normalized
