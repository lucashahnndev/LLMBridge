#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.config import get_settings
from backend.app.database.models import KeyStatus, ProviderKey
from backend.app.services.crypto import decrypt_text
from backend.app.services.openai_probe import build_openai_probe_candidates, load_trace
from backend.app.services.proxy import resolve_route_driver_selection


async def _select_provider_key(session, provider: str, provider_key_id: int | None) -> ProviderKey:
    if provider_key_id is not None:
        result = await session.execute(
            select(ProviderKey).where(
                ProviderKey.id == provider_key_id,
                ProviderKey.provider == provider,
            )
        )
        provider_key = result.scalar_one_or_none()
        if provider_key is None:
            raise RuntimeError(f"{provider} provider key id {provider_key_id} not found")
        return provider_key

    result = await session.execute(
        select(ProviderKey).where(
            ProviderKey.provider == provider,
            ProviderKey.status == KeyStatus.ACTIVE,
        ).order_by(ProviderKey.id.asc())
    )
    provider_key = result.scalars().first()
    if provider_key is None:
        raise RuntimeError(f"no active {provider} provider key found")
    return provider_key


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Replay a canonical trace against an OpenAI-compatible route.")
    parser.add_argument("--trace", required=True, help="Path to a trace JSON file")
    parser.add_argument("--route-model", default=None, help="Override route model, e.g. github/openai/gpt-4.1")
    parser.add_argument("--provider-key-id", type=int, default=None, help="Use a specific gateway provider key id")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads and do not send network requests")
    args = parser.parse_args()

    settings = get_settings()
    trace = load_trace(args.trace)
    candidates = build_openai_probe_candidates(trace, route_model=args.route_model)
    candidate = candidates[0]

    print(f"[trace] {args.trace}")
    print(f"[route] {candidate.route_model}")
    print(f"[gateway] {candidate.gateway_provider}")
    print(f"[adapter] {candidate.adapter_provider}")

    if args.dry_run:
        print(json.dumps(candidate.payload, ensure_ascii=False, indent=2))
        return 0

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            provider_key = await _select_provider_key(
                session,
                candidate.gateway_provider,
                args.provider_key_id,
            )
            provider_token = decrypt_text(provider_key.encrypted_token)
            key_label = provider_key.description or provider_key.name or f"key-{provider_key.id}"
            print(f"[key] {provider_key.id} {key_label}")

            async with httpx.AsyncClient(timeout=settings.proxy_timeout_seconds) as client:
                selection = resolve_route_driver_selection(candidate.route_model)
                response = await client.post(
                    selection.gateway_driver.build_url(candidate.gateway_model_name),
                    headers=selection.gateway_driver.build_headers(provider_token),
                    json=candidate.payload,
                )
                print(f"[status] {response.status_code}")
                print(response.text)
                if 200 <= response.status_code < 300:
                    normalized = selection.gateway_driver.normalize_response_body(
                        response.json(),
                        candidate.gateway_model_name,
                    )
                    print("[normalized]")
                    print(json.dumps(normalized, ensure_ascii=False, indent=2))
                    return 0
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
