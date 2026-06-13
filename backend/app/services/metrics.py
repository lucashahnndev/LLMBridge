from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database.models import AppToken, KeyStatus, ModelQueue, ProviderKey, UsageLog
from backend.app.schemas.metrics import (
    GlobalMetricsResponse,
    MetricsTimeseriesBucketResponse,
    MetricsTimeseriesResponse,
    MetricsModelUsageResponse,
    MetricsOverviewTelemetryResponse,
    MetricsOverviewResponse,
    MetricsOverviewSummaryResponse,
    ProjectMetricsResponse,
)
from backend.app.services.records import derive_operational_route_parts


def resolve_usage_window_filter(window: str) -> tuple[datetime, datetime]:
    lookback, _ = resolve_metrics_window(window)
    now = datetime.now(timezone.utc)
    start = now - lookback
    return start, now


async def build_global_metrics(session: AsyncSession, window: str = "24h") -> GlobalMetricsResponse:
    start, now = resolve_usage_window_filter(window)

    total_requests_stmt = select(func.count(UsageLog.id)).where(
        UsageLog.created_at >= start,
        UsageLog.created_at <= now,
    )
    success_count_stmt = select(func.count(UsageLog.id)).where(
        UsageLog.status_code >= 200,
        UsageLog.status_code < 300,
        UsageLog.created_at >= start,
        UsageLog.created_at <= now,
    )
    avg_latency_stmt = select(func.coalesce(func.avg(UsageLog.latency_ms), 0.0)).where(
        UsageLog.created_at >= start,
        UsageLog.created_at <= now,
    )
    total_tokens_stmt = select(func.coalesce(func.sum(UsageLog.total_tokens), 0)).where(
        UsageLog.created_at >= start,
        UsageLog.created_at <= now,
    )
    active_keys_stmt = select(func.count(ProviderKey.id)).where(ProviderKey.status == KeyStatus.ACTIVE)
    cooldown_keys_stmt = select(func.count(ProviderKey.id)).where(ProviderKey.status == KeyStatus.COOLDOWN)
    rotated_stmt = select(func.coalesce(func.sum(case((UsageLog.was_rotated.is_(True), 1), else_=0)), 0)).where(
        UsageLog.created_at >= start,
        UsageLog.created_at <= now,
    )

    total_requests = int((await session.execute(total_requests_stmt)).scalar_one())
    success_count = int((await session.execute(success_count_stmt)).scalar_one())
    avg_latency_ms = float((await session.execute(avg_latency_stmt)).scalar_one())
    total_tokens = int((await session.execute(total_tokens_stmt)).scalar_one())
    active_keys_count = int((await session.execute(active_keys_stmt)).scalar_one())
    cooldown_keys_count = int((await session.execute(cooldown_keys_stmt)).scalar_one())
    total_rotations_triggered = int((await session.execute(rotated_stmt)).scalar_one())

    success_rate = (success_count / total_requests * 100.0) if total_requests else 0.0

    return GlobalMetricsResponse(
        total_requests=total_requests,
        success_rate=success_rate,
        avg_latency_ms=avg_latency_ms,
        total_tokens_consumed=total_tokens,
        active_keys_count=active_keys_count,
        cooldown_keys_count=cooldown_keys_count,
        total_rotations_triggered=total_rotations_triggered,
    )


async def build_project_metrics(session: AsyncSession, window: str = "24h") -> list[ProjectMetricsResponse]:
    start, now = resolve_usage_window_filter(window)
    stmt = (
        select(
            AppToken.id,
            AppToken.name,
            AppToken.environment,
            func.count(UsageLog.id).label("requests_count"),
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("total_tokens_consumed"),
            func.coalesce(func.avg(UsageLog.latency_ms), 0.0).label("avg_latency_ms"),
        )
        .select_from(AppToken)
        .outerjoin(
            UsageLog,
            (UsageLog.app_token_id == AppToken.id) & (UsageLog.created_at >= start) & (UsageLog.created_at <= now),
        )
        .group_by(AppToken.id, AppToken.name, AppToken.environment)
        .order_by(func.count(UsageLog.id).desc(), AppToken.id.desc())
    )
    result = await session.execute(stmt)
    rows = result.all()
    return [
        ProjectMetricsResponse(
            app_token_id=row.id,
            app_name=row.name,
            environment=row.environment.value,
            requests_count=int(row.requests_count or 0),
            total_tokens_consumed=int(row.total_tokens_consumed or 0),
            avg_latency_ms=float(row.avg_latency_ms or 0.0),
        )
        for row in rows
    ]


def resolve_metrics_window(window: str) -> tuple[timedelta, str]:
    if window == "1h":
        return timedelta(hours=1), "minute"
    if window == "24h":
        return timedelta(hours=24), "hour"
    if window == "7d":
        return timedelta(days=7), "day"
    if window == "30d":
        return timedelta(days=30), "day"
    raise ValueError(f"Unsupported metrics window: {window}")


def align_bucket_start(value: datetime, granularity: str) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    if granularity == "minute":
        return value.replace(second=0, microsecond=0)
    if granularity == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    if granularity == "day":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"Unsupported granularity: {granularity}")


def bucket_end_for(start: datetime, granularity: str) -> datetime:
    if granularity == "minute":
        return start + timedelta(minutes=1)
    if granularity == "hour":
        return start + timedelta(hours=1)
    if granularity == "day":
        return start + timedelta(days=1)
    raise ValueError(f"Unsupported granularity: {granularity}")


def build_overview_summary_response(
    total_requests: int,
    success_count: int,
    avg_latency_ms: float,
    total_tokens_consumed: int,
    total_rotations_triggered: int,
) -> MetricsOverviewSummaryResponse:
    success_rate = (success_count / total_requests * 100.0) if total_requests else 0.0
    return MetricsOverviewSummaryResponse(
        total_requests=total_requests,
        success_rate=success_rate,
        avg_latency_ms=avg_latency_ms,
        total_tokens_consumed=total_tokens_consumed,
        total_rotations_triggered=total_rotations_triggered,
    )


async def build_timeseries_metrics(session: AsyncSession, window: str) -> MetricsTimeseriesResponse:
    lookback, granularity = resolve_metrics_window(window)
    now = datetime.now(timezone.utc)
    start = now - lookback
    stmt = (
        select(UsageLog.created_at, UsageLog.status_code, UsageLog.total_tokens, UsageLog.latency_ms, UsageLog.was_rotated)
        .where(UsageLog.created_at >= start)
        .where(UsageLog.created_at <= now)
        .order_by(UsageLog.created_at.asc())
    )
    result = await session.execute(stmt)

    buckets: OrderedDict[datetime, dict[str, float | int]] = OrderedDict()
    for created_at, status_code, total_tokens, latency_ms, was_rotated in result.all():
        if created_at is None:
            continue
        bucket_start = align_bucket_start(created_at, granularity)
        bucket = buckets.setdefault(
            bucket_start,
            {
                "requests_count": 0,
                "success_count": 0,
                "error_count": 0,
                "total_tokens_consumed": 0,
                "latency_total": 0.0,
                "latency_samples": 0,
                "total_rotations_triggered": 0,
            },
        )
        bucket["requests_count"] = int(bucket["requests_count"]) + 1
        if 200 <= status_code < 300:
            bucket["success_count"] = int(bucket["success_count"]) + 1
        else:
            bucket["error_count"] = int(bucket["error_count"]) + 1
        bucket["total_tokens_consumed"] = int(bucket["total_tokens_consumed"]) + int(total_tokens or 0)
        bucket["latency_total"] = float(bucket["latency_total"]) + float(latency_ms or 0.0)
        bucket["latency_samples"] = int(bucket["latency_samples"]) + 1
        if was_rotated:
            bucket["total_rotations_triggered"] = int(bucket["total_rotations_triggered"]) + 1

    timeline_start = align_bucket_start(start, granularity)
    timeline_end = align_bucket_start(now, granularity)
    cursor = timeline_start
    bucket_rows: list[MetricsTimeseriesBucketResponse] = []
    while cursor <= timeline_end:
        bucket = buckets.get(cursor)
        if bucket is None:
            bucket_rows.append(
                MetricsTimeseriesBucketResponse(
                    bucket_start=cursor.isoformat(),
                    bucket_end=bucket_end_for(cursor, granularity).isoformat(),
                )
            )
        else:
            latency_samples = int(bucket["latency_samples"])
            bucket_rows.append(
                MetricsTimeseriesBucketResponse(
                    bucket_start=cursor.isoformat(),
                    bucket_end=bucket_end_for(cursor, granularity).isoformat(),
                    requests_count=int(bucket["requests_count"]),
                    success_count=int(bucket["success_count"]),
                    error_count=int(bucket["error_count"]),
                    total_tokens_consumed=int(bucket["total_tokens_consumed"]),
                    avg_latency_ms=(float(bucket["latency_total"]) / latency_samples) if latency_samples else 0.0,
                    total_rotations_triggered=int(bucket["total_rotations_triggered"]),
                )
            )

        cursor = bucket_end_for(cursor, granularity)

    return MetricsTimeseriesResponse(window=window, granularity=granularity, buckets=bucket_rows)


async def _build_overview_response(
    session: AsyncSession,
    *,
    window: str,
    context_type: str,
    context_label: str,
    filters: list,
    context_id: int | None = None,
) -> MetricsOverviewResponse:
    lookback, granularity = resolve_metrics_window(window)
    now = datetime.now(timezone.utc)
    start = now - lookback

    base_stmt = (
        select(
            UsageLog.created_at,
            UsageLog.status_code,
            UsageLog.total_tokens,
            UsageLog.latency_ms,
            UsageLog.was_rotated,
            UsageLog.protocol_in,
            UsageLog.protocol_out,
            UsageLog.upstream_protocol,
            UsageLog.route_kind,
            UsageLog.tool_calling,
        )
        .where(UsageLog.created_at >= start)
        .where(UsageLog.created_at <= now)
    )
    for clause in filters:
        base_stmt = base_stmt.where(clause)
    base_stmt = base_stmt.order_by(UsageLog.created_at.asc())
    result = await session.execute(base_stmt)

    buckets: OrderedDict[datetime, dict[str, float | int]] = OrderedDict()
    total_requests = 0
    success_count = 0
    total_tokens_consumed = 0
    latency_total = 0.0
    latency_samples = 0
    total_rotations_triggered = 0
    protocol_in_counts: OrderedDict[str, int] = OrderedDict()
    protocol_out_counts: OrderedDict[str, int] = OrderedDict()
    upstream_protocol_counts: OrderedDict[str, int] = OrderedDict()
    route_kind_counts: OrderedDict[str, int] = OrderedDict()
    tool_calling_count = 0

    for created_at, status_code, total_tokens, latency_ms, was_rotated, protocol_in, protocol_out, upstream_protocol, route_kind, tool_calling in result.all():
        if created_at is None:
            continue
        bucket_start = align_bucket_start(created_at, granularity)
        bucket = buckets.setdefault(
            bucket_start,
            {
                "requests_count": 0,
                "success_count": 0,
                "error_count": 0,
                "total_tokens_consumed": 0,
                "latency_total": 0.0,
                "latency_samples": 0,
                "total_rotations_triggered": 0,
            },
        )
        total_requests += 1
        if 200 <= status_code < 300:
            success_count += 1
            bucket["success_count"] = int(bucket["success_count"]) + 1
        else:
            bucket["error_count"] = int(bucket["error_count"]) + 1
        total_tokens_consumed += int(total_tokens or 0)
        latency_value = float(latency_ms or 0.0)
        latency_total += latency_value
        latency_samples += 1
        bucket["requests_count"] = int(bucket["requests_count"]) + 1
        bucket["total_tokens_consumed"] = int(bucket["total_tokens_consumed"]) + int(total_tokens or 0)
        bucket["latency_total"] = float(bucket["latency_total"]) + latency_value
        bucket["latency_samples"] = int(bucket["latency_samples"]) + 1
        if was_rotated:
            total_rotations_triggered += 1
            bucket["total_rotations_triggered"] = int(bucket["total_rotations_triggered"]) + 1
        protocol_in_counts[protocol_in] = protocol_in_counts.get(protocol_in, 0) + 1
        protocol_out_counts[protocol_out] = protocol_out_counts.get(protocol_out, 0) + 1
        upstream_protocol_counts[upstream_protocol] = upstream_protocol_counts.get(upstream_protocol, 0) + 1
        route_kind_counts[route_kind] = route_kind_counts.get(route_kind, 0) + 1
        if tool_calling:
            tool_calling_count += 1

    timeline_start = align_bucket_start(start, granularity)
    timeline_end = align_bucket_start(now, granularity)
    cursor = timeline_start
    bucket_rows: list[MetricsTimeseriesBucketResponse] = []
    while cursor <= timeline_end:
        bucket = buckets.get(cursor)
        if bucket is None:
            bucket_rows.append(
                MetricsTimeseriesBucketResponse(
                    bucket_start=cursor.isoformat(),
                    bucket_end=bucket_end_for(cursor, granularity).isoformat(),
                )
            )
        else:
            samples = int(bucket["latency_samples"])
            bucket_rows.append(
                MetricsTimeseriesBucketResponse(
                    bucket_start=cursor.isoformat(),
                    bucket_end=bucket_end_for(cursor, granularity).isoformat(),
                    requests_count=int(bucket["requests_count"]),
                    success_count=int(bucket["success_count"]),
                    error_count=int(bucket["error_count"]),
                    total_tokens_consumed=int(bucket["total_tokens_consumed"]),
                    avg_latency_ms=(float(bucket["latency_total"]) / samples) if samples else 0.0,
                    total_rotations_triggered=int(bucket["total_rotations_triggered"]),
                )
            )
        cursor = bucket_end_for(cursor, granularity)

    models_stmt = (
        select(
            func.coalesce(UsageLog.resolved_model, UsageLog.model_requested).label("model_name"),
            func.count(UsageLog.id).label("requests_count"),
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("total_tokens_consumed"),
            func.coalesce(func.avg(UsageLog.latency_ms), 0.0).label("avg_latency_ms"),
            func.coalesce(func.sum(case((UsageLog.status_code >= 200, 1), else_=0)), 0).label("success_count"),
            func.coalesce(func.sum(case((UsageLog.was_rotated.is_(True), 1), else_=0)), 0).label("total_rotations_triggered"),
        )
        .select_from(UsageLog)
    )
    for clause in filters:
        models_stmt = models_stmt.where(clause)
    models_stmt = models_stmt.group_by(func.coalesce(UsageLog.resolved_model, UsageLog.model_requested)).order_by(func.count(UsageLog.id).desc(), func.coalesce(func.sum(UsageLog.total_tokens), 0).desc())
    models_result = await session.execute(models_stmt)
    model_rows = models_result.all()
    models = [
        MetricsModelUsageResponse(
            model_name=row.model_name,
            gateway_provider=route_parts["gateway_provider"],
            downstream_provider=route_parts["downstream_provider"],
            downstream_model_name=route_parts["downstream_model_name"],
            operational_route=route_parts["operational_route"],
            requests_count=int(row.requests_count or 0),
            success_count=int(row.success_count or 0),
            error_count=max(0, int(row.requests_count or 0) - int(row.success_count or 0)),
            total_tokens_consumed=int(row.total_tokens_consumed or 0),
            avg_latency_ms=float(row.avg_latency_ms or 0.0),
            total_rotations_triggered=int(row.total_rotations_triggered or 0),
        )
        for row in model_rows
        for route_parts in [
            derive_operational_route_parts(
                provider_used=row.model_name.split("/", 1)[0] if isinstance(row.model_name, str) and "/" in row.model_name else None,
                resolved_model=row.model_name,
            )
        ]
    ]

    return MetricsOverviewResponse(
        context_type=context_type,
        context_id=context_id,
        context_label=context_label,
        window=window,
        granularity=granularity,
        summary=build_overview_summary_response(
            total_requests=total_requests,
            success_count=success_count,
            avg_latency_ms=(latency_total / latency_samples) if latency_samples else 0.0,
            total_tokens_consumed=total_tokens_consumed,
            total_rotations_triggered=total_rotations_triggered,
        ),
        telemetry=MetricsOverviewTelemetryResponse(
            protocol_in_counts=dict(protocol_in_counts),
            protocol_out_counts=dict(protocol_out_counts),
            upstream_protocol_counts=dict(upstream_protocol_counts),
            route_kind_counts=dict(route_kind_counts),
            tool_calling_count=tool_calling_count,
        ),
        timeseries=MetricsTimeseriesResponse(window=window, granularity=granularity, buckets=bucket_rows),
        models=models,
    )


async def build_app_token_overview(session: AsyncSession, app_token_id: int, window: str) -> MetricsOverviewResponse:
    app_token_result = await session.execute(select(AppToken).where(AppToken.id == app_token_id))
    app_token = app_token_result.scalar_one_or_none()
    if app_token is None:
        raise ValueError(f"App token {app_token_id} not found")
    return await _build_overview_response(
        session,
        window=window,
        context_type="app_token",
        context_label=app_token.name,
        context_id=app_token.id,
        filters=[UsageLog.app_token_id == app_token.id],
    )


async def build_provider_overview(session: AsyncSession, provider: str, window: str) -> MetricsOverviewResponse:
    return await _build_overview_response(
        session,
        window=window,
        context_type="provider",
        context_label=provider,
        filters=[UsageLog.provider_used == provider],
    )


async def build_provider_key_overview(session: AsyncSession, provider_key_id: int, window: str) -> MetricsOverviewResponse:
    provider_key_result = await session.execute(select(ProviderKey).where(ProviderKey.id == provider_key_id))
    provider_key = provider_key_result.scalar_one_or_none()
    if provider_key is None:
        raise ValueError(f"Provider key {provider_key_id} not found")

    return await _build_overview_response(
        session,
        window=window,
        context_type="provider_key",
        context_label=provider_key.name,
        context_id=provider_key.id,
        filters=[UsageLog.provider_key_id == provider_key.id],
    )


async def build_queue_overview(session: AsyncSession, queue_name: str, window: str) -> MetricsOverviewResponse:
    queue_result = await session.execute(select(ModelQueue).where(ModelQueue.name == queue_name))
    queue = queue_result.scalar_one_or_none()
    if queue is None:
        raise ValueError(f"Queue '{queue_name}' not found")
    return await _build_overview_response(
        session,
        window=window,
        context_type="queue",
        context_label=queue.name,
        context_id=queue.id,
        filters=[UsageLog.queue_name == queue.name],
    )


def format_provider_pool_alert(provider: str, active_count: int, total_count: int) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    return (
        f"[LLMBridge] Provider alert at {timestamp}\n"
        f"Provider: {provider}\n"
        f"Active keys: {active_count}/{total_count}\n"
        "All keys may be in cooldown or unavailable."
    )


def format_key_status_alert(provider: str, key_name: str, new_status: str, blocked_until: str | None = None) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        "[LLMBridge] Provider key status change",
        f"Time: {timestamp}",
        f"Provider: {provider}",
        f"Key: {key_name}",
        f"Status: {new_status}",
    ]
    if blocked_until:
        lines.append(f"Blocked until: {blocked_until}")
    return "\n".join(lines)
