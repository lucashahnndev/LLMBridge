from contextlib import asynccontextmanager
import logging
import time
import uuid

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request

from backend.app.core.version import APP_VERSION
from backend.app.core.config import get_settings
from backend.app.core.logging import (
    clear_request_context,
    request_body_ctx,
    set_request_context,
    setup_logging,
    summarize_debug_payload,
)
from backend.app.database.bootstrap import ensure_database
from backend.app.routes.auth import router as auth_router
from backend.app.routes.app_tokens import router as app_tokens_router
from backend.app.routes.admin import router as admin_router
from backend.app.routes.health import router as health_router
from backend.app.routes.messages import router as anthropic_router
from backend.app.routes.observability import router as observability_router
from backend.app.routes.model_queues import router as model_queues_router
from backend.app.routes.proxy import router as proxy_router
from backend.app.routes.provider_keys import router as provider_keys_router
from backend.app.routes.usage_logs import router as usage_logs_router
from backend.app.database.session import get_sessionmaker
from backend.app.services.route_materializer import warmup_route_materializer
from backend.app.services.cors import build_local_frontend_origins
from backend.app.services.telegram_bot import create_telegram_bot_worker


settings = get_settings()
setup_logging(settings)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_database()
    timeout = httpx.Timeout(settings.proxy_timeout_seconds)
    limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
    http_client = httpx.AsyncClient(timeout=timeout, limits=limits)
    telegram_bot_worker = create_telegram_bot_worker(get_sessionmaker())
    await telegram_bot_worker.start()
    await warmup_route_materializer()
    app.state.http_client = http_client
    app.state.telegram_bot_worker = telegram_bot_worker
    yield
    await http_client.aclose()
    await telegram_bot_worker.stop()


app = FastAPI(title=settings.app_name, version=APP_VERSION, lifespan=lifespan)

cors_allowed_origins = build_local_frontend_origins(
    frontend_host=settings.frontend_host,
    frontend_port=settings.frontend_port,
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    client = request.client.host if request.client and request.client.host else "-"
    set_request_context(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        client=client,
    )
    start = time.perf_counter()
    logger.info("request start")

    debug_key = settings.logging_control_key.strip()
    debug_enabled = bool(debug_key) and request.headers.get("x-logging-key") == debug_key
    trace_enabled = bool(settings.trace_proxy_enabled)
    if (debug_enabled or trace_enabled) and request.method in {"POST", "PUT", "PATCH"}:
        body = await request.body()
        if body:
            decoded_body = body.decode("utf-8", errors="replace")
            request_body_ctx.set(decoded_body)
            if debug_enabled:
                logger.debug("request body %s", summarize_debug_payload(body))
        else:
            request_body_ctx.set(None)
        request._body = body  # type: ignore[attr-defined]

    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request failed")
        clear_request_context()
        raise

    duration_ms = (time.perf_counter() - start) * 1000.0
    response.headers["X-Request-Id"] = request_id
    logger.info("request end status=%s duration_ms=%.2f", response.status_code, duration_ms)
    clear_request_context()
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins,
    allow_credentials=False,
    allow_methods=["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(provider_keys_router, prefix="/api/v1")
app.include_router(app_tokens_router, prefix="/api/v1")
app.include_router(model_queues_router, prefix="/api/v1")
app.include_router(usage_logs_router, prefix="/api/v1")
app.include_router(observability_router, prefix="/api/v1")
app.include_router(anthropic_router, prefix="/v1")
app.include_router(proxy_router, prefix="/v1")
