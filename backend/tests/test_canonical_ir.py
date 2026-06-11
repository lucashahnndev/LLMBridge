import unittest

from backend.app.drivers import GoogleDriver, OpenAICompatibleDriver
from backend.app.schemas.anthropic import AnthropicMessagesRequest
from backend.app.schemas.proxy import ChatCompletionRequest
from backend.app.services.canonical import (
    anthropic_request_to_canonical,
    canonical_request_to_chat_completion,
    canonical_response_to_anthropic,
    chat_completion_body_to_canonical_response,
    openai_request_to_canonical,
)


class CanonicalIrTest(unittest.TestCase):
    def test_anthropic_request_to_canonical_preserves_tool_blocks(self) -> None:
        payload = AnthropicMessagesRequest(
            model="google/gemini-3.1-flash",
            max_tokens=256,
            system=[
                {"type": "text", "text": "You are concise."},
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Use the demo tool."},
                    ],
                },
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_1",
                            "name": "demo",
                            "input": {"answer": "pong"},
                        }
                    ],
                },
            ],
            tools=[
                {
                    "name": "demo",
                    "description": "Demo tool",
                    "input_schema": {
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                    },
                }
            ],
            metadata={"client": "claude-code"},
        )

        canonical = anthropic_request_to_canonical(payload)

        self.assertEqual(canonical.protocol_in, "anthropic")
        self.assertEqual(canonical.route.requested_model, "google/gemini-3.1-flash")
        self.assertEqual(canonical.system[0].type, "text")
        self.assertEqual(canonical.messages[1].blocks[0].type, "tool_use")
        self.assertEqual(canonical.messages[1].blocks[0].tool_call.function.name, "demo")
        self.assertEqual(canonical.tools[0].name, "demo")
        self.assertEqual(canonical.metadata["client"], "claude-code")

        chat_completion = canonical_request_to_chat_completion(canonical, model_override="google/gemini-3-flash-preview")
        self.assertEqual(chat_completion.model, "google/gemini-3-flash-preview")
        self.assertEqual(chat_completion.messages[0].role, "system")
        self.assertEqual(chat_completion.messages[1].role, "user")

    def test_openai_request_to_canonical_preserves_legacy_tool_fields(self) -> None:
        canonical = openai_request_to_canonical(
            ChatCompletionRequest(
                model="google/gemini-3.1-flash",
                messages=[
                    {
                        "role": "user",
                        "content": "Say hello.",
                    }
                ],
                functions=[
                    {
                        "name": "demo",
                        "description": "Demo tool",
                        "parameters": {
                            "type": "object",
                            "properties": {"answer": {"type": "string"}},
                        },
                    }
                ],
                function_call={"name": "demo"},
                metadata={"client": "playground"},
            ),
            provider="google",
            model_name="gemini-3-flash-preview",
            requested_model="google/gemini-3.1-flash",
        )

        self.assertEqual(canonical.protocol_in, "openai")
        self.assertEqual(canonical.route.provider, "google")
        self.assertEqual(canonical.route.model_name, "gemini-3-flash-preview")
        self.assertEqual(canonical.tools[0].name, "demo")
        self.assertEqual(canonical.generation.tool_choice["function"]["name"], "demo")
        self.assertEqual(canonical.metadata["client"], "playground")

    def test_google_and_ollama_responses_normalize_to_canonical_response(self) -> None:
        google_driver = GoogleDriver("google", "https://generativelanguage.googleapis.com/v1beta/openai")
        ollama_driver = OpenAICompatibleDriver("ollama", "http://localhost:11434/v1")

        google_native = {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {"text": "Thinking..."},
                            {
                                "functionCall": {
                                    "name": "demo",
                                    "args": {"answer": "pong"},
                                }
                            },
                        ],
                    },
                    "finishReason": "FUNCTION_CALL",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 12,
                "candidatesTokenCount": 8,
                "totalTokenCount": 20,
            },
        }

        ollama_native = {
            "model": "gemma3",
            "created_at": "2026-06-08T00:00:00Z",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_ollama_1",
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
        }

        google_normalized = google_driver.normalize_response_body(google_native, "gemini-3-flash-preview")
        ollama_normalized = ollama_driver.normalize_response_body(ollama_native, "gemma3")

        google_canonical = chat_completion_body_to_canonical_response(
            google_normalized,
            model_name="google/gemini-3-flash-preview",
        )
        ollama_canonical = chat_completion_body_to_canonical_response(
            ollama_normalized,
            model_name="gemma3",
        )

        self.assertEqual(google_canonical.model, "gemini-3-flash-preview")
        self.assertEqual(google_canonical.finish_reason, "tool_calls")
        self.assertEqual(google_canonical.tool_calls[0].function.name, "demo")
        self.assertEqual(google_canonical.usage.total_tokens, 20)

        self.assertEqual(ollama_canonical.model, "gemma3")
        self.assertEqual(ollama_canonical.finish_reason, "tool_calls")
        self.assertEqual(ollama_canonical.tool_calls[0].function.name, "demo")
        self.assertEqual(ollama_canonical.usage.input_tokens, 12)

        anthropic_google = canonical_response_to_anthropic(google_canonical)
        anthropic_ollama = canonical_response_to_anthropic(ollama_canonical)

        self.assertEqual(anthropic_google["stop_reason"], "tool_use")
        self.assertEqual(anthropic_google["content"][1]["type"], "tool_use")
        self.assertEqual(anthropic_ollama["content"][0]["type"], "tool_use")
        self.assertEqual(anthropic_ollama["usage"]["input_tokens"], 12)

    def test_canonical_text_response_maps_to_valid_anthropic_text_block(self) -> None:
        response = chat_completion_body_to_canonical_response(
            {
                "id": "chatcmpl-text-1",
                "object": "chat.completion",
                "created": 1_719_000_000,
                "model": "gemini-3-flash-preview",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Hello from canonical text.",
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
            model_name="google/gemini-3.1-flash",
            protocol_out="anthropic",
        )

        anthropic = canonical_response_to_anthropic(response)

        self.assertEqual(anthropic["content"][0]["type"], "text")
        self.assertEqual(anthropic["content"][0]["text"], "Hello from canonical text.")
        self.assertNotIn("content", anthropic["content"][0])


if __name__ == "__main__":
    unittest.main()
