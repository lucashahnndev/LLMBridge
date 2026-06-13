import unittest
from unittest.mock import patch

from backend.app.core.config import Settings
from backend.app.drivers import (
    GithubModelsDriver,
    GoogleDriver,
    OpenAICompatibleDriver,
    OpenAIDriver,
    OpenRouterDriver,
    get_output_adapter_driver,
    get_provider_driver,
)
from backend.app.schemas.canonical import (
    CanonicalContentBlock,
    CanonicalGeneration,
    CanonicalMessage,
    CanonicalRequest,
    CanonicalRoute,
    CanonicalToolCall,
    CanonicalToolDefinition,
    CanonicalToolFunction,
)


class DriverRegistryTest(unittest.TestCase):
    def test_registry_returns_openai_driver(self) -> None:
        driver = get_provider_driver("openai")
        self.assertIsInstance(driver, OpenAIDriver)

    def test_registry_returns_openrouter_driver(self) -> None:
        driver = get_provider_driver("openrouter")
        self.assertIsInstance(driver, OpenRouterDriver)

    def test_registry_returns_google_driver(self) -> None:
        driver = get_provider_driver("google")
        self.assertIsInstance(driver, GoogleDriver)

    def test_registry_returns_github_models_driver(self) -> None:
        driver = get_provider_driver("github")
        self.assertIsInstance(driver, GithubModelsDriver)

    def test_output_adapter_returns_openai_driver_for_openai(self) -> None:
        driver = get_output_adapter_driver("openai")
        self.assertIsInstance(driver, OpenAIDriver)

    def test_output_adapter_returns_google_driver_for_google(self) -> None:
        driver = get_output_adapter_driver("google")
        self.assertIsInstance(driver, GoogleDriver)

    def test_output_adapter_returns_generic_openai_compatible_driver_for_microsoft(self) -> None:
        with patch(
            "backend.app.drivers.registry.get_settings",
            return_value=Settings(openai_api_base="https://api.openai.com/v1"),
        ):
            driver = get_output_adapter_driver("microsoft")
        self.assertIsInstance(driver, OpenAICompatibleDriver)
        self.assertEqual(driver.provider, "microsoft")


class GithubModelsDriverTest(unittest.TestCase):
    def test_github_models_driver_builds_github_inference_endpoint(self) -> None:
        driver = GithubModelsDriver("github", "https://models.github.ai/inference", "2022-11-28")
        self.assertEqual(
            driver.build_url("openai/gpt-4.1"),
            "https://models.github.ai/inference/chat/completions",
        )
        headers = driver.build_headers("github-secret")
        self.assertEqual(headers["Authorization"], "Bearer github-secret")
        self.assertEqual(headers["Accept"], "application/vnd.github+json")
        self.assertEqual(headers["X-GitHub-Api-Version"], "2022-11-28")

    def test_github_models_driver_keeps_downstream_target_in_model_field(self) -> None:
        driver = GithubModelsDriver("github", "https://models.github.ai/inference", "2022-11-28")
        payload = driver.build_payload({"messages": []}, "openai/gpt-4.1")
        self.assertEqual(payload["model"], "openai/gpt-4.1")

    def test_github_models_driver_rejects_missing_downstream_target(self) -> None:
        from fastapi import HTTPException

        driver = GithubModelsDriver("github", "https://models.github.ai/inference", "2022-11-28")
        with self.assertRaises(HTTPException):
            driver.resolve_model_name("openai")


class GoogleDriverAliasTest(unittest.TestCase):
    def test_google_driver_maps_alias_to_real_model_id(self) -> None:
        driver = GoogleDriver("google", "https://generativelanguage.googleapis.com/v1beta/openai")
        payload = driver.build_payload({"messages": []}, "gemini-3.1-flash")
        self.assertEqual(payload["model"], "gemini-3-flash-preview")

    def test_google_driver_keeps_real_model_id_unchanged(self) -> None:
        driver = GoogleDriver("google", "https://generativelanguage.googleapis.com/v1beta/openai")
        payload = driver.build_payload({"messages": []}, "gemini-3-flash-preview")
        self.assertEqual(payload["model"], "gemini-3-flash-preview")

    def test_google_driver_normalizes_legacy_tool_calling_and_strips_unsupported_response_format(self) -> None:
        driver = GoogleDriver("google", "https://generativelanguage.googleapis.com/v1beta/openai")
        payload = driver.build_payload(
            {
                "messages": [],
                "thinking": {"budget_tokens": 128},
                "context_management": {"strategy": "adaptive"},
                "output_config": {"mime_type": "application/json"},
                "metadata": {"request_id": "req_123"},
                "response_format": {"type": "json_object"},
                "tool_choice": "required",
                "function_call": {"name": "demo"},
                "functions": [{"name": "legacy_demo"}],
                "parallel_tool_calls": True,
                "tools": [{"type": "function", "function": {"name": "demo", "parameters": {}}}],
            },
            "gemini-3.1-flash",
        )
        self.assertEqual(payload["model"], "gemini-3-flash-preview")
        self.assertNotIn("response_format", payload)
        self.assertNotIn("functions", payload)
        self.assertNotIn("function_call", payload)
        self.assertNotIn("parallel_tool_calls", payload)
        self.assertNotIn("metadata", payload)
        self.assertNotIn("thinking", payload)
        self.assertNotIn("context_management", payload)
        self.assertNotIn("output_config", payload)
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertIn("tools", payload)
        self.assertEqual(payload["tools"][0]["function"]["name"], "demo")

    def test_google_driver_strips_json_schema_keywords_from_tool_parameters(self) -> None:
        driver = GoogleDriver("google", "https://generativelanguage.googleapis.com/v1beta/openai")
        payload = driver.build_payload(
            {
                "messages": [],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "demo",
                            "parameters": {
                                "$schema": "https://json-schema.org/draft/2020-12/schema",
                                "type": "object",
                                "properties": {"answer": {"type": "string"}},
                            },
                        },
                    }
                ],
            },
            "gemini-3.1-flash",
        )
        self.assertNotIn("$schema", payload["tools"][0]["function"]["parameters"])
        self.assertEqual(payload["tools"][0]["function"]["parameters"]["type"], "object")

    def test_google_driver_coerces_named_tool_choice_to_auto_for_stability(self) -> None:
        driver = GoogleDriver("google", "https://generativelanguage.googleapis.com/v1beta/openai")
        payload = driver.build_payload(
            {
                "messages": [],
                "tools": [{"type": "function", "function": {"name": "demo", "parameters": {}}}],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": "demo"},
                },
            },
            "gemini-3.1-flash",
        )
        self.assertEqual(payload["model"], "gemini-3-flash-preview")
        self.assertEqual(payload["tool_choice"], "auto")

    def test_google_driver_builds_native_payload_from_canonical_without_unsupported_schema_keys(self) -> None:
        driver = GoogleDriver("google", "https://generativelanguage.googleapis.com/v1beta/openai")
        canonical = CanonicalRequest(
            protocol_in="anthropic",
            route=CanonicalRoute(
                kind="queue",
                requested_model="queue/gemini",
                provider="google",
                model_name="gemini-3.1-flash",
                queue_name="gemini",
                resolved_route="google/gemini-3-flash-preview",
            ),
            messages=[
                CanonicalMessage(
                    role="user",
                    content="call the tool",
                    blocks=[CanonicalContentBlock(type="text", text="call the tool")],
                )
            ],
            generation=CanonicalGeneration(tool_choice="required", max_tokens=256),
            tools=[
                CanonicalToolDefinition(
                    name="demo",
                    description="Demo tool",
                    parameters={
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer", "missing"],
                        "additionalProperties": False,
                    },
                )
            ],
        )

        payload = driver.build_native_payload(canonical, "gemini-3.1-flash")

        self.assertEqual(payload["model"], "gemini-3-flash-preview")
        self.assertEqual(payload["contents"][0]["role"], "user")
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 256)
        self.assertEqual(payload["toolConfig"]["functionCallingConfig"]["mode"], "ANY")
        parameters = payload["tools"][0]["functionDeclarations"][0]["parameters"]
        self.assertNotIn("additionalProperties", parameters)
        self.assertEqual(parameters["required"], ["answer"])

    def test_google_driver_renders_foreign_tool_history_as_text(self) -> None:
        driver = GoogleDriver("google", "https://generativelanguage.googleapis.com/v1beta/openai")
        canonical = CanonicalRequest(
            protocol_in="anthropic",
            route=CanonicalRoute(
                kind="queue",
                requested_model="queue/gemini",
                provider="google",
                model_name="gemini-3.1-flash-lite",
                queue_name="gemini",
                resolved_route="google/gemini-3.1-flash-lite",
            ),
            messages=[
                CanonicalMessage(
                    role="assistant",
                    content=None,
                    blocks=[
                        CanonicalContentBlock(
                            type="tool_use",
                            tool_use_id="call_1",
                            name="Bash",
                            tool_call=CanonicalToolCall(
                                id="call_1",
                                type="function",
                                function=CanonicalToolFunction(
                                    name="Bash",
                                    arguments={"command": "ls"},
                                ),
                            ),
                        )
                    ],
                ),
                CanonicalMessage(
                    role="user",
                    content=None,
                    blocks=[
                        CanonicalContentBlock(
                            type="tool_result",
                            tool_use_id="call_1",
                            tool_result={"content": "README.md"},
                        )
                    ],
                ),
            ],
            tools=[
                CanonicalToolDefinition(
                    name="Bash",
                    parameters={"type": "object", "properties": {"command": {"type": "string"}}},
                )
            ],
        )

        payload = driver.build_native_payload(canonical, "gemini-3.1-flash-lite")

        assistant_part = payload["contents"][0]["parts"][0]
        user_part = payload["contents"][1]["parts"][0]
        self.assertIn("Previous tool call: Bash", assistant_part["text"])
        self.assertIn("Previous tool result: Bash", user_part["text"])
        self.assertNotIn("functionCall", assistant_part)
        self.assertNotIn("functionResponse", user_part)
        self.assertEqual(payload["tools"][0]["functionDeclarations"][0]["name"], "Bash")

    def test_openai_driver_normalizes_legacy_functions_to_tools(self) -> None:
        driver = OpenAIDriver("openai", "https://api.openai.com/v1")
        payload = driver.build_payload(
            {
                "messages": [],
                "functions": [{"name": "legacy_demo", "parameters": {"type": "object"}}],
                "function_call": {"name": "legacy_demo"},
            },
            "gpt-4o-mini",
        )
        self.assertNotIn("functions", payload)
        self.assertNotIn("function_call", payload)
        self.assertIn("tools", payload)
        self.assertEqual(payload["tool_choice"]["function"]["name"], "legacy_demo")
        self.assertEqual(payload["tools"][0]["function"]["name"], "legacy_demo")

    def test_openai_compatible_driver_normalizes_ollama_style_response_to_openai_shape(self) -> None:
        driver = OpenAIDriver("openai", "https://api.openai.com/v1")
        response = driver.normalize_response_body(
            {
                "model": "gemma3",
                "created_at": "2026-06-08T00:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": "Hello from Ollama",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "demo",
                                "arguments": {"answer": "pong"},
                            },
                        }
                    ],
                },
                "done_reason": "tool_calls",
                "prompt_eval_count": 12,
                "eval_count": 8,
            },
            "gpt-4o-mini",
        )
        self.assertIsInstance(response, dict)
        self.assertEqual(response["object"], "chat.completion")
        self.assertEqual(response["choices"][0]["message"]["content"], "Hello from Ollama")
        self.assertEqual(response["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "demo")
        self.assertEqual(response["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(response["usage"]["prompt_tokens"], 12)
        self.assertEqual(response["usage"]["completion_tokens"], 8)
        self.assertEqual(response["usage"]["total_tokens"], 20)

    def test_openai_compatible_driver_normalizes_openai_stream_tool_calling_chunk(self) -> None:
        driver = OpenAIDriver("openai", "https://api.openai.com/v1")
        event = driver.normalize_stream_event(
            {
                "id": "chunk-1",
                "object": "chat.completion.chunk",
                "created": 1_719_000_000,
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": "ignored text",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "demo",
                                        "arguments": {"answer": "pong"},
                                    },
                                }
                            ],
                        },
                        "finish_reason": "function_call",
                    }
                ],
            },
            "gpt-4o-mini",
        )
        self.assertIsInstance(event, dict)
        self.assertEqual(event["object"], "chat.completion.chunk")
        self.assertEqual(event["choices"][0]["delta"]["role"], "assistant")
        self.assertEqual(event["choices"][0]["delta"]["content"], "ignored text")
        self.assertEqual(event["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"], "{\"answer\": \"pong\"}")
        self.assertEqual(event["choices"][0]["finish_reason"], "tool_calls")

    def test_openai_compatible_driver_normalizes_openai_stream_legacy_function_call_chunk(self) -> None:
        driver = OpenAIDriver("openai", "https://api.openai.com/v1")
        event = driver.normalize_stream_event(
            {
                "id": "chunk-2",
                "object": "chat.completion.chunk",
                "created": 1_719_000_000,
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": "ignored text",
                            "function_call": {
                                "name": "demo",
                                "arguments": {"answer": "pong"},
                            },
                        },
                        "finish_reason": "function_call",
                    }
                ],
            },
            "gpt-4o-mini",
        )
        self.assertIsInstance(event, dict)
        self.assertEqual(event["object"], "chat.completion.chunk")
        self.assertEqual(event["choices"][0]["delta"]["role"], "assistant")
        self.assertEqual(event["choices"][0]["delta"]["content"], "ignored text")
        self.assertEqual(event["choices"][0]["delta"]["tool_calls"][0]["function"]["name"], "demo")
        self.assertEqual(event["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"], "{\"answer\": \"pong\"}")
        self.assertEqual(event["choices"][0]["finish_reason"], "tool_calls")


if __name__ == "__main__":
    unittest.main()
