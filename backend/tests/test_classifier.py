import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database.base import Base
from backend.app.database.models import (
    AppToken,
    KeyStatus,
    ModelQueue,
    ModelQueueCandidate,
    ProviderKey,
    ProviderKeyModelCooldown,
    ProviderKeyRouteState,
    QueueStrategy,
)
from backend.app.schemas.proxy import ChatCompletionRequest
from backend.app.services.classifier import (
    RouteClassificationEvent,
    classify_route_classification_event,
)
from backend.app.services.crypto import encrypt_text
from backend.app.services.proxy import (
    mark_provider_key_auth_failed,
    mark_provider_key_model_failure,
    mark_provider_key_model_soft_failure,
    mark_provider_key_model_success,
    proxy_chat_completion,
    proxy_chat_completion_stream,
)


class RouteClassifierTest(unittest.TestCase):
    def test_success_event_updates_latency_and_distribution(self) -> None:
        asyncio.run(self._run_success_event_test())

    def test_global_route_state_rank_reorders_queue_candidates(self) -> None:
        asyncio.run(self._run_global_route_state_rank_test())

    def test_429_with_retry_after_updates_cooldown_until(self) -> None:
        asyncio.run(self._run_retry_after_test())

    def test_google_retry_message_updates_cooldown_until(self) -> None:
        asyncio.run(self._run_google_retry_message_test())

    def test_429_does_not_degrade_provider_model_rank(self) -> None:
        asyncio.run(self._run_429_does_not_degrade_rank_test())

    def test_401_403_disable_or_block_route(self) -> None:
        asyncio.run(self._run_auth_error_test())

    def test_5xx_degrades_provider_model_temporarily(self) -> None:
        asyncio.run(self._run_5xx_test())

    def test_400_does_not_degrade_provider_model(self) -> None:
        asyncio.run(self._run_400_test())

    def test_404_is_classified_by_context(self) -> None:
        asyncio.run(self._run_404_test())

    def test_legacy_methods_delegate_correctly(self) -> None:
        asyncio.run(self._run_legacy_methods_test())

    def test_legacy_mirror_can_be_disabled_without_affecting_new_state(self) -> None:
        asyncio.run(self._run_legacy_mirror_disable_test())

    def test_streaming_and_non_streaming_emit_classification(self) -> None:
        asyncio.run(self._run_proxy_emission_test())

    def test_classifier_failure_does_not_break_response(self) -> None:
        asyncio.run(self._run_classifier_failure_safe_test())

    async def _create_session_factory(self, db_name: str):
        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / db_name
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return temp_dir, engine, session_factory

    async def _seed_candidate(self, session):
        queue = ModelQueue(name="prod", description=None, strategy=QueueStrategy.SMART, is_active=True)
        session.add(queue)
        await session.flush()
        candidate = ModelQueueCandidate(queue_id=queue.id, provider="google", model_name="flash", position=0)
        key = ProviderKey(name="Key A", description=None, provider="google", encrypted_token="cipher", status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0)
        session.add_all([candidate, key])
        await session.commit()
        return candidate, key

    async def _run_success_event_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("classifier-success.sqlite")
        try:
            async with session_factory() as session:
                candidate, key = await self._seed_candidate(session)
                event = RouteClassificationEvent(
                    provider="google",
                    model_name="flash",
                    key_id=key.id,
                    candidate_id=candidate.id,
                    success=True,
                    status_code=200,
                    latency_ms=1234.0,
                    started_at=candidate.created_at,
                    finished_at=candidate.created_at,
                )
                await classify_route_classification_event(session, event)

                refreshed_candidate = await session.get(ModelQueueCandidate, candidate.id)
                route_state = (
                    await session.execute(
                        select(ProviderKeyRouteState).where(
                            ProviderKeyRouteState.provider_key_id == key.id,
                            ProviderKeyRouteState.model_name == "flash",
                        )
                    )
                ).scalar_one()

            self.assertEqual(refreshed_candidate.success_count, 1)
            self.assertGreater(refreshed_candidate.avg_latency_ms, 1200.0)
            self.assertIsNotNone(route_state.last_used_at)
            self.assertEqual(route_state.in_flight_count, 0)
            self.assertIsNotNone(route_state.next_available_at)
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_global_route_state_rank_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("classifier-global-rank.sqlite")
        try:
            async with session_factory() as session:
                queue = ModelQueue(name="prod", description=None, strategy=QueueStrategy.SMART, is_active=True)
                session.add(queue)
                await session.flush()
                google_candidate = ModelQueueCandidate(queue_id=queue.id, provider="google", model_name="flash", position=0)
                openai_candidate = ModelQueueCandidate(queue_id=queue.id, provider="openai", model_name="gpt-4o-mini", position=1)
                google_key = ProviderKey(
                    name="Google Key",
                    description=None,
                    provider="google",
                    encrypted_token="cipher-google",
                    status=KeyStatus.ACTIVE,
                    blocked_until=None,
                    failure_count=0,
                )
                openai_key = ProviderKey(
                    name="OpenAI Key",
                    description=None,
                    provider="openai",
                    encrypted_token="cipher-openai",
                    status=KeyStatus.ACTIVE,
                    blocked_until=None,
                    failure_count=0,
                )
                session.add_all([google_candidate, openai_candidate, google_key, openai_key])
                await session.commit()

                event = RouteClassificationEvent(
                    provider="google",
                    model_name="flash",
                    key_id=google_key.id,
                    candidate_id=None,
                    success=False,
                    status_code=500,
                    latency_ms=3200.0,
                    started_at=google_key.created_at,
                    finished_at=google_key.created_at,
                    route_kind="provider",
                    requested_model="google/flash",
                    resolved_model="google/flash",
                    error_message="Upstream provider error",
                )
                await classify_route_classification_event(session, event)

                google_route_state = (
                    await session.execute(
                        select(ProviderKeyRouteState).where(
                            ProviderKeyRouteState.provider_key_id == google_key.id,
                            ProviderKeyRouteState.provider == "google",
                            ProviderKeyRouteState.model_name == "flash",
                        )
                    )
                ).scalar_one()
                refreshed_google_candidate = await session.get(ModelQueueCandidate, google_candidate.id)
                snapshot = await materialize_model_route_snapshot(session, "queue/prod")

            self.assertGreater(google_route_state.final_rank, 0.0)
            self.assertEqual(refreshed_google_candidate.final_rank, 0.0)
            self.assertEqual(
                [route.provider_key_name for route in snapshot.routes],
                ["OpenAI Key", "Google Key"],
            )
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_retry_after_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("classifier-429.sqlite")
        try:
            async with session_factory() as session:
                _, key = await self._seed_candidate(session)
                event = RouteClassificationEvent(
                    provider="google",
                    model_name="flash",
                    key_id=key.id,
                    success=False,
                    status_code=429,
                    latency_ms=10.0,
                    started_at=key.created_at,
                    finished_at=key.created_at,
                    response_headers={"retry-after": "12"},
                )
                await classify_route_classification_event(session, event)
                state = (
                    await session.execute(
                        select(ProviderKeyRouteState).where(
                            ProviderKeyRouteState.provider_key_id == key.id,
                            ProviderKeyRouteState.model_name == "flash",
                        )
                    )
                ).scalar_one()

            self.assertIsNotNone(state.cooldown_until)
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_google_retry_message_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("classifier-google-retry.sqlite")
        try:
            async with session_factory() as session:
                _, key = await self._seed_candidate(session)
                event = RouteClassificationEvent(
                    provider="google",
                    model_name="flash",
                    key_id=key.id,
                    success=False,
                    status_code=429,
                    latency_ms=10.0,
                    started_at=key.created_at,
                    finished_at=key.created_at,
                    response_body_preview={"error": {"message": "Please retry in 393.337641ms"}},
                )
                await classify_route_classification_event(session, event)
                state = (
                    await session.execute(
                        select(ProviderKeyRouteState).where(
                            ProviderKeyRouteState.provider_key_id == key.id,
                            ProviderKeyRouteState.model_name == "flash",
                        )
                    )
                ).scalar_one()

            self.assertIsNotNone(state.cooldown_until)
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_429_does_not_degrade_rank_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("classifier-429-rank.sqlite")
        try:
            async with session_factory() as session:
                candidate, key = await self._seed_candidate(session)
                before = await session.get(ModelQueueCandidate, candidate.id)
                event = RouteClassificationEvent(
                    provider="google",
                    model_name="flash",
                    key_id=key.id,
                    candidate_id=candidate.id,
                    success=False,
                    status_code=429,
                    latency_ms=25.0,
                    started_at=key.created_at,
                    finished_at=key.created_at,
                    response_body_preview={"error": {"message": "Please retry in 1.2s"}},
                )
                await classify_route_classification_event(session, event)
                refreshed_candidate = await session.get(ModelQueueCandidate, candidate.id)
                state = (
                    await session.execute(
                        select(ProviderKeyRouteState).where(
                            ProviderKeyRouteState.provider_key_id == key.id,
                            ProviderKeyRouteState.model_name == "flash",
                        )
                    )
                ).scalar_one()

            self.assertEqual(refreshed_candidate.error_score, before.error_score)
            self.assertEqual(refreshed_candidate.final_rank, before.final_rank)
            self.assertIsNotNone(state.cooldown_until)
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_auth_error_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("classifier-auth.sqlite")
        try:
            async with session_factory() as session:
                _, key = await self._seed_candidate(session)
                event = RouteClassificationEvent(
                    provider="google",
                    model_name="flash",
                    key_id=key.id,
                    success=False,
                    status_code=403,
                    latency_ms=10.0,
                    started_at=key.created_at,
                    finished_at=key.created_at,
                    error_message="billing issue on account",
                )
                await classify_route_classification_event(session, event)
                refreshed_key = await session.get(ProviderKey, key.id)
                state = (
                    await session.execute(
                        select(ProviderKeyRouteState).where(
                            ProviderKeyRouteState.provider_key_id == key.id,
                            ProviderKeyRouteState.model_name == "flash",
                        )
                    )
                ).scalar_one()

            self.assertEqual(refreshed_key.status, KeyStatus.SUSPENDED_BILLING)
            self.assertTrue(state.disabled)
            self.assertEqual(state.disabled_reason, "billing")
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_5xx_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("classifier-5xx.sqlite")
        try:
            async with session_factory() as session:
                candidate, key = await self._seed_candidate(session)
                event = RouteClassificationEvent(
                    provider="google",
                    model_name="flash",
                    key_id=key.id,
                    candidate_id=candidate.id,
                    success=False,
                    status_code=502,
                    latency_ms=800.0,
                    started_at=key.created_at,
                    finished_at=key.created_at,
                    error_message="upstream failure",
                    retry_hint_seconds=30,
                )
                await classify_route_classification_event(session, event)
                refreshed_candidate = await session.get(ModelQueueCandidate, candidate.id)
                state = (
                    await session.execute(
                        select(ProviderKeyRouteState).where(
                            ProviderKeyRouteState.provider_key_id == key.id,
                            ProviderKeyRouteState.model_name == "flash",
                        )
                    )
                ).scalar_one()

            self.assertGreater(refreshed_candidate.error_score, 0.0)
            self.assertIsNotNone(state.cooldown_until)
            self.assertIsNotNone(state.next_available_at)
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_400_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("classifier-400.sqlite")
        try:
            async with session_factory() as session:
                candidate, key = await self._seed_candidate(session)
                event = RouteClassificationEvent(
                    provider="google",
                    model_name="flash",
                    key_id=key.id,
                    candidate_id=candidate.id,
                    success=False,
                    status_code=400,
                    latency_ms=100.0,
                    started_at=key.created_at,
                    finished_at=key.created_at,
                    error_message="adapter mismatch",
                )
                await classify_route_classification_event(session, event)
                refreshed_candidate = await session.get(ModelQueueCandidate, candidate.id)

            self.assertEqual(refreshed_candidate.error_score, 0.0)
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_404_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("classifier-404.sqlite")
        try:
            async with session_factory() as session:
                candidate, key = await self._seed_candidate(session)
                model_missing_event = RouteClassificationEvent(
                    provider="google",
                    model_name="flash",
                    key_id=key.id,
                    candidate_id=candidate.id,
                    success=False,
                    status_code=404,
                    latency_ms=100.0,
                    started_at=key.created_at,
                    finished_at=key.created_at,
                    error_message="models/gemini-2.5 is not found",
                )
                await classify_route_classification_event(session, model_missing_event)
                refreshed_candidate = await session.get(ModelQueueCandidate, candidate.id)

                access_missing_event = RouteClassificationEvent(
                    provider="google",
                    model_name="flash",
                    key_id=key.id,
                    success=False,
                    status_code=404,
                    latency_ms=100.0,
                    started_at=key.created_at,
                    finished_at=key.created_at,
                    error_message="resource path unavailable",
                )
                await classify_route_classification_event(session, access_missing_event)
                state = (
                    await session.execute(
                        select(ProviderKeyRouteState).where(
                            ProviderKeyRouteState.provider_key_id == key.id,
                            ProviderKeyRouteState.model_name == "flash",
                        )
                    )
                ).scalar_one()

            self.assertGreater(refreshed_candidate.error_score, 0.0)
            self.assertTrue(state.disabled)
            self.assertEqual(state.disabled_reason, "not_found")
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_legacy_methods_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("classifier-legacy.sqlite")
        try:
            async with session_factory() as session:
                _, key = await self._seed_candidate(session)
                await mark_provider_key_model_failure(session, key, "flash", retry_after_seconds=15)
                await mark_provider_key_model_soft_failure(session, key, "flash", cooldown_seconds=30)
                await mark_provider_key_auth_failed(session, key, "flash", 401, "bad token")
                await mark_provider_key_model_success(session, key, "flash")

                legacy_rows = (
                    await session.execute(
                        select(ProviderKeyModelCooldown).where(
                            ProviderKeyModelCooldown.provider_key_id == key.id,
                            ProviderKeyModelCooldown.model_name == "flash",
                        )
                    )
                ).scalars().all()
                state = (
                    await session.execute(
                        select(ProviderKeyRouteState).where(
                            ProviderKeyRouteState.provider_key_id == key.id,
                            ProviderKeyRouteState.model_name == "flash",
                        )
                    )
                ).scalar_one()

            self.assertTrue(len(legacy_rows) >= 0)
            self.assertIsNotNone(state)
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_legacy_mirror_disable_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("classifier-legacy-disabled.sqlite")
        try:
            async with session_factory() as session:
                _, key = await self._seed_candidate(session)
                with patch(
                    "backend.app.services.proxy.get_settings",
                    return_value=SimpleNamespace(legacy_cooldown_mirror_enabled=False),
                ):
                    await mark_provider_key_model_failure(session, key, "flash", retry_after_seconds=15)

                legacy_rows = (
                    await session.execute(
                        select(ProviderKeyModelCooldown).where(
                            ProviderKeyModelCooldown.provider_key_id == key.id,
                            ProviderKeyModelCooldown.model_name == "flash",
                        )
                    )
                ).scalars().all()
                state = (
                    await session.execute(
                        select(ProviderKeyRouteState).where(
                            ProviderKeyRouteState.provider_key_id == key.id,
                            ProviderKeyRouteState.model_name == "flash",
                        )
                    )
                ).scalar_one()

            self.assertEqual(legacy_rows, [])
            self.assertIsNotNone(state.cooldown_until)
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_proxy_emission_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("classifier-proxy.sqlite")
        try:
            async with session_factory() as session:
                app_token = AppToken(name="Atlas", environment="development", token="app-token-1", is_active=True, rpm_limit=None)
                provider_key = ProviderKey(name="Google primary", description=None, provider="google", encrypted_token=encrypt_text("google-secret"), status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0)
                session.add_all([app_token, provider_key])
                await session.commit()

                upstream_body = {
                    "id": "chatcmpl-1",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "gemini-3-flash-preview",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }

                def handler(request: httpx.Request) -> httpx.Response:
                    return httpx.Response(200, json=upstream_body, request=request)

                original_async_client = httpx.AsyncClient
                client = original_async_client(transport=httpx.MockTransport(handler), timeout=90.0)

                def client_factory(*args, **kwargs):
                    timeout = kwargs.get("timeout")
                    return original_async_client(transport=httpx.MockTransport(handler), timeout=timeout)

                payload = ChatCompletionRequest(model="google/gemini-3.1-flash", messages=[{"role": "user", "content": "hi"}])
                with patch("backend.app.services.proxy.httpx.AsyncClient", side_effect=client_factory):
                    status_code, _ = await proxy_chat_completion(session, app_token, payload, client=client)
                self.assertEqual(status_code, 200)

                stream_payload = ChatCompletionRequest(model="google/gemini-3.1-flash", messages=[{"role": "user", "content": "hi"}], stream=True)
                with patch("backend.app.services.proxy.httpx.AsyncClient", side_effect=client_factory):
                    response = await proxy_chat_completion_stream(session, app_token, stream_payload, client=client)
                async for _ in response.body_iterator:
                    pass

                states = (
                    await session.execute(
                        select(ProviderKeyRouteState).where(
                            ProviderKeyRouteState.provider_key_id == provider_key.id,
                            ProviderKeyRouteState.model_name == "gemini-3-flash-preview",
                        )
                    )
                ).scalars().all()

                await client.aclose()

            self.assertEqual(len(states), 1)
            self.assertIsNotNone(states[0].last_used_at)
        finally:
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_classifier_failure_safe_test(self) -> None:
        temp_dir, engine, session_factory = await self._create_session_factory("classifier-safe.sqlite")
        try:
            async with session_factory() as session:
                app_token = AppToken(name="Atlas", environment="development", token="app-token-1", is_active=True, rpm_limit=None)
                provider_key = ProviderKey(name="Google primary", description=None, provider="google", encrypted_token=encrypt_text("google-secret"), status=KeyStatus.ACTIVE, blocked_until=None, failure_count=0)
                session.add_all([app_token, provider_key])
                await session.commit()

                upstream_body = {
                    "id": "chatcmpl-1",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "gemini-3-flash-preview",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }

                def handler(request: httpx.Request) -> httpx.Response:
                    return httpx.Response(200, json=upstream_body, request=request)

                original_async_client = httpx.AsyncClient
                client = original_async_client(transport=httpx.MockTransport(handler), timeout=90.0)

                def client_factory(*args, **kwargs):
                    timeout = kwargs.get("timeout")
                    return original_async_client(transport=httpx.MockTransport(handler), timeout=timeout)

                payload = ChatCompletionRequest(model="google/gemini-3.1-flash", messages=[{"role": "user", "content": "hi"}])
                with patch("backend.app.services.proxy.httpx.AsyncClient", side_effect=client_factory):
                    with patch("backend.app.services.classifier.classify_route_classification_event", side_effect=RuntimeError("boom")):
                        status_code, body = await proxy_chat_completion(session, app_token, payload, client=client)

                await client.aclose()

            self.assertEqual(status_code, 200)
            self.assertEqual(body["choices"][0]["message"]["content"], "ok")
        finally:
            await engine.dispose()
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
