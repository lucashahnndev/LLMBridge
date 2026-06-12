from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable

import httpx


GOOGLE_RETRY_PATTERN = re.compile(r"please retry in\s+([0-9]+(?:\.[0-9]+)?)\s*(ms|s)\b", re.IGNORECASE)


@dataclass(frozen=True)
class RetryCooldownResult:
    retry_after_seconds: float
    cooldown_until: datetime
    source: str
    evidence: str | None = None


def _utc_now(now: datetime | None = None) -> datetime:
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        return reference.replace(tzinfo=timezone.utc)
    return reference.astimezone(timezone.utc)


def _result_from_delay(delay_seconds: float, *, now: datetime, source: str, evidence: str | None = None) -> RetryCooldownResult | None:
    if delay_seconds < 0:
        return None
    return RetryCooldownResult(
        retry_after_seconds=delay_seconds,
        cooldown_until=now + timedelta(seconds=delay_seconds),
        source=source,
        evidence=evidence,
    )


def _extract_text_fragments(body: dict[str, object] | list[object] | str | None) -> Iterable[str]:
    if body is None:
        return
    if isinstance(body, str):
        cleaned = body.strip()
        if cleaned:
            yield cleaned
        return
    if isinstance(body, list):
        for entry in body:
            yield from _extract_text_fragments(entry if isinstance(entry, (dict, list, str)) else str(entry))
        return
    if isinstance(body, dict):
        for key in ("detail", "message"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                yield value.strip()
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                yield message.strip()
        for value in body.values():
            if isinstance(value, (dict, list)):
                yield from _extract_text_fragments(value)


def _parse_headers(headers: httpx.Headers, *, now: datetime) -> RetryCooldownResult | None:
    retry_after = headers.get("retry-after")
    if retry_after:
        retry_after = retry_after.strip()
        if retry_after.isdigit():
            return _result_from_delay(float(retry_after), now=now, source="retry-after", evidence=retry_after)
        try:
            retry_at = parsedate_to_datetime(retry_after)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            seconds = (retry_at.astimezone(timezone.utc) - now).total_seconds()
            return _result_from_delay(seconds, now=now, source="retry-after-date", evidence=retry_after)
        except (TypeError, ValueError, IndexError):
            pass

    reset_after = headers.get("x-ratelimit-reset-after")
    if reset_after:
        try:
            return _result_from_delay(float(reset_after), now=now, source="x-ratelimit-reset-after", evidence=reset_after)
        except ValueError:
            pass

    reset_at = headers.get("x-ratelimit-reset")
    if reset_at:
        try:
            reset_dt = datetime.fromtimestamp(float(reset_at), tz=timezone.utc)
            seconds = (reset_dt - now).total_seconds()
            return _result_from_delay(seconds, now=now, source="x-ratelimit-reset", evidence=reset_at)
        except ValueError:
            pass

    return None


def _parse_google_retry(body: dict[str, object] | list[object] | str | None, *, now: datetime) -> RetryCooldownResult | None:
    for fragment in _extract_text_fragments(body):
        match = GOOGLE_RETRY_PATTERN.search(fragment)
        if not match:
            continue
        value = float(match.group(1))
        unit = match.group(2).lower()
        delay_seconds = value / 1000.0 if unit == "ms" else value
        result = _result_from_delay(delay_seconds, now=now, source="google-retry-message", evidence=fragment)
        if result is not None:
            return result
    return None


def parse_retry_cooldown(
    headers: httpx.Headers,
    *,
    body: dict[str, object] | list[object] | str | None = None,
    provider: str | None = None,
    now: datetime | None = None,
) -> RetryCooldownResult | None:
    reference_now = _utc_now(now)
    header_result = _parse_headers(headers, now=reference_now)
    if header_result is not None:
        return header_result

    normalized_provider = (provider or "").strip().lower()
    if normalized_provider == "google":
        return _parse_google_retry(body, now=reference_now)
    return None


def parse_retry_after_seconds(
    headers: httpx.Headers,
    *,
    body: dict[str, object] | list[object] | str | None = None,
    provider: str | None = None,
    now: datetime | None = None,
) -> int | None:
    result = parse_retry_cooldown(headers, body=body, provider=provider, now=now)
    if result is None:
        return None
    return max(1, int(math.ceil(result.retry_after_seconds)))
