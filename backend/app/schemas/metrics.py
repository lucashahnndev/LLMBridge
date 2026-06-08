from pydantic import BaseModel, Field

from backend.app.schemas.common import ORMModel


class GlobalMetricsResponse(ORMModel):
    total_requests: int = Field(default=0, ge=0)
    success_rate: float = Field(default=0.0, ge=0)
    avg_latency_ms: float = Field(default=0.0, ge=0)
    total_tokens_consumed: int = Field(default=0, ge=0)
    active_keys_count: int = Field(default=0, ge=0)
    cooldown_keys_count: int = Field(default=0, ge=0)
    total_rotations_triggered: int = Field(default=0, ge=0)


class ProjectMetricsResponse(ORMModel):
    app_token_id: int
    app_name: str
    environment: str
    requests_count: int = Field(default=0, ge=0)
    total_tokens_consumed: int = Field(default=0, ge=0)
    avg_latency_ms: float = Field(default=0.0, ge=0)


class MetricsTimeseriesBucketResponse(ORMModel):
    bucket_start: str
    bucket_end: str
    requests_count: int = Field(default=0, ge=0)
    success_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    total_tokens_consumed: int = Field(default=0, ge=0)
    avg_latency_ms: float = Field(default=0.0, ge=0)
    total_rotations_triggered: int = Field(default=0, ge=0)


class MetricsTimeseriesResponse(ORMModel):
    window: str
    granularity: str
    buckets: list[MetricsTimeseriesBucketResponse] = Field(default_factory=list)


class MetricsOverviewSummaryResponse(ORMModel):
    total_requests: int = Field(default=0, ge=0)
    success_rate: float = Field(default=0.0, ge=0)
    avg_latency_ms: float = Field(default=0.0, ge=0)
    total_tokens_consumed: int = Field(default=0, ge=0)
    total_rotations_triggered: int = Field(default=0, ge=0)


class MetricsOverviewTelemetryResponse(ORMModel):
    protocol_in_counts: dict[str, int] = Field(default_factory=dict)
    protocol_out_counts: dict[str, int] = Field(default_factory=dict)
    route_kind_counts: dict[str, int] = Field(default_factory=dict)
    tool_calling_count: int = Field(default=0, ge=0)


class MetricsModelUsageResponse(ORMModel):
    model_name: str
    requests_count: int = Field(default=0, ge=0)
    success_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    total_tokens_consumed: int = Field(default=0, ge=0)
    avg_latency_ms: float = Field(default=0.0, ge=0)
    total_rotations_triggered: int = Field(default=0, ge=0)


class MetricsOverviewResponse(ORMModel):
    context_type: str
    context_id: int | None = None
    context_label: str
    window: str
    granularity: str
    summary: MetricsOverviewSummaryResponse
    telemetry: MetricsOverviewTelemetryResponse = Field(default_factory=MetricsOverviewTelemetryResponse)
    timeseries: MetricsTimeseriesResponse
    models: list[MetricsModelUsageResponse] = Field(default_factory=list)
