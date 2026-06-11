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
from backend.app.drivers.google import GoogleDriver
from backend.app.services.crypto import decrypt_text
from backend.app.services.gemini_probe import build_google_probe_candidates, load_trace
from backend.app.services.proxy import get_eligible_provider_keys


async def _select_google_provider_key(session, provider_key_id: int | None) -> ProviderKey:
    if provider_key_id is not None:
        result = await session.execute(
            select(ProviderKey).where(
                ProviderKey.id == provider_key_id,
                ProviderKey.provider == "google",
            )
        )
        provider_key = result.scalar_one_or_none()
        if provider_key is None:
            raise RuntimeError(f"google provider key id {provider_key_id} not found")
        return provider_key

    result = await session.execute(
        select(ProviderKey).where(
            ProviderKey.provider == "google",
            ProviderKey.status == KeyStatus.ACTIVE,
        ).order_by(ProviderKey.id.asc())
    )
    provider_key = result.scalars().first()
    if provider_key is None:
        raise RuntimeError("no active google provider key found")
    return provider_key


async def _select_google_provider_keys(session, model_name: str, provider_key_id: int | None) -> list[ProviderKey]:
    if provider_key_id is not None:
        return [await _select_google_provider_key(session, provider_key_id)]
    return await get_eligible_provider_keys(session, "google", model_name)


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Replay a trace against one Gemini model/key.")
    parser.add_argument("--trace", required=True, help="Path to a trace JSON file")
    parser.add_argument("--model", default=None, help="Override Gemini model name, e.g. gemini-3.1-flash-lite")
    parser.add_argument(
        "--strategy",
        choices=["auto", "baseline", "strict-schema", "drop-parameterless", "drop-parameterless-strict"],
        default="auto",
        help="Payload sanitization strategy",
    )
    parser.add_argument(
        "--transport",
        choices=["auto", "openai", "native"],
        default="auto",
        help="Google transport to probe",
    )
    parser.add_argument("--provider-key-id", type=int, default=None, help="Use a specific Google provider key id")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads and do not send network requests")
    parser.add_argument("--print-payload", action="store_true", help="Print full candidate payloads before sending")
    args = parser.parse_args()

    settings = get_settings()
    trace = load_trace(args.trace)
    transports = ["openai", "native"] if args.transport == "auto" else [args.transport]
    candidates = []
    for transport in transports:
        candidates.extend(
            build_google_probe_candidates(
                trace,
                base_url=settings.google_api_base,
                model_name=args.model,
                strategy=args.strategy,
                transport=transport,  # type: ignore[arg-type]
            )
        )

    print(f"[trace] {args.trace}")
    print(f"[model] {candidates[0].model_name}")
    print(f"[strategy] {args.strategy}")
    print(f"[transport] {args.transport}")

    if args.dry_run:
        for candidate in candidates:
            print(f"\n--- {candidate.transport}:{candidate.strategy} ---")
            print(json.dumps(candidate.payload, ensure_ascii=False, indent=2))
        return 0

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            driver = GoogleDriver("google", settings.google_api_base)
            native_base = settings.google_api_base.removesuffix("/openai")

            async with httpx.AsyncClient(timeout=settings.proxy_timeout_seconds) as client:
                for candidate in candidates:
                    print(f"\n--- trying {candidate.transport}:{candidate.strategy} ---")
                    if args.print_payload:
                        print(json.dumps(candidate.payload, ensure_ascii=False, indent=2))
                    else:
                        tool_count = 0
                        tools = candidate.payload.get("tools")
                        if isinstance(tools, list):
                            for tool in tools:
                                if not isinstance(tool, dict):
                                    continue
                                declarations = tool.get("functionDeclarations")
                                if isinstance(declarations, list):
                                    tool_count += len(declarations)
                                elif tool.get("function"):
                                    tool_count += 1
                        print(
                            f"[payload] keys={sorted(candidate.payload.keys())} "
                            f"tools={tool_count}"
                        )
                    provider_keys = await _select_google_provider_keys(
                        session,
                        candidate.model_name,
                        args.provider_key_id,
                    )
                    if not provider_keys:
                        raise RuntimeError("no eligible google provider keys found")
                    tried_key_ids: set[int] = set()
                    key_index = 0
                    while key_index < len(provider_keys):
                        provider_key = provider_keys[key_index]
                        if provider_key.id in tried_key_ids:
                            key_index += 1
                            continue
                        tried_key_ids.add(provider_key.id)
                        provider_token = decrypt_text(provider_key.encrypted_token)
                        key_label = provider_key.description or provider_key.name or f"key-{provider_key.id}"
                        print(f"[key] {provider_key.id} {key_label}")
                        if candidate.transport == "native":
                            response = await client.post(
                                f"{native_base}/models/{candidate.model_name}:generateContent",
                                headers={
                                    "x-goog-api-key": provider_token,
                                    "Content-Type": "application/json",
                                },
                                json=candidate.payload,
                            )
                        else:
                            response = await client.post(
                                driver.build_url(candidate.model_name),
                                headers=driver.build_headers(provider_token),
                                json=candidate.payload,
                            )
                        body = response.text
                        print(f"[status] {response.status_code}")
                        print(body)
                        if 200 <= response.status_code < 300:
                            normalized = driver.normalize_response_body(response.json(), candidate.model_name)
                            print("[normalized]")
                            print(json.dumps(normalized, ensure_ascii=False, indent=2))
                            return 0
                        if response.status_code not in {401, 403, 429, 500, 502, 503, 504}:
                            break
                        if response.status_code in {401, 403, 429} and args.provider_key_id is None:
                            refreshed_keys = await _select_google_provider_keys(
                                session,
                                candidate.model_name,
                                args.provider_key_id,
                            )
                            provider_keys = [
                                refreshed_key
                                for refreshed_key in refreshed_keys
                                if refreshed_key.id not in tried_key_ids
                            ]
                            key_index = 0
                            print("[retry] trying next key")
                            continue
                        key_index += 1
                        print("[retry] trying next key")
                    print("[retry] moving to next strategy")

        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
