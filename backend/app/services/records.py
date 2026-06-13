from datetime import datetime, timezone

from backend.app.database.models import AppToken, ModelQueue, ModelQueueCandidate, ProviderKey, UsageLog
from backend.app.schemas.app_tokens import AppTokenCreateResponse, AppTokenResponse
from backend.app.schemas.model_queues import ModelQueueCandidateResponse, ModelQueueResponse
from backend.app.schemas.provider_keys import ProviderKeyResponse
from backend.app.schemas.usage_logs import UsageLogResponse
from backend.app.services.crypto import decrypt_text
from backend.app.services.tokens import mask_secret


def derive_operational_route_parts(
    *,
    provider_used: str | None,
    resolved_model: str | None,
    model_requested: str | None = None,
) -> dict[str, str | None]:
    gateway_provider = provider_used.strip() if isinstance(provider_used, str) and provider_used.strip() else None
    operational_route = None
    if isinstance(resolved_model, str) and resolved_model.strip():
        operational_route = resolved_model.strip()
    elif isinstance(model_requested, str) and "/" in model_requested and not model_requested.startswith("queue/"):
        operational_route = model_requested.strip()

    downstream_provider = gateway_provider
    downstream_model_name = None
    if operational_route and "/" in operational_route:
        route_gateway, remainder = operational_route.split("/", 1)
        if not gateway_provider:
            gateway_provider = route_gateway.strip() or gateway_provider
        if gateway_provider and remainder and "/" in remainder:
            downstream_provider, downstream_model_name = remainder.split("/", 1)
        else:
            downstream_provider = gateway_provider
            downstream_model_name = remainder

    return {
        "gateway_provider": gateway_provider,
        "downstream_provider": downstream_provider.strip() if isinstance(downstream_provider, str) and downstream_provider.strip() else None,
        "downstream_model_name": downstream_model_name.strip() if isinstance(downstream_model_name, str) and downstream_model_name.strip() else None,
        "operational_route": operational_route,
    }


def ensure_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def provider_key_response(provider_key: ProviderKey) -> ProviderKeyResponse:
    token = decrypt_text(provider_key.encrypted_token)
    return ProviderKeyResponse.model_validate(
        {
            "id": provider_key.id,
            "name": provider_key.name,
            "description": provider_key.description,
            "provider": provider_key.provider,
            "status": provider_key.status.value,
            "blocked_until": ensure_utc_datetime(provider_key.blocked_until),
            "failure_count": provider_key.failure_count,
            "created_at": ensure_utc_datetime(provider_key.created_at),
            "updated_at": ensure_utc_datetime(provider_key.updated_at),
            "masked_token": mask_secret(token),
        }
    )


def app_token_response(app_token: AppToken) -> AppTokenResponse:
    return AppTokenResponse.model_validate(
        {
            "id": app_token.id,
            "name": app_token.name,
            "environment": app_token.environment.value,
            "is_active": app_token.is_active,
            "rpm_limit": app_token.rpm_limit,
            "created_at": ensure_utc_datetime(app_token.created_at),
            "masked_token": mask_secret(app_token.token),
        }
    )


def app_token_create_response(app_token: AppToken, token: str) -> AppTokenCreateResponse:
    payload = app_token_response(app_token).model_dump()
    return AppTokenCreateResponse.model_validate(
        {
            **payload,
            "token": token,
        }
    )


def usage_log_response(usage_log: UsageLog) -> UsageLogResponse:
    route_parts = derive_operational_route_parts(
        provider_used=usage_log.provider_used,
        resolved_model=usage_log.resolved_model,
        model_requested=usage_log.model_requested,
    )
    return UsageLogResponse.model_validate(
        {
            "id": usage_log.id,
            "app_token_id": usage_log.app_token_id,
            "app_token_name": usage_log.app_token.name if usage_log.app_token else None,
            "provider_key_id": usage_log.provider_key_id,
            "provider_key_name": usage_log.provider_key.name if usage_log.provider_key else None,
            "protocol_in": usage_log.protocol_in,
            "protocol_out": usage_log.protocol_out,
            "upstream_protocol": usage_log.upstream_protocol,
            "route_kind": usage_log.route_kind,
            "queue_name": usage_log.queue_name,
            "model_requested": usage_log.model_requested,
            "provider_used": usage_log.provider_used,
            "resolved_model": usage_log.resolved_model,
            "gateway_provider": route_parts["gateway_provider"],
            "downstream_provider": route_parts["downstream_provider"],
            "downstream_model_name": route_parts["downstream_model_name"],
            "operational_route": route_parts["operational_route"],
            "prompt_tokens": usage_log.prompt_tokens,
            "completion_tokens": usage_log.completion_tokens,
            "total_tokens": usage_log.total_tokens,
            "latency_ms": usage_log.latency_ms,
            "status_code": usage_log.status_code,
            "was_rotated": usage_log.was_rotated,
            "tool_calling": usage_log.tool_calling,
            "error_message": usage_log.error_message,
            "created_at": ensure_utc_datetime(usage_log.created_at),
        }
    )


def model_queue_candidate_response(candidate: ModelQueueCandidate) -> ModelQueueCandidateResponse:
    return ModelQueueCandidateResponse.model_validate(
        {
            "id": candidate.id,
            "queue_id": candidate.queue_id,
            "provider": candidate.provider,
            "model_name": candidate.model_name,
            "position": candidate.position,
            "is_active": candidate.is_active,
            "base_degradation": candidate.base_degradation,
            "latency_score": candidate.latency_score,
            "error_score": candidate.error_score,
            "final_rank": candidate.final_rank,
            "score": candidate.score,
            "failure_count": candidate.failure_count,
            "success_count": candidate.success_count,
            "avg_latency_ms": candidate.avg_latency_ms,
            "last_used_at": ensure_utc_datetime(candidate.last_used_at),
            "last_error_at": ensure_utc_datetime(candidate.last_error_at),
            "last_success_at": ensure_utc_datetime(candidate.last_success_at),
            "created_at": ensure_utc_datetime(candidate.created_at),
            "updated_at": ensure_utc_datetime(candidate.updated_at),
        }
    )


def model_queue_response(queue: ModelQueue) -> ModelQueueResponse:
    return ModelQueueResponse.model_validate(
        {
            "id": queue.id,
            "name": queue.name,
            "description": queue.description,
            "strategy": queue.strategy.value,
            "is_active": queue.is_active,
            "created_at": ensure_utc_datetime(queue.created_at),
            "updated_at": ensure_utc_datetime(queue.updated_at),
            "candidates": [model_queue_candidate_response(candidate).model_dump() for candidate in sorted(queue.candidates, key=lambda candidate: (candidate.position, candidate.id))],
        }
    )
