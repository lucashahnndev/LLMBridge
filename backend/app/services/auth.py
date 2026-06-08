from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.database.models import AdminTokenRevocation
from backend.app.database.session import get_session


security = HTTPBearer(auto_error=False)


def create_admin_token() -> tuple[str, int]:
    settings = get_settings()
    if not settings.secret_key:
        raise RuntimeError("SECRET_KEY is required to sign admin JWTs")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.admin_token_ttl_minutes)
    jti = uuid4().hex
    payload = {
        "sub": "admin",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "scope": "admin",
        "jti": jti,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, settings.admin_token_ttl_minutes


async def get_admin_claims(
    session: Annotated[AsyncSession, Depends(get_session)],
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    settings = get_settings()
    if not settings.secret_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="JWT secret not configured")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc
    if payload.get("scope") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient token scope")
    if session is not None and payload.get("jti"):
        result = await session.execute(
            select(AdminTokenRevocation).where(AdminTokenRevocation.jti == payload["jti"])
        )
        if result.scalar_one_or_none() is not None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")
    return payload


async def require_admin(claims: dict = Depends(get_admin_claims)) -> None:
    _ = claims
