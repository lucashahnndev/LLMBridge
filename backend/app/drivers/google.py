from __future__ import annotations

import json
from datetime import datetime, timezone

from backend.app.drivers.base import OpenAICompatibleDriver


class GoogleDriver(OpenAICompatibleDriver):
    MODEL_ALIASES = {
        "gemini-3.1-flash": "gemini-3-flash-preview",
        "gemini-3-flash": "gemini-3-flash-preview",
        "gemini-3.1-pro": "gemini-3-pro-preview",
        "gemini-3-pro": "gemini-3-pro-preview",
    }

    def resolve_model_name(self, model_name: str) -> str:
        return self.MODEL_ALIASES.get(model_name, model_name)

    def build_payload(self, normalized_payload: dict[str, object], model_name: str) -> dict[str, object]:
        payload = super().build_payload(normalized_payload, self.resolve_model_name(model_name))

        # Claude Code / Anthropic requests may carry metadata, but Gemini's OpenAI-compatible
        # endpoint rejects the field entirely, so drop it here instead of leaking provider-agnostic
        # transport details upstream.
        payload.pop("metadata", None)

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

            message: dict[str, object] = {
                "role": "assistant",
                "content": None if tool_calls else ("\n".join(text_parts) if text_parts else None),
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
                delta["content"] = None
            else:
                delta["content"] = "\n".join(text_parts) if text_parts else None

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
