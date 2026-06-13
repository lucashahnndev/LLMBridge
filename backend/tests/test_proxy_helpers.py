import unittest
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException

from backend.app.services.queues import ResolvedRouteCandidate
from backend.app.services.proxy import (
    determine_upstream_protocol,
    extract_usage_metrics,
    filter_chat_compatible_routes,
    format_provider_pool_exhausted_message,
    parse_model_identifier,
    parse_retry_after_seconds,
    resolve_route_driver_selection,
    route_supports_chat_completion,
)
from backend.app.services.records import derive_operational_route_parts


class ProxyHelperTest(unittest.TestCase):
    def test_parse_model_identifier_splits_provider_and_model(self) -> None:
        provider, model_name = parse_model_identifier("openai/gpt-4o-mini")
        self.assertEqual(provider, "openai")
        self.assertEqual(model_name, "gpt-4o-mini")

    def test_parse_model_identifier_preserves_nested_downstream_target(self) -> None:
        provider, model_name = parse_model_identifier("github/openai/gpt-4.1")
        self.assertEqual(provider, "github")
        self.assertEqual(model_name, "openai/gpt-4.1")

    def test_parse_model_identifier_rejects_invalid_format(self) -> None:
        with self.assertRaises(HTTPException):
            parse_model_identifier("gpt-4o-mini")

    def test_resolve_route_driver_selection_keeps_direct_provider_logic(self) -> None:
        selection = resolve_route_driver_selection("openai/gpt-4o-mini")
        self.assertEqual(selection.gateway_provider, "openai")
        self.assertEqual(selection.adapter_provider, "openai")
        self.assertEqual(selection.gateway_model_name, "gpt-4o-mini")
        self.assertEqual(selection.adapter_model_name, "gpt-4o-mini")
        self.assertEqual(selection.resolved_route_model, "openai/gpt-4o-mini")

    def test_resolve_route_driver_selection_uses_openai_adapter_for_github_subpath(self) -> None:
        selection = resolve_route_driver_selection("github/openai/gpt-4.1")
        self.assertEqual(selection.gateway_provider, "github")
        self.assertEqual(selection.adapter_provider, "openai")
        self.assertEqual(selection.gateway_model_name, "openai/gpt-4.1")
        self.assertEqual(selection.adapter_model_name, "gpt-4.1")
        self.assertEqual(selection.resolved_route_model, "github/openai/gpt-4.1")

    def test_resolve_route_driver_selection_uses_microsoft_adapter_for_github_subpath(self) -> None:
        selection = resolve_route_driver_selection("github/microsoft/phi-4")
        self.assertEqual(selection.gateway_provider, "github")
        self.assertEqual(selection.adapter_provider, "microsoft")
        self.assertEqual(selection.gateway_model_name, "microsoft/phi-4")
        self.assertEqual(selection.adapter_model_name, "phi-4")

    def test_determine_upstream_protocol_reports_google_native_when_applicable(self) -> None:
        self.assertEqual(
            determine_upstream_protocol(gateway_provider="google", use_google_native=True),
            "google",
        )

    def test_determine_upstream_protocol_reports_openai_for_brokered_routes(self) -> None:
        self.assertEqual(
            determine_upstream_protocol(gateway_provider="github", use_google_native=False),
            "openai",
        )

    def test_route_supports_chat_completion_rejects_embedding_models(self) -> None:
        self.assertFalse(route_supports_chat_completion("github/openai/text-embedding-3-small"))

    def test_filter_chat_compatible_routes_removes_embedding_candidates(self) -> None:
        routes = [
            ResolvedRouteCandidate(provider="github", model_name="openai/text-embedding-3-small"),
            ResolvedRouteCandidate(provider="github", model_name="openai/gpt-4.1"),
        ]

        filtered = filter_chat_compatible_routes(routes)

        self.assertEqual([route.route for route in filtered], ["github/openai/gpt-4.1"])

    def test_derive_operational_route_parts_for_direct_provider(self) -> None:
        route_parts = derive_operational_route_parts(
            provider_used="google",
            resolved_model="google/gemini-3-flash-preview",
        )
        self.assertEqual(route_parts["gateway_provider"], "google")
        self.assertEqual(route_parts["downstream_provider"], "google")
        self.assertEqual(route_parts["downstream_model_name"], "gemini-3-flash-preview")
        self.assertEqual(route_parts["operational_route"], "google/gemini-3-flash-preview")

    def test_derive_operational_route_parts_for_brokered_provider(self) -> None:
        route_parts = derive_operational_route_parts(
            provider_used="github",
            resolved_model="github/openai/gpt-4.1",
        )
        self.assertEqual(route_parts["gateway_provider"], "github")
        self.assertEqual(route_parts["downstream_provider"], "openai")
        self.assertEqual(route_parts["downstream_model_name"], "gpt-4.1")
        self.assertEqual(route_parts["operational_route"], "github/openai/gpt-4.1")

    def test_extract_usage_metrics_reads_usage_payload(self) -> None:
        prompt_tokens, completion_tokens, total_tokens = extract_usage_metrics(
            {
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 8,
                    "total_tokens": 20,
                }
            }
        )
        self.assertEqual((prompt_tokens, completion_tokens, total_tokens), (12, 8, 20))

    def test_extract_usage_metrics_defaults_when_usage_missing(self) -> None:
        self.assertEqual(extract_usage_metrics({}), (0, 0, 0))

    def test_format_provider_pool_exhausted_message_reports_cooldown(self) -> None:
        message = format_provider_pool_exhausted_message(
            "google",
            total=3,
            active=0,
            cooldown=3,
            invalid=0,
            next_retry_at=None,
        )
        self.assertIn("No eligible provider keys available", message)
        self.assertIn("total=3", message)

    def test_format_provider_pool_exhausted_message_reports_retry_time(self) -> None:
        from datetime import datetime, timezone

        message = format_provider_pool_exhausted_message(
            "google",
            total=3,
            active=0,
            cooldown=3,
            invalid=0,
            next_retry_at=datetime(2026, 6, 8, 3, 19, 17, tzinfo=timezone.utc),
        )
        self.assertIn("cooling down until", message)
        self.assertIn("2026-06-08T03:19:17+00:00", message)

    def test_parse_retry_after_seconds_reads_numeric_header(self) -> None:
        headers = httpx.Headers({"retry-after": "12"})
        self.assertEqual(parse_retry_after_seconds(headers), 12)

    def test_parse_retry_after_seconds_reads_http_date_header(self) -> None:
        now = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)
        headers = httpx.Headers({"retry-after": "Thu, 11 Jun 2026 12:00:05 GMT"})
        self.assertEqual(parse_retry_after_seconds(headers, now=now), 5)


if __name__ == "__main__":
    unittest.main()
