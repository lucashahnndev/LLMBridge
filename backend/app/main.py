from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.core.version import APP_VERSION
from backend.app.core.config import get_settings
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


settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_database()
    yield


app = FastAPI(title=settings.app_name, version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=False,
    allow_methods=["*"],
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
