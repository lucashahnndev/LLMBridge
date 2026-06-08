from fastapi import APIRouter

from backend.app.core.version import APP_VERSION, SCHEMA_VERSION
from backend.app.core.config import get_settings
from backend.app.schemas.common import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
    }
