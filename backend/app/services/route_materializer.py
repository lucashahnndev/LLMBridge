from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Literal

from fastapi import HTTPException, status
from sqlalchemy import distinct, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database.models import ModelQueue, ModelQueueCandidate, ProviderKeyRouteState
from backend.app.database.session import get_sessionmaker
from backend.app.services.queues import ResolvedRouteSnapshot, _raise_for_exhausted_snapshot, materialize_model_route_snapshot


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
        self._dirty_models: set[str] = set()

    def get_snapshot(self, model: str) -> ResolvedRouteSnapshot | None:
        return self._catalog.snapshots.get(model)

    def set_snapshot(self, model: str, snapshot: ResolvedRouteSnapshot) -> None:
        self._catalog.snapshots[model] = snapshot

    def invalidate_model(self, model: str) -> None:
        self._catalog.snapshots.pop(model, None)

    def mark_route_unavailable(
        self,
        *,
        provider: str,
        model_name: str,
        provider_key_id: int | None,
        reason: Literal["cooldown", "blocked", "disabled"],
        cooldown_until: datetime | None = None,
    ) -> None:
        if provider_key_id is None:
            return
        for snapshot in self._catalog.snapshots.values():
            self._mark_route_unavailable_in_snapshot(
                snapshot,
                provider=provider,
                model_name=model_name,
                provider_key_id=provider_key_id,
                reason=reason,
                cooldown_until=cooldown_until,
            )

    def _mark_route_unavailable_in_snapshot(
        self,
        snapshot: ResolvedRouteSnapshot,
        *,
        provider: str,
        model_name: str,
        provider_key_id: int,
        reason: Literal["cooldown", "blocked", "disabled"],
        cooldown_until: datetime | None = None,
    ) -> None:
        removed_count = 0
        kept_routes = []
        for route in snapshot.routes:
            if (
                route.provider == provider
                and route.model_name == model_name
                and route.provider_key_id == provider_key_id
            ):
                removed_count += 1
                continue
            kept_routes.append(route)
        if removed_count <= 0:
            return

        snapshot.routes[:] = kept_routes
        summary = snapshot.summary
        summary.eligible_count = max(0, summary.eligible_count - removed_count)
        if reason == "cooldown":
            summary.cooldown_count += removed_count
            summary.recoverable_cooldowns += removed_count
            if cooldown_until is not None:
                current_smallest = summary.smallest_cooldown_until
                if current_smallest is None or cooldown_until < current_smallest:
                    summary.smallest_cooldown_until = cooldown_until
            return
        if reason == "blocked":
            summary.blocked_count += removed_count
            summary.structural_unavailable_count += removed_count
            return
        summary.disabled_count += removed_count
        summary.structural_unavailable_count += removed_count

    def set_snapshots(self, snapshots: dict[str, ResolvedRouteSnapshot]) -> None:
        self._catalog.snapshots = snapshots
        self._catalog.refreshed_at = None

    async def refresh_model(self, model: str) -> ResolvedRouteSnapshot | None:
        sessionmaker = get_sessionmaker()
        try:
            async with sessionmaker() as session:
                snapshot = await materialize_model_route_snapshot(session, model)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND:
                self.invalidate_model(model)
                return None
            raise
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
                        snapshots[model] = await materialize_model_route_snapshot(session, model)
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

    def schedule_refresh_models(self, models: Iterable[str]) -> None:
        targets = {model for model in models if model}
        if not targets:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        self._dirty_models.update(targets)
        if self._refresh_task is not None and not self._refresh_task.done():
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
                refresh_all_requested = self._dirty
                self._dirty = False
                dirty_models = set(self._dirty_models)
                self._dirty_models.clear()
                try:
                    if refresh_all_requested:
                        await self.refresh_all()
                    elif dirty_models:
                        await self.refresh_many(sorted(dirty_models))
                except Exception:
                    logger.exception("Route materializer worker failed")
                if not self._dirty and not self._dirty_models:
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


def invalidate_materialized_route_snapshot(model: str) -> None:
    _route_materializer.invalidate_model(model)


def apply_materialized_route_unavailability(
    *,
    provider: str,
    model_name: str,
    provider_key_id: int | None,
    reason: Literal["cooldown", "blocked", "disabled"],
    cooldown_until: datetime | None = None,
) -> None:
    _route_materializer.mark_route_unavailable(
        provider=provider,
        model_name=model_name,
        provider_key_id=provider_key_id,
        reason=reason,
        cooldown_until=cooldown_until,
    )


def schedule_route_materializer_refresh_models(models: Iterable[str]) -> None:
    _route_materializer.schedule_refresh_models(models)


async def ensure_materialized_route_snapshot(session: AsyncSession, model: str) -> ResolvedRouteSnapshot:
    snapshot = _route_materializer.get_snapshot(model)
    if snapshot is not None:
        if not snapshot.routes:
            _raise_for_exhausted_snapshot(snapshot)
        return snapshot
    snapshot = await materialize_model_route_snapshot(session, model)
    _route_materializer.set_snapshot(model, snapshot)
    if not snapshot.routes:
        _raise_for_exhausted_snapshot(snapshot)
    return snapshot
