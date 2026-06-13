from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from passlib.context import CryptContext

from backend.app.core.config import get_settings
from backend.app.database.models import AdminAuthState, AdminTokenRevocation
from backend.app.database.session import get_session


security = HTTPBearer(auto_error=False)
password_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


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


def hash_admin_password(password: str) -> str:
    return password_context.hash(password)


def verify_admin_password_hash(password: str, hashed_password: str) -> bool:
    return password_context.verify(password, hashed_password)


async def get_admin_auth_state(session: AsyncSession) -> AdminAuthState | None:
    result = await session.execute(select(AdminAuthState).where(AdminAuthState.key == "admin"))
    return result.scalar_one_or_none()


async def set_admin_password(session: AsyncSession, password: str) -> AdminAuthState:
    auth_state = await get_admin_auth_state(session)
    hashed_password = hash_admin_password(password)
    if auth_state is None:
        auth_state = AdminAuthState(key="admin", password_hash=hashed_password)
        session.add(auth_state)
    else:
        auth_state.password_hash = hashed_password

    await session.commit()
    await session.refresh(auth_state)
    return auth_state


async def is_admin_password_configured(session: AsyncSession) -> bool:
    auth_state = await get_admin_auth_state(session)
    return bool(auth_state and auth_state.password_hash)


async def is_admin_setup_required(session: AsyncSession) -> bool:
    settings = get_settings()
    return not settings.admin_password.strip() and not await is_admin_password_configured(session)


async def verify_admin_login_password(session: AsyncSession, password: str) -> bool:
    settings = get_settings()
    if settings.admin_password and password == settings.admin_password:
        return True

    auth_state = await get_admin_auth_state(session)
    if auth_state and auth_state.password_hash:
        return verify_admin_password_hash(password, auth_state.password_hash)

    return False


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
