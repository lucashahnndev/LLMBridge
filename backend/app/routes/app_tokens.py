from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database.models import AppToken
from backend.app.database.session import get_session
from backend.app.schemas.app_tokens import AppTokenCreate, AppTokenCreateResponse, AppTokenResponse, AppTokenUpdate
from backend.app.services.auth import require_admin
from backend.app.services.records import app_token_create_response, app_token_response
from backend.app.services.tokens import generate_app_token


router = APIRouter(prefix="/app-tokens", tags=["app-tokens"], dependencies=[Depends(require_admin)])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_app_token_or_404(session: AsyncSession, app_token_id: int) -> AppToken:
    app_token = await session.get(AppToken, app_token_id)
    if app_token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="App token not found")
    return app_token


@router.post("", response_model=AppTokenCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_app_token(payload: AppTokenCreate, session: SessionDep) -> AppTokenCreateResponse:
    token = generate_app_token()
    app_token = AppToken(
        name=payload.name,
        environment=payload.environment.value,
        token=token,
        is_active=True,
        rpm_limit=payload.rpm_limit,
    )
    session.add(app_token)
    await session.commit()
    await session.refresh(app_token)
    return app_token_create_response(app_token, token)


@router.get("", response_model=list[AppTokenResponse])
async def list_app_tokens(session: SessionDep, active: bool | None = None) -> list[AppTokenResponse]:
    stmt = select(AppToken).order_by(AppToken.id.desc())
    if active is not None:
        stmt = stmt.where(AppToken.is_active == active)
    result = await session.execute(stmt)
    return [app_token_response(row) for row in result.scalars().all()]


@router.get("/{app_token_id}", response_model=AppTokenResponse)
async def get_app_token(app_token_id: int, session: SessionDep) -> AppTokenResponse:
    app_token = await get_app_token_or_404(session, app_token_id)
    return app_token_response(app_token)


@router.post("/{app_token_id}/peek", response_model=AppTokenCreateResponse)
async def peek_app_token(app_token_id: int, session: SessionDep) -> AppTokenCreateResponse:
    app_token = await get_app_token_or_404(session, app_token_id)
    return app_token_create_response(app_token, app_token.token)


@router.post("/{app_token_id}/rotate", response_model=AppTokenCreateResponse)
async def rotate_app_token(app_token_id: int, session: SessionDep) -> AppTokenCreateResponse:
    app_token = await get_app_token_or_404(session, app_token_id)
    token = generate_app_token()
    app_token.token = token
    await session.commit()
    await session.refresh(app_token)
    return app_token_create_response(app_token, token)


@router.patch("/{app_token_id}", response_model=AppTokenResponse)
async def update_app_token(
    app_token_id: int,
    payload: AppTokenUpdate,
    session: SessionDep,
) -> AppTokenResponse:
    app_token = await get_app_token_or_404(session, app_token_id)
    update_data = payload.model_dump(exclude_unset=True)

    if "environment" in update_data and update_data["environment"] is not None:
        update_data["environment"] = update_data["environment"].value

    for field, value in update_data.items():
        setattr(app_token, field, value)

    await session.commit()
    await session.refresh(app_token)
    return app_token_response(app_token)


@router.delete("/{app_token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app_token(app_token_id: int, session: SessionDep) -> Response:
    app_token = await get_app_token_or_404(session, app_token_id)
    await session.delete(app_token)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
