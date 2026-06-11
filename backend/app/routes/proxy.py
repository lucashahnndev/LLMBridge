from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database.models import AppToken
from backend.app.database.session import get_session
from backend.app.schemas.proxy import ChatCompletionRequest
from backend.app.services.proxy import proxy_chat_completion, proxy_chat_completion_stream, require_app_token


router = APIRouter(prefix="/chat", tags=["proxy"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("/completions")
async def chat_completions(
    payload: ChatCompletionRequest,
    session: SessionDep,
    request: Request,
    app_token: Annotated[AppToken, Depends(require_app_token)],
):
    client = request.app.state.http_client
    if payload.stream:
        return await proxy_chat_completion_stream(
            session=session,
            app_token=app_token,
            payload=payload,
            client=client,
        )

    status_code, body = await proxy_chat_completion(
        session=session,
        app_token=app_token,
        payload=payload,
        client=client,
    )
    return JSONResponse(status_code=status_code, content=body)
