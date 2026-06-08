import unittest

from backend.app.drivers import GoogleDriver, OpenAIDriver, OpenRouterDriver, get_provider_driver


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
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertIn("tools", payload)
        self.assertEqual(payload["tools"][0]["function"]["name"], "demo")

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
        self.assertIsNone(response["choices"][0]["message"]["content"])
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
        self.assertIsNone(event["choices"][0]["delta"]["content"])
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
        self.assertIsNone(event["choices"][0]["delta"]["content"])
        self.assertEqual(event["choices"][0]["delta"]["tool_calls"][0]["function"]["name"], "demo")
        self.assertEqual(event["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"], "{\"answer\": \"pong\"}")
        self.assertEqual(event["choices"][0]["finish_reason"], "tool_calls")


if __name__ == "__main__":
    unittest.main()
