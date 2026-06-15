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
from backend.app.services.openai_probe import build_openai_probe_candidates, load_trace


class OpenAIProbeTest(unittest.TestCase):
    def test_probe_builds_github_openai_payload_from_anthropic_canonical(self) -> None:
        canonical = CanonicalRequest(
            protocol_in="anthropic",
            route=CanonicalRoute(
                kind="provider",
                requested_model="github/openai/gpt-4.1",
                provider="github",
                model_name="openai/gpt-4.1",
                resolved_route="github/openai/gpt-4.1",
            ),
            system=[CanonicalContentBlock(type="text", text="You are concise.")],
            messages=[
                CanonicalMessage(
                    role="user",
                    content="Use the demo tool.",
                    blocks=[CanonicalContentBlock(type="text", text="Use the demo tool.")],
                )
            ],
            tools=[
                CanonicalToolDefinition(
                    name="demo",
                    description="Demo tool",
                    parameters={
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                    },
                )
            ],
            generation=CanonicalGeneration(
                stream=True,
                tool_choice={"type": "function", "function": {"name": "demo"}},
                response_format={"type": "json_schema", "json_schema": {"name": "demo_response"}},
                parallel_tool_calls=False,
            ),
            metadata={"client": "claude-code"},
        )
        trace = {
            "canonical": {"request": canonical.model_dump(mode="json")},
            "route": {"selected_route": "github/openai/gpt-4.1"},
        }

        candidates = build_openai_probe_candidates(trace)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.gateway_provider, "github")
        self.assertEqual(candidate.adapter_provider, "openai")
        self.assertEqual(candidate.route_model, "github/openai/gpt-4.1")
        self.assertEqual(candidate.gateway_model_name, "openai/gpt-4.1")
        self.assertEqual(candidate.adapter_model_name, "gpt-4.1")
        self.assertEqual(candidate.payload["model"], "openai/gpt-4.1")
        self.assertNotIn("metadata", candidate.payload)
        self.assertEqual(candidate.payload["parallel_tool_calls"], False)
        self.assertEqual(candidate.payload["tool_choice"]["function"]["name"], "demo")
        self.assertEqual(candidate.payload["response_format"]["type"], "json_schema")
        self.assertEqual(candidate.payload["tools"][0]["function"]["name"], "demo")
        self.assertEqual(candidate.payload["messages"][0]["role"], "system")
        self.assertEqual(candidate.payload["messages"][1]["role"], "user")

    def test_probe_uses_second_path_to_select_generic_openai_compatible_adapter(self) -> None:
        canonical = CanonicalRequest(
            protocol_in="anthropic",
            route=CanonicalRoute(
                kind="provider",
                requested_model="github/microsoft/phi-4",
                provider="github",
                model_name="microsoft/phi-4",
                resolved_route="github/microsoft/phi-4",
            ),
            messages=[
                CanonicalMessage(
                    role="user",
                    content="Say hello.",
                    blocks=[CanonicalContentBlock(type="text", text="Say hello.")],
                )
            ],
        )
        trace = {
            "canonical": {"request": canonical.model_dump(mode="json")},
            "route": {"selected_route": "github/microsoft/phi-4"},
        }

        candidates = build_openai_probe_candidates(trace)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.gateway_provider, "github")
        self.assertEqual(candidate.adapter_provider, "microsoft")
        self.assertEqual(candidate.gateway_model_name, "microsoft/phi-4")
        self.assertEqual(candidate.adapter_model_name, "phi-4")
        self.assertEqual(candidate.payload["model"], "microsoft/phi-4")

    def test_probe_builds_openrouter_meta_payload_from_anthropic_canonical(self) -> None:
        canonical = CanonicalRequest(
            protocol_in="anthropic",
            route=CanonicalRoute(
                kind="provider",
                requested_model="openrouter/meta/llama-3.3-70b-instruct",
                provider="openrouter",
                model_name="meta/llama-3.3-70b-instruct",
                resolved_route="openrouter/meta/llama-3.3-70b-instruct",
            ),
            system=[CanonicalContentBlock(type="text", text="You are concise.")],
            messages=[
                CanonicalMessage(
                    role="user",
                    content="Say hello.",
                    blocks=[CanonicalContentBlock(type="text", text="Say hello.")],
                )
            ],
            tools=[
                CanonicalToolDefinition(
                    name="demo",
                    description="Demo tool",
                    parameters={
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                    },
                )
            ],
            generation=CanonicalGeneration(
                tool_choice={"type": "function", "function": {"name": "demo"}},
                parallel_tool_calls=False,
            ),
        )
        trace = {
            "canonical": {"request": canonical.model_dump(mode="json")},
            "route": {"selected_route": "openrouter/meta/llama-3.3-70b-instruct"},
        }

        candidates = build_openai_probe_candidates(trace)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.gateway_provider, "openrouter")
        self.assertEqual(candidate.adapter_provider, "meta")
        self.assertEqual(candidate.route_model, "openrouter/meta/llama-3.3-70b-instruct")
        self.assertEqual(candidate.gateway_model_name, "meta/llama-3.3-70b-instruct")
        self.assertEqual(candidate.adapter_model_name, "llama-3.3-70b-instruct")
        self.assertEqual(candidate.payload["model"], "meta/llama-3.3-70b-instruct")
        self.assertEqual(candidate.payload["tool_choice"], "required")

    def test_probe_normalizes_openrouter_meta_llama_alias_to_meta_adapter(self) -> None:
        canonical = CanonicalRequest(
            protocol_in="anthropic",
            route=CanonicalRoute(
                kind="provider",
                requested_model="openrouter/meta-llama/llama-3.3-70b-instruct:free",
                provider="openrouter",
                model_name="meta-llama/llama-3.3-70b-instruct:free",
                resolved_route="openrouter/meta-llama/llama-3.3-70b-instruct:free",
            ),
            messages=[
                CanonicalMessage(
                    role="user",
                    content="Say hello.",
                    blocks=[CanonicalContentBlock(type="text", text="Say hello.")],
                )
            ],
            generation=CanonicalGeneration(
                tool_choice={"type": "function", "function": {"name": "demo"}},
            ),
        )
        trace = {
            "canonical": {"request": canonical.model_dump(mode="json")},
            "route": {"selected_route": "openrouter/meta-llama/llama-3.3-70b-instruct:free"},
        }

        candidates = build_openai_probe_candidates(trace)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.gateway_provider, "openrouter")
        self.assertEqual(candidate.adapter_provider, "meta")
        self.assertEqual(candidate.gateway_model_name, "meta-llama/llama-3.3-70b-instruct:free")
        self.assertEqual(candidate.adapter_model_name, "llama-3.3-70b-instruct:free")
        self.assertEqual(candidate.payload["model"], "meta-llama/llama-3.3-70b-instruct:free")
        self.assertEqual(candidate.payload["tool_choice"], "required")

    def test_load_trace_reads_json_file(self) -> None:
        traces_dir = Path(__file__).resolve().parents[2] / "traces"
        trace_path = next(traces_dir.glob("*.json"))
        trace = load_trace(trace_path)
        self.assertIsInstance(trace["client"]["raw_body"]["model"], str)


if __name__ == "__main__":
    unittest.main()
