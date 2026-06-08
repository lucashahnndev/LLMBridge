from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.database.models import AdminTokenRevocation
from backend.app.database.session import get_session
from backend.app.schemas.auth import AdminLoginRequest, AdminLoginResponse, AdminLogoutResponse, AdminProfileResponse
from backend.app.services.auth import create_admin_token, get_admin_claims, require_admin


router = APIRouter(prefix="/auth", tags=["auth"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("/login", response_model=AdminLoginResponse)
async def login(payload: AdminLoginRequest) -> AdminLoginResponse:
    settings = get_settings()
    if not settings.admin_password:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Admin password not configured")
    if payload.password != settings.admin_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin password")
    token, expires_in = create_admin_token()
    return AdminLoginResponse(access_token=token, expires_in_minutes=expires_in)


@router.get("/me", response_model=AdminProfileResponse, dependencies=[Depends(require_admin)])
async def me() -> AdminProfileResponse:
    return AdminProfileResponse(authenticated=True)


@router.post("/logout", response_model=AdminLogoutResponse)
async def logout(
    claims: Annotated[dict, Depends(get_admin_claims)],
    session: SessionDep,
) -> AdminLogoutResponse:
    jti = claims.get("jti")
    expires_at = claims.get("exp")
    if not jti or not expires_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token missing revocation claims")

    result = await session.execute(select(AdminTokenRevocation).where(AdminTokenRevocation.jti == jti))
    if result.scalar_one_or_none() is None:
        revocation = AdminTokenRevocation(
            jti=jti,
            expires_at=datetime.fromtimestamp(int(expires_at), tz=timezone.utc),
        )
        session.add(revocation)
        await session.commit()

    return AdminLogoutResponse(revoked=True)
