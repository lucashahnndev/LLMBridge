from __future__ import annotations

from abc import ABC, abstractmethod
import json
from datetime import datetime, timezone

import httpx


class ProviderDriver(ABC):
    provider: str

    @abstractmethod
    def build_url(self, model_name: str) -> str:
        raise NotImplementedError

    def build_headers(self, provider_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {provider_token}",
            "Content-Type": "application/json",
        }

    def normalize_payload(self, normalized_payload: dict[str, object], model_name: str) -> dict[str, object]:
        payload = dict(normalized_payload)

        legacy_functions = payload.pop("functions", None)
        if not payload.get("tools") and isinstance(legacy_functions, list):
            tools: list[dict[str, object]] = []
            for function_spec in legacy_functions:
                if isinstance(function_spec, dict) and function_spec.get("name"):
                    tools.append(
                        {
                            "type": "function",
                            "function": function_spec,
                        }
                    )
            if tools:
                payload["tools"] = tools

        legacy_function_call = payload.pop("function_call", None)
        if legacy_function_call is not None and "tool_choice" not in payload:
            if isinstance(legacy_function_call, str):
                if legacy_function_call in {"auto", "none"}:
                    payload["tool_choice"] = legacy_function_call
                elif legacy_function_call == "required":
                    payload["tool_choice"] = "auto"
            elif isinstance(legacy_function_call, dict):
                function_name = legacy_function_call.get("name")
                if isinstance(function_name, str) and function_name.strip():
                    payload["tool_choice"] = {
                        "type": "function",
                        "function": {
                            "name": function_name.strip(),
                        },
                    }

        # Some OpenAI-compatible chat completion surfaces reject metadata unless
        # the request is explicitly stored. Preserve it only when store is on.
        if payload.get("metadata") is not None and not payload.get("store"):
            payload.pop("metadata", None)

        tool_choice = payload.get("tool_choice")
        if self.provider == "meta" and isinstance(tool_choice, dict):
            payload["tool_choice"] = "required"
        elif self.provider in {"mistral", "mistral-ai"}:
            if isinstance(tool_choice, dict):
                payload["tool_choice"] = "any"
            elif tool_choice == "required":
                payload["tool_choice"] = "any"
            payload.pop("parallel_tool_calls", None)

        return payload

    def build_payload(self, normalized_payload: dict[str, object], model_name: str) -> dict[str, object]:
        payload = self.normalize_payload(normalized_payload, model_name)
        payload["model"] = model_name
        return payload

    def normalize_response_body(
        self,
        response_body: dict[str, object] | list[object] | str,
        model_name: str,
    ) -> dict[str, object] | list[object] | str:
        _ = model_name
        if not isinstance(response_body, dict) or "choices" in response_body:
            return response_body

        message = response_body.get("message")
        if not isinstance(message, dict):
            return response_body

        content = message.get("content")
        tool_calls_raw = message.get("tool_calls")
        tool_calls: list[dict[str, object]] = []
        if isinstance(tool_calls_raw, list):
            for index, tool_call in enumerate(tool_calls_raw):
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
                if isinstance(arguments, str):
                    arguments_text = arguments
                elif isinstance(arguments, (dict, list)):
                    arguments_text = json.dumps(arguments, ensure_ascii=False)
                else:
                    arguments_text = "{}"
                tool_calls.append(
                    {
                        "id": tool_call.get("id") or f"tool_{index}",
                        "type": "function",
                        "function": {
                            "name": function_name.strip(),
                            "arguments": arguments_text,
                        },
                    }
                )

        done_reason = response_body.get("done_reason") or response_body.get("finish_reason")
        finish_reason = {
            "stop": "stop",
            "done": "stop",
            "tool_calls": "tool_calls",
            "function_call": "tool_calls",
            "length": "length",
            "content_filter": "content_filter",
        }.get(str(done_reason).lower(), "stop")

        created = response_body.get("created")
        if not isinstance(created, int):
            created_at = response_body.get("created_at")
            if isinstance(created_at, str):
                try:
                    created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    created = int(created_dt.astimezone(timezone.utc).timestamp())
                except ValueError:
                    created = int(datetime.now(timezone.utc).timestamp())
            else:
                created = int(datetime.now(timezone.utc).timestamp())

        normalized_message: dict[str, object] = {
            "role": message.get("role") or "assistant",
            "content": content,
        }
        if tool_calls:
            normalized_message["tool_calls"] = tool_calls

        normalized: dict[str, object] = {
            "id": response_body.get("id") or f"chatcmpl-{model_name}",
            "object": "chat.completion",
            "created": created,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": normalized_message,
                    "finish_reason": finish_reason,
                }
            ],
        }

        usage_payload = response_body.get("usage")
        if isinstance(usage_payload, dict):
            normalized["usage"] = usage_payload
        else:
            prompt_tokens = response_body.get("prompt_eval_count")
            completion_tokens = response_body.get("eval_count")
            if isinstance(prompt_tokens, int) or isinstance(completion_tokens, int):
                prompt_value = int(prompt_tokens or 0)
                completion_value = int(completion_tokens or 0)
                normalized["usage"] = {
                    "prompt_tokens": prompt_value,
                    "completion_tokens": completion_value,
                    "total_tokens": int(response_body.get("total_tokens") or prompt_value + completion_value),
                }

        return normalized

    def normalize_stream_event(
        self,
        event_body: dict[str, object] | list[object] | str,
        model_name: str,
    ) -> dict[str, object] | list[object] | str:
        if not isinstance(event_body, dict):
            return event_body

        if "choices" in event_body:
            choices = event_body.get("choices")
            if not isinstance(choices, list):
                return event_body
            normalized_choices: list[dict[str, object]] = []
            for index, choice in enumerate(choices):
                if not isinstance(choice, dict):
                    continue
                normalized_choice = dict(choice)
                delta = normalized_choice.get("delta")
                if isinstance(delta, dict):
                    normalized_delta = dict(delta)
                    tool_calls_raw = normalized_delta.get("tool_calls")
                    tool_calls: list[dict[str, object]] = []
                    if isinstance(tool_calls_raw, list):
                        for tool_index, tool_call in enumerate(tool_calls_raw):
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
                            if isinstance(arguments, str):
                                arguments_text = arguments
                            elif isinstance(arguments, (dict, list)):
                                arguments_text = json.dumps(arguments, ensure_ascii=False)
                            else:
                                arguments_text = "{}"
                            tool_calls.append(
                                {
                                    "id": tool_call.get("id") or f"tool_{tool_index}",
                                    "type": "function",
                                    "function": {
                                        "name": function_name.strip(),
                                        "arguments": arguments_text,
                                    },
                                }
                            )
                    legacy_function_call = normalized_delta.pop("function_call", None)
                    if not tool_calls and isinstance(legacy_function_call, dict):
                        function_name = legacy_function_call.get("name")
                        if isinstance(function_name, str) and function_name.strip():
                            arguments = legacy_function_call.get("arguments")
                            if isinstance(arguments, str):
                                arguments_text = arguments
                            elif isinstance(arguments, (dict, list)):
                                arguments_text = json.dumps(arguments, ensure_ascii=False)
                            else:
                                arguments_text = "{}"
                            tool_calls.append(
                                {
                                    "id": legacy_function_call.get("id") or f"tool_{index}",
                                    "type": "function",
                                    "function": {
                                        "name": function_name.strip(),
                                        "arguments": arguments_text,
                                    },
                                }
                            )
                    if tool_calls:
                        normalized_delta["tool_calls"] = tool_calls
                        normalized_choice["delta"] = normalized_delta
                        if normalized_choice.get("finish_reason") in (None, "function_call"):
                            normalized_choice["finish_reason"] = "tool_calls"
                finish_reason = normalized_choice.get("finish_reason")
                if isinstance(finish_reason, str) and finish_reason.lower() == "function_call":
                    normalized_choice["finish_reason"] = "tool_calls"
                normalized_choices.append(normalized_choice)
            normalized_event = dict(event_body)
            normalized_event["choices"] = normalized_choices
            return normalized_event

        message = event_body.get("message")
        if not isinstance(message, dict):
            return event_body

        content = message.get("content")
        tool_calls_raw = message.get("tool_calls")
        tool_calls: list[dict[str, object]] = []
        if isinstance(tool_calls_raw, list):
            for index, tool_call in enumerate(tool_calls_raw):
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
                if isinstance(arguments, str):
                    arguments_text = arguments
                elif isinstance(arguments, (dict, list)):
                    arguments_text = json.dumps(arguments, ensure_ascii=False)
                else:
                    arguments_text = "{}"
                tool_calls.append(
                    {
                        "id": tool_call.get("id") or f"tool_{index}",
                        "type": "function",
                        "function": {
                            "name": function_name.strip(),
                            "arguments": arguments_text,
                        },
                    }
                )

        done_reason = event_body.get("done_reason") or event_body.get("finish_reason")
        finish_reason = {
            "stop": "stop",
            "done": "stop",
            "tool_calls": "tool_calls",
            "function_call": "tool_calls",
            "length": "length",
            "content_filter": "content_filter",
        }.get(str(done_reason).lower(), None)

        delta: dict[str, object] = {
            "role": message.get("role") or "assistant",
        }
        if tool_calls:
            delta["tool_calls"] = tool_calls
        if content is not None:
            delta["content"] = content

        created = event_body.get("created")
        if not isinstance(created, int):
            created_at = event_body.get("created_at")
            if isinstance(created_at, str):
                try:
                    created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    created = int(created_dt.astimezone(timezone.utc).timestamp())
                except ValueError:
                    created = int(datetime.now(timezone.utc).timestamp())
            else:
                created = int(datetime.now(timezone.utc).timestamp())

        normalized: dict[str, object] = {
            "id": event_body.get("id") or f"chatcmpl-{model_name}",
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": finish_reason,
                }
            ],
        }

        usage_payload = event_body.get("usage")
        if isinstance(usage_payload, dict):
            normalized["usage"] = usage_payload
        else:
            prompt_tokens = event_body.get("prompt_eval_count")
            completion_tokens = event_body.get("eval_count")
            if isinstance(prompt_tokens, int) or isinstance(completion_tokens, int):
                prompt_value = int(prompt_tokens or 0)
                completion_value = int(completion_tokens or 0)
                normalized["usage"] = {
                    "prompt_tokens": prompt_value,
                    "completion_tokens": completion_value,
                    "total_tokens": int(event_body.get("total_tokens") or prompt_value + completion_value),
                }

        return normalized

    async def send_chat_completion(
        self,
        client: httpx.AsyncClient,
        provider_token: str,
        normalized_payload: dict[str, object],
        model_name: str,
    ) -> httpx.Response:
        response = await client.post(
            self.build_url(model_name),
            headers=self.build_headers(provider_token),
            json=self.build_payload(normalized_payload, model_name),
        )
        return response


class OpenAICompatibleDriver(ProviderDriver):
    def __init__(self, provider: str, base_url: str) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")

    def build_url(self, model_name: str) -> str:
        _ = model_name
        return f"{self.base_url}/chat/completions"
