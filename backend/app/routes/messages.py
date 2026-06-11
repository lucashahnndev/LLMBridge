from __future__ import annotations

import codecs
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.database.models import AppToken
from backend.app.database.session import get_session
from backend.app.schemas.anthropic import AnthropicMessagesRequest
from backend.app.services.anthropic import (
    anthropic_error_response,
    anthropic_sse_event,
    anthropic_request_to_chat_completion,
    chat_completion_body_to_anthropic,
)
from backend.app.services.proxy import proxy_chat_completion, proxy_chat_completion_stream, require_app_token
from backend.app.services.trace import ProxyTraceRecorder


router = APIRouter(prefix="/messages", tags=["anthropic"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _extract_sse_payloads(raw_text: str) -> list[str]:
    payloads: list[str] = []
    for block in raw_text.split("\n\n"):
        stripped_block = block.strip()
        if not stripped_block:
            continue
        data_lines: list[str] = []
        for line in stripped_block.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if data_lines:
            payloads.append("\n".join(data_lines).strip())
    return payloads


def _extract_sse_payload_from_block(block: str) -> list[str]:
    stripped_block = block.strip()
    if not stripped_block:
        return []
    data_lines: list[str] = []
    for line in stripped_block.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return []
    return ["\n".join(data_lines).strip()]


def _anthropic_stream_events(message_id: str, model_name: str, openai_stream: StreamingResponse):
    async def generator() -> object:
        sent_block_starts: set[int] = set()
        content_block_index = 0
        current_block_kind: str | None = None
        stop_reason = "end_turn"
        usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        message_started = False
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        buffer = ""

        async def handle_payload(payload: str):
            nonlocal message_started, content_block_index, current_block_kind, stop_reason, usage
            if payload == "[DONE]":
                return
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                return
            if not isinstance(parsed, dict):
                return
            choices = parsed.get("choices")
            if not isinstance(choices, list) or not choices:
                return
            choice = choices[0] if isinstance(choices[0], dict) else {}
            delta = choice.get("delta") if isinstance(choice, dict) else None
            if not message_started:
                message_started = True
                yield anthropic_sse_event(
                    "message_start",
                    {
                        "type": "message_start",
                        "message": {
                            "id": message_id,
                            "type": "message",
                            "role": "assistant",
                            "model": model_name,
                            "content": [],
                            "stop_reason": None,
                            "stop_sequence": None,
                            "usage": {
                                "input_tokens": 0,
                                "output_tokens": 0,
                            },
                        },
                    },
                )
            if isinstance(delta, dict):
                text = delta.get("content")
                tool_calls = delta.get("tool_calls")
                if isinstance(text, str) and text:
                    if current_block_kind != "text":
                        if content_block_index not in sent_block_starts:
                            sent_block_starts.add(content_block_index)
                            yield anthropic_sse_event(
                                "content_block_start",
                                {
                                    "type": "content_block_start",
                                    "index": content_block_index,
                                    "content_block": {
                                        "type": "text",
                                        "text": "",
                                    },
                                },
                            )
                        current_block_kind = "text"
                    yield anthropic_sse_event(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": content_block_index,
                            "delta": {
                                "type": "text_delta",
                                "text": text,
                            },
                        },
                    )

                if isinstance(tool_calls, list) and tool_calls:
                    if current_block_kind == "text":
                        content_block_index += 1
                    for tool_call in tool_calls:
                        if not isinstance(tool_call, dict):
                            continue
                        function = tool_call.get("function")
                        if not isinstance(function, dict):
                            continue
                        tool_name = function.get("name")
                        if not isinstance(tool_name, str) or not tool_name.strip():
                            continue
                        if content_block_index not in sent_block_starts:
                            sent_block_starts.add(content_block_index)
                            yield anthropic_sse_event(
                                "content_block_start",
                                {
                                    "type": "content_block_start",
                                    "index": content_block_index,
                                    "content_block": {
                                        "type": "tool_use",
                                        "id": tool_call.get("id") or f"tool_{content_block_index}",
                                        "name": tool_name.strip(),
                                        "input": {},
                                    },
                                },
                            )
                        yield anthropic_sse_event(
                            "content_block_delta",
                            {
                                "type": "content_block_delta",
                                "index": content_block_index,
                                "delta": {
                                    "type": "input_json_delta",
                                    "partial_json": function.get("arguments") or "{}",
                                },
                            },
                        )
                        current_block_kind = "tool_use"
                        content_block_index += 1

            finish_reason = choice.get("finish_reason")
            if isinstance(finish_reason, str) and finish_reason:
                stop_reason = {
                    "stop": "end_turn",
                    "length": "max_tokens",
                    "tool_calls": "tool_use",
                    "function_call": "tool_use",
                    "content_filter": "refusal",
                }.get(finish_reason, stop_reason)

            if isinstance(parsed.get("usage"), dict):
                usage_payload = parsed["usage"]
                usage["input_tokens"] = int(usage_payload.get("prompt_tokens") or usage["input_tokens"])
                usage["output_tokens"] = int(usage_payload.get("completion_tokens") or usage["output_tokens"])

        try:
            async for chunk in openai_stream.body_iterator:
                if isinstance(chunk, bytes):
                    chunk_text = decoder.decode(chunk)
                else:
                    chunk_text = str(chunk)
                buffer += chunk_text
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    for payload in _extract_sse_payload_from_block(block):
                        async for event in handle_payload(payload):
                            yield event

            tail = decoder.decode(b"", final=True)
            if tail:
                buffer += tail
            if buffer.strip():
                for payload in _extract_sse_payload_from_block(buffer):
                    async for event in handle_payload(payload):
                        yield event

            if message_started:
                for index in sorted(sent_block_starts):
                    yield anthropic_sse_event(
                        "content_block_stop",
                        {
                            "type": "content_block_stop",
                            "index": index,
                        },
                    )
                yield anthropic_sse_event(
                    "message_delta",
                    {
                        "type": "message_delta",
                        "delta": {
                            "stop_reason": stop_reason,
                            "stop_sequence": None,
                        },
                        "usage": {
                            "output_tokens": usage["output_tokens"],
                        },
                    },
                )
                yield anthropic_sse_event(
                    "message_stop",
                    {
                        "type": "message_stop",
                    },
                )
        finally:
            if hasattr(openai_stream, "close"):
                close_result = openai_stream.close()
                if hasattr(close_result, "__await__"):
                    await close_result

    return generator


@router.post("")
async def messages(
    payload: AnthropicMessagesRequest,
    session: SessionDep,
    request: Request,
    app_token: Annotated[AppToken, Depends(require_app_token)],
):
    if not payload.model.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="model is required")

    settings = get_settings()
    trace = ProxyTraceRecorder.from_settings(settings)
    chat_payload = anthropic_request_to_chat_completion(payload)
    client = request.app.state.http_client

    if payload.stream:
        openai_stream = await proxy_chat_completion_stream(
            session=session,
            app_token=app_token,
            payload=chat_payload,
            client=client,
            protocol_in="anthropic",
            protocol_out="anthropic",
            trace=trace,
        )
        generator = _anthropic_stream_events(message_id=f"msg_{payload.model.replace('/', '_')}", model_name=payload.model, openai_stream=openai_stream)
        return StreamingResponse(generator(), media_type="text/event-stream")
    status_code, body = await proxy_chat_completion(
        session=session,
        app_token=app_token,
        payload=chat_payload,
        client=client,
        protocol_in="anthropic",
        protocol_out="anthropic",
        trace=trace,
    )
    if status_code >= 400:
        message = "Proxy request failed"
        if isinstance(body, dict):
            detail = body.get("detail")
            if isinstance(detail, str) and detail.strip():
                message = detail
            else:
                error = body.get("error")
                if isinstance(error, dict):
                    error_message = error.get("message")
                    if isinstance(error_message, str) and error_message.strip():
                        message = error_message
        elif isinstance(body, str) and body.strip():
            message = body
        if trace.enabled:
            trace.record_final_response(status_code=status_code, body=body)
            trace.write()
        return JSONResponse(
            status_code=status_code,
            content=anthropic_error_response(message),
        )

    if not isinstance(body, dict):
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=anthropic_error_response("Proxy returned an unsupported response shape"),
        )

    anthropic_body = chat_completion_body_to_anthropic(body, payload.model)
    if trace.enabled:
        trace.record_final_response(status_code=status_code, body=anthropic_body)
        trace.write()
    return JSONResponse(
        status_code=status_code,
        content=anthropic_body,
    )
