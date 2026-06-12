from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database.session import get_session
from backend.app.schemas.metrics import (
    GlobalMetricsResponse,
    MetricsOverviewResponse,
    MetricsTimeseriesResponse,
    ProjectMetricsResponse,
)
from backend.app.services.auth import require_admin
from backend.app.services.metrics import (
    build_app_token_overview,
    build_global_metrics,
    build_provider_key_overview,
    build_provider_overview,
    build_project_metrics,
    build_queue_overview,
    build_timeseries_metrics,
)


router = APIRouter(prefix="/observability", tags=["observability"], dependencies=[Depends(require_admin)])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/metrics/global", response_model=GlobalMetricsResponse)
async def global_metrics(
    session: SessionDep,
    range_filter: str = Query(default="24h", alias="range"),
) -> GlobalMetricsResponse:
    try:
        return await build_global_metrics(session, range_filter)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/metrics/projects", response_model=list[ProjectMetricsResponse])
async def project_metrics(
    session: SessionDep,
    range_filter: str = Query(default="24h", alias="range"),
) -> list[ProjectMetricsResponse]:
    try:
        return await build_project_metrics(session, range_filter)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/metrics/timeseries", response_model=MetricsTimeseriesResponse)
async def metrics_timeseries(
    session: SessionDep,
    range_filter: str = Query(default="24h", alias="range"),
) -> MetricsTimeseriesResponse:
    try:
        return await build_timeseries_metrics(session, range_filter)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/overview/app-tokens/{app_token_id}", response_model=MetricsOverviewResponse)
async def app_token_overview(
    app_token_id: int,
    session: SessionDep,
    range_filter: str = Query(default="24h", alias="range"),
) -> MetricsOverviewResponse:
    try:
        return await build_app_token_overview(session, app_token_id, range_filter)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/overview/provider-keys/{provider_key_id}", response_model=MetricsOverviewResponse)
async def provider_key_overview(
    provider_key_id: int,
    session: SessionDep,
    range_filter: str = Query(default="24h", alias="range"),
) -> MetricsOverviewResponse:
    try:
        return await build_provider_key_overview(session, provider_key_id, range_filter)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/overview/providers/{provider}", response_model=MetricsOverviewResponse)
async def provider_overview(
    provider: str,
    session: SessionDep,
    range_filter: str = Query(default="24h", alias="range"),
) -> MetricsOverviewResponse:
    return await build_provider_overview(session, provider, range_filter)


@router.get("/overview/model-queues/{queue_name}", response_model=MetricsOverviewResponse)
async def queue_overview(
    queue_name: str,
    session: SessionDep,
    range_filter: str = Query(default="24h", alias="range"),
) -> MetricsOverviewResponse:
    try:
        return await build_queue_overview(session, queue_name, range_filter)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
