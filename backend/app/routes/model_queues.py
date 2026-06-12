from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database.models import ModelQueue, ModelQueueCandidate, QueueStrategy
from backend.app.database.session import get_session
from backend.app.schemas.model_queues import (
    ModelQueueCandidateCreate,
    ModelQueueCandidateResponse,
    ModelQueueCandidateUpdate,
    ModelQueueCreate,
    ModelQueueResponse,
    ModelQueueUpdate,
)
from backend.app.services.auth import require_admin
from backend.app.services.records import model_queue_candidate_response, model_queue_response
from backend.app.services.route_materializer import schedule_route_materializer_refresh_all


router = APIRouter(prefix="/model-queues", tags=["model-queues"], dependencies=[Depends(require_admin)])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_model_queue_or_404(session: AsyncSession, queue_id: int) -> ModelQueue:
    queue = await session.get(ModelQueue, queue_id)
    if queue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model queue not found")
    return queue


async def get_model_queue_candidate_or_404(session: AsyncSession, candidate_id: int) -> ModelQueueCandidate:
    candidate = await session.get(ModelQueueCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model queue candidate not found")
    return candidate


@router.post("", response_model=ModelQueueResponse, status_code=status.HTTP_201_CREATED)
async def create_model_queue(payload: ModelQueueCreate, session: SessionDep) -> ModelQueueResponse:
    queue = ModelQueue(
        name=payload.name,
        description=payload.description,
        strategy=QueueStrategy(payload.strategy.value),
        is_active=True,
    )
    session.add(queue)
    await session.commit()
    await session.refresh(queue)
    schedule_route_materializer_refresh_all()
    return model_queue_response(queue)


@router.get("", response_model=list[ModelQueueResponse])
async def list_model_queues(session: SessionDep) -> list[ModelQueueResponse]:
    stmt = select(ModelQueue).order_by(ModelQueue.id.desc())
    result = await session.execute(stmt)
    queues = list(result.scalars().all())
    for queue in queues:
        await session.refresh(queue, attribute_names=["candidates"])
    return [model_queue_response(queue) for queue in queues]


@router.get("/{queue_id}", response_model=ModelQueueResponse)
async def get_model_queue(queue_id: int, session: SessionDep) -> ModelQueueResponse:
    queue = await get_model_queue_or_404(session, queue_id)
    await session.refresh(queue, attribute_names=["candidates"])
    return model_queue_response(queue)


@router.patch("/{queue_id}", response_model=ModelQueueResponse)
async def update_model_queue(
    queue_id: int,
    payload: ModelQueueUpdate,
    session: SessionDep,
) -> ModelQueueResponse:
    queue = await get_model_queue_or_404(session, queue_id)
    update_data = payload.model_dump(exclude_unset=True)
    if "strategy" in update_data and update_data["strategy"] is not None:
        update_data["strategy"] = QueueStrategy(update_data["strategy"].value)
    for field, value in update_data.items():
        setattr(queue, field, value)
    await session.commit()
    await session.refresh(queue)
    await session.refresh(queue, attribute_names=["candidates"])
    schedule_route_materializer_refresh_all()
    return model_queue_response(queue)


@router.delete("/{queue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_queue(queue_id: int, session: SessionDep) -> Response:
    queue = await get_model_queue_or_404(session, queue_id)
    await session.delete(queue)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{queue_id}/candidates", response_model=ModelQueueCandidateResponse, status_code=status.HTTP_201_CREATED)
async def create_model_queue_candidate(
    queue_id: int,
    payload: ModelQueueCandidateCreate,
    session: SessionDep,
) -> ModelQueueCandidateResponse:
    queue = await get_model_queue_or_404(session, queue_id)
    candidate = ModelQueueCandidate(
        queue_id=queue.id,
        provider=payload.provider,
        model_name=payload.model_name,
        position=payload.position,
        is_active=payload.is_active,
    )
    session.add(candidate)
    await session.commit()
    await session.refresh(candidate)
    schedule_route_materializer_refresh_all()
    return model_queue_candidate_response(candidate)


@router.patch("/candidates/{candidate_id}", response_model=ModelQueueCandidateResponse)
async def update_model_queue_candidate(
    candidate_id: int,
    payload: ModelQueueCandidateUpdate,
    session: SessionDep,
) -> ModelQueueCandidateResponse:
    candidate = await get_model_queue_candidate_or_404(session, candidate_id)
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(candidate, field, value)
    await session.commit()
    await session.refresh(candidate)
    schedule_route_materializer_refresh_all()
    return model_queue_candidate_response(candidate)


@router.delete("/candidates/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_queue_candidate(candidate_id: int, session: SessionDep) -> Response:
    candidate = await get_model_queue_candidate_or_404(session, candidate_id)
    await session.delete(candidate)
    await session.commit()
    schedule_route_materializer_refresh_all()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
