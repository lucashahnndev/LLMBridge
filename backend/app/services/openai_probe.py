from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.schemas.canonical import CanonicalRequest
from backend.app.services.canonical import canonical_request_to_chat_completion
from backend.app.services.proxy import build_provider_payload, resolve_route_driver_selection


@dataclass(slots=True)
class OpenAIProbeCandidate:
    gateway_provider: str
    adapter_provider: str
    route_model: str
    gateway_model_name: str
    adapter_model_name: str
    payload: dict[str, Any]


def load_trace(trace_path: str | Path) -> dict[str, Any]:
    return json.loads(Path(trace_path).read_text(encoding="utf-8"))


def _selected_route_model(trace: dict[str, Any], route_model: str | None = None) -> str:
    if route_model:
        return route_model
    route = trace.get("route")
    if isinstance(route, dict):
        selected_route = route.get("selected_route")
        if isinstance(selected_route, str) and selected_route.strip():
            return selected_route.strip()
        selected = route.get("selected")
        if isinstance(selected, dict):
            selected_provider = selected.get("provider")
            selected_model_name = selected.get("model_name")
            if (
                isinstance(selected_provider, str)
                and selected_provider.strip()
                and isinstance(selected_model_name, str)
                and selected_model_name.strip()
            ):
                return f"{selected_provider.strip()}/{selected_model_name.strip()}"
    canonical = trace.get("canonical")
    if isinstance(canonical, dict):
        request = canonical.get("request")
        if isinstance(request, dict):
            route_data = request.get("route")
            if isinstance(route_data, dict):
                requested_model = route_data.get("requested_model")
                if isinstance(requested_model, str) and requested_model.strip():
                    return requested_model.strip()
                provider = route_data.get("provider")
                model_name = route_data.get("model_name")
                if (
                    isinstance(provider, str)
                    and provider.strip()
                    and isinstance(model_name, str)
                    and model_name.strip()
                ):
                    return f"{provider.strip()}/{model_name.strip()}"
    raise ValueError("trace does not include a resolvable route model")


def build_openai_probe_candidates(
    trace: dict[str, Any],
    *,
    route_model: str | None = None,
) -> list[OpenAIProbeCandidate]:
    canonical_payload = trace.get("canonical", {}).get("request")
    if not isinstance(canonical_payload, dict):
        raise ValueError("trace does not contain canonical.request")

    canonical = CanonicalRequest.model_validate(canonical_payload)
    selected_route_model = _selected_route_model(trace, route_model)
    selection = resolve_route_driver_selection(selected_route_model)
    normalized = canonical_request_to_chat_completion(
        canonical,
        model_override=selection.resolved_route_model,
    ).model_dump(exclude_none=True, exclude={"model"})
    payload = build_provider_payload(
        adapter_driver=selection.adapter_driver,
        request_payload=normalized,
        adapter_model_name=selection.adapter_model_name,
        gateway_model_name=selection.gateway_model_name,
    )
    return [
        OpenAIProbeCandidate(
            gateway_provider=selection.gateway_provider,
            adapter_provider=selection.adapter_provider,
            route_model=selection.resolved_route_model,
            gateway_model_name=selection.gateway_model_name,
            adapter_model_name=selection.adapter_model_name,
            payload=payload,
        )
    ]
