from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import distinct, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database.models import ModelQueue, ModelQueueCandidate, ProviderKeyRouteState
from backend.app.database.session import get_sessionmaker
from backend.app.services.queues import ResolvedRouteSnapshot, resolve_model_route_snapshot


logger = logging.getLogger(__name__)


@dataclass
class MaterializedRouteCatalog:
    snapshots: dict[str, ResolvedRouteSnapshot]
    refreshed_at: float | None = None


class RouteMaterializer:
    def __init__(self) -> None:
        self._catalog = MaterializedRouteCatalog(snapshots={})
        self._lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[None] | None = None
        self._dirty = False

    def get_snapshot(self, model: str) -> ResolvedRouteSnapshot | None:
        return self._catalog.snapshots.get(model)

    def set_snapshot(self, model: str, snapshot: ResolvedRouteSnapshot) -> None:
        self._catalog.snapshots[model] = snapshot

    def set_snapshots(self, snapshots: dict[str, ResolvedRouteSnapshot]) -> None:
        self._catalog.snapshots = snapshots
        self._catalog.refreshed_at = None

    async def refresh_model(self, model: str) -> ResolvedRouteSnapshot | None:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            snapshot = await resolve_model_route_snapshot(session, model)
        self.set_snapshot(model, snapshot)
        return snapshot

    async def refresh_many(self, models: Iterable[str]) -> None:
        for model in models:
            try:
                await self.refresh_model(model)
            except Exception:
                logger.exception("Route materialization refresh failed", extra={"model": model})

    async def refresh_all(self) -> None:
        sessionmaker = get_sessionmaker()
        try:
            async with sessionmaker() as session:
                has_route_state_table = await session.run_sync(
                    lambda sync_session: inspect(sync_session.get_bind()).has_table("provider_key_route_states")
                )
                if not has_route_state_table:
                    return
                models = await self._collect_target_models(session)
                snapshots: dict[str, ResolvedRouteSnapshot] = {}
                for model in models:
                    try:
                        snapshots[model] = await resolve_model_route_snapshot(session, model)
                    except Exception:
                        logger.exception("Route materialization refresh failed", extra={"model": model})
            if snapshots:
                self.set_snapshots({**self._catalog.snapshots, **snapshots})
        except Exception:
            logger.exception("Route materializer refresh failed")

    def schedule_refresh_all(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        if self._refresh_task is not None and not self._refresh_task.done():
            self._dirty = True
            return

        self._refresh_task = loop.create_task(self._refresh_worker(), name="route-materializer-refresh")

    async def ensure_snapshot(self, model: str) -> ResolvedRouteSnapshot:
        snapshot = self.get_snapshot(model)
        if snapshot is not None:
            return snapshot
        snapshot = await self.refresh_model(model)
        if snapshot is None:
            raise RuntimeError(f"Unable to materialize route snapshot for '{model}'")
        return snapshot

    async def warmup(self) -> None:
        await self.refresh_all()

    async def _refresh_worker(self) -> None:
        try:
            while True:
                self._dirty = False
                try:
                    await self.refresh_all()
                except Exception:
                    logger.exception("Route materializer worker failed")
                if not self._dirty:
                    return
        finally:
            self._refresh_task = None

    async def _collect_target_models(self, session: AsyncSession) -> list[str]:
        models: set[str] = set()

        queue_names_result = await session.execute(select(ModelQueue.name).where(ModelQueue.is_active.is_(True)))
        for queue_name in queue_names_result.scalars().all():
            models.add(f"queue/{queue_name}")

        queue_candidates_result = await session.execute(
            select(ModelQueueCandidate.provider, ModelQueueCandidate.model_name)
            .join(ModelQueue, ModelQueue.id == ModelQueueCandidate.queue_id)
            .where(ModelQueue.is_active.is_(True), ModelQueueCandidate.is_active.is_(True))
            .distinct()
        )
        for provider, model_name in queue_candidates_result.all():
            if provider and model_name:
                models.add(f"{provider}/{model_name}")

        route_states_result = await session.execute(
            select(ProviderKeyRouteState.provider, ProviderKeyRouteState.model_name).distinct()
        )
        for provider, model_name in route_states_result.all():
            if provider and model_name:
                models.add(f"{provider}/{model_name}")

        return sorted(models)


_route_materializer = RouteMaterializer()


def get_route_materializer() -> RouteMaterializer:
    return _route_materializer


def get_materialized_route_snapshot(model: str) -> ResolvedRouteSnapshot | None:
    return _route_materializer.get_snapshot(model)


async def warmup_route_materializer() -> None:
    await _route_materializer.warmup()


def schedule_route_materializer_refresh_all() -> None:
    _route_materializer.schedule_refresh_all()


async def ensure_materialized_route_snapshot(session: AsyncSession, model: str) -> ResolvedRouteSnapshot:
    snapshot = _route_materializer.get_snapshot(model)
    if snapshot is not None:
        return snapshot
    snapshot = await resolve_model_route_snapshot(session, model)
    _route_materializer.set_snapshot(model, snapshot)
    return snapshot
