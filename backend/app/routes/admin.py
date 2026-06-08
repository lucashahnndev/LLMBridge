from fastapi import APIRouter, Depends

from backend.app.schemas.runtime import RuntimeConfigResponse, RuntimeConfigUpdate
from backend.app.services.auth import require_admin
from backend.app.services.runtime import read_runtime_config, update_runtime_config


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/runtime", response_model=RuntimeConfigResponse)
async def get_runtime_config() -> RuntimeConfigResponse:
    return read_runtime_config()


@router.patch("/runtime", response_model=RuntimeConfigResponse)
async def patch_runtime_config(payload: RuntimeConfigUpdate) -> RuntimeConfigResponse:
    return update_runtime_config(host=payload.host, port=payload.port)
