import json
import unittest
from pathlib import Path

from backend.app.schemas.canonical import (
    CanonicalContentBlock,
    CanonicalGeneration,
    CanonicalMessage,
    CanonicalRequest,
    CanonicalRoute,
    CanonicalToolDefinition,
)
from backend.app.services.gemini_probe import build_google_probe_candidates


class GeminiProbeTest(unittest.TestCase):
    def test_trace_replay_does_not_reemit_gemini_thought_signatures(self) -> None:
        trace_path = Path(__file__).resolve().parents[2] / "traces" / "00adc1281fb5.json"
        trace = json.loads(trace_path.read_text(encoding="utf-8"))

        candidates = build_google_probe_candidates(
            trace,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            strategy="auto",
            transport="native",
        )

        for candidate in candidates:
            payload_text = json.dumps(candidate.payload, ensure_ascii=False)
            self.assertNotIn("thoughtSignature", payload_text)
            self.assertNotIn("thought_signature", payload_text)
            self.assertNotIn("functionCall", payload_text)
            self.assertNotIn("functionResponse", payload_text)

    def test_probe_builds_multiple_sanitization_candidates_from_trace(self) -> None:
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
                    role="user",
                    content="hello",
                    blocks=[CanonicalContentBlock(type="text", text="hello")],
                )
            ],
            generation=CanonicalGeneration(stream=True),
            tools=[
                CanonicalToolDefinition(
                    name="demo",
                    description="Demo tool",
                    parameters={
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "type": "object",
                        "definitions": {"nested": {"type": "string"}},
                        "oneOf": [{"type": "string"}],
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                    },
                )
            ],
        )
        trace = {
            "canonical": {"request": canonical.model_dump(mode="json")},
            "route": {"selected": {"model_name": "gemini-3.1-flash-lite"}},
        }

        candidates = build_google_probe_candidates(
            trace,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            strategy="auto",
        )

        self.assertEqual(
            [candidate.strategy for candidate in candidates],
            ["baseline", "strict-schema", "drop-parameterless", "drop-parameterless-strict"],
        )
        self.assertEqual(candidates[0].model_name, "gemini-3.1-flash-lite")
        self.assertIn("tools", candidates[0].payload)
        baseline_params = candidates[0].payload["tools"][0]["function"]["parameters"]
        strict_params = candidates[1].payload["tools"][0]["function"]["parameters"]
        self.assertNotIn("$schema", baseline_params)
        self.assertIn("definitions", baseline_params)
        self.assertIn("oneOf", baseline_params)
        self.assertNotIn("definitions", strict_params)
        self.assertNotIn("oneOf", strict_params)
        self.assertEqual(strict_params["type"], "object")

    def test_drop_parameterless_strategy_removes_empty_tools(self) -> None:
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
                    role="user",
                    content="hello",
                    blocks=[CanonicalContentBlock(type="text", text="hello")],
                )
            ],
            generation=CanonicalGeneration(stream=True),
            tools=[
                CanonicalToolDefinition(
                    name="empty_tool",
                    description="No args",
                    parameters={
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                ),
                CanonicalToolDefinition(
                    name="with_args",
                    description="Has args",
                    parameters={
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                        "additionalProperties": False,
                    },
                ),
            ],
        )
        trace = {
            "canonical": {"request": canonical.model_dump(mode="json")},
            "route": {"selected": {"model_name": "gemini-3.1-flash-lite"}},
        }

        candidates = build_google_probe_candidates(
            trace,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            strategy="drop-parameterless",
        )

        tool_names = [
            tool["function"]["name"]
            for tool in candidates[0].payload.get("tools", [])
            if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
        ]
        self.assertNotIn("empty_tool", tool_names)
        self.assertIn("with_args", tool_names)

    def test_native_strategy_strips_google_unsupported_schema_keys(self) -> None:
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
                    role="user",
                    content="hello",
                    blocks=[CanonicalContentBlock(type="text", text="hello")],
                )
            ],
            generation=CanonicalGeneration(stream=True),
            tools=[
                CanonicalToolDefinition(
                    name="demo",
                    description="Demo tool",
                    parameters={
                        "type": "object",
                        "properties": {
                            "answer": {"type": "string"},
                        },
                        "required": ["answer", "missing"],
                        "additionalProperties": False,
                    },
                )
            ],
        )
        trace = {
            "canonical": {"request": canonical.model_dump(mode="json")},
            "route": {"selected": {"model_name": "gemini-3.1-flash-lite"}},
        }

        candidates = build_google_probe_candidates(
            trace,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            strategy="strict-schema",
            transport="native",
        )

        self.assertEqual(len(candidates), 1)
        parameters = candidates[0].payload["tools"][0]["functionDeclarations"][0]["parameters"]
        self.assertNotIn("additionalProperties", parameters)
        self.assertEqual(parameters["required"], ["answer"])


if __name__ == "__main__":
    unittest.main()
