import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database.base import Base
from backend.app.database.models import AppToken, KeyStatus, ProviderKey
from backend.app.routes.messages import messages as anthropic_messages_route
from backend.app.schemas.anthropic import AnthropicMessagesRequest
from backend.app.services.crypto import encrypt_text


class AnthropicAdapterTest(unittest.TestCase):
    def test_anthropic_route_converts_openai_tool_calling_response(self) -> None:
        asyncio.run(self._run_non_stream())

    def test_anthropic_route_streams_openai_style_sse_as_anthropic_events(self) -> None:
        asyncio.run(self._run_stream())

    def test_anthropic_route_handles_split_sse_chunks_without_losing_text(self) -> None:
        asyncio.run(self._run_split_stream())

    def test_anthropic_route_separates_text_and_tool_use_blocks_in_one_chunk(self) -> None:
        asyncio.run(self._run_mixed_stream())

    async def _create_session(self):
        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / "anthropic-adapter.sqlite"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session = session_factory()
        app_token = AppToken(
            name="Claude",
            environment="development",
            token="app-token-anthropic",
            is_active=True,
            rpm_limit=None,
        )
        provider_key = ProviderKey(
            name="Google primary",
            description=None,
            provider="google",
            encrypted_token=encrypt_text("google-secret"),
            status=KeyStatus.ACTIVE,
            blocked_until=None,
            failure_count=0,
        )
        session.add_all([app_token, provider_key])
        await session.commit()
        return temp_dir, engine, session, app_token

    def _make_request(self):
        return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(http_client=None)))

    async def _run_non_stream(self) -> None:
        temp_dir, engine, session, app_token = await self._create_session()
        try:
            upstream_body = {
                "id": "chatcmpl-anthropic-1",
                "object": "chat.completion",
                "created": 1_719_000_000,
                "model": "gemini-3-flash-preview",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "demo",
                                        "arguments": "{\"answer\":\"pong\"}",
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 7,
                    "total_tokens": 17,
                },
            }

            async def fake_proxy_chat_completion(*args, **kwargs):
                _ = args, kwargs
                self.assertEqual(kwargs["protocol_in"], "anthropic")
                self.assertEqual(kwargs["protocol_out"], "anthropic")
                return 200, upstream_body

            payload = AnthropicMessagesRequest(
                model="google/gemini-3.1-flash",
                max_tokens=512,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Call the demo tool."},
                        ],
                    }
                ],
                tools=[
                    {
                        "name": "demo",
                        "description": "Demo tool",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "answer": {"type": "string"},
                            },
                            "required": ["answer"],
                        },
                    }
                ],
                tool_choice={"type": "tool", "name": "demo"},
                system="You are a helpful assistant.",
            )

            request = self._make_request()

            with patch("backend.app.routes.messages.proxy_chat_completion", side_effect=fake_proxy_chat_completion):
                response = await anthropic_messages_route(payload, session, request, app_token)

            self.assertEqual(response.status_code, 200)
            body = json.loads(response.body.decode("utf-8"))
            self.assertEqual(body["type"], "message")
            self.assertEqual(body["role"], "assistant")
            self.assertEqual(body["stop_reason"], "tool_use")
            self.assertEqual(body["usage"]["input_tokens"], 10)
            self.assertEqual(body["usage"]["output_tokens"], 7)
            self.assertEqual(body["content"][0]["type"], "tool_use")
            self.assertEqual(body["content"][0]["name"], "demo")
            self.assertEqual(body["content"][0]["input"]["answer"], "pong")
        finally:
            await session.close()
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_stream(self) -> None:
        temp_dir, engine, session, app_token = await self._create_session()
        try:
            async def upstream_stream():
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "id": "chatcmpl-stream-1",
                            "object": "chat.completion.chunk",
                            "created": 1_719_000_000,
                            "model": "gemini-3-flash-preview",
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"role": "assistant", "content": "Hello "},
                                    "finish_reason": None,
                                }
                            ],
                        }
                    )
                    + "\n\n"
                )
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "id": "chatcmpl-stream-1",
                            "object": "chat.completion.chunk",
                            "created": 1_719_000_001,
                            "model": "gemini-3-flash-preview",
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": "world"},
                                    "finish_reason": "tool_calls",
                                }
                            ],
                            "usage": {
                                "prompt_tokens": 8,
                                "completion_tokens": 4,
                                "total_tokens": 12,
                            },
                        }
                    )
                    + "\n\n"
                )
                yield "data: [DONE]\n\n"

            openai_stream = httpx.Response(
                200,
                request=httpx.Request("POST", "http://test/chat/completions"),
                content=b"",
            )
            openai_stream = openai_stream  # satisfy type checker / local readability

            class FakeStreamResponse:
                def __init__(self) -> None:
                    self.body_iterator = upstream_stream()

            async def fake_proxy_chat_completion_stream(*args, **kwargs):
                _ = args, kwargs
                self.assertEqual(kwargs["protocol_in"], "anthropic")
                self.assertEqual(kwargs["protocol_out"], "anthropic")
                return FakeStreamResponse()

            payload = AnthropicMessagesRequest(
                model="google/gemini-3.1-flash",
                max_tokens=512,
                stream=True,
                messages=[
                    {
                        "role": "user",
                        "content": "Say hello.",
                    }
                ],
            )

            request = self._make_request()

            with patch("backend.app.routes.messages.proxy_chat_completion_stream", side_effect=fake_proxy_chat_completion_stream):
                response = await anthropic_messages_route(payload, session, request, app_token)

            self.assertEqual(response.media_type, "text/event-stream")
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                if isinstance(chunk, bytes):
                    chunks.append(chunk.decode("utf-8"))
                else:
                    chunks.append(str(chunk))
            payload_text = "".join(chunks)
            self.assertIn("event: message_start", payload_text)
            self.assertIn("event: content_block_start", payload_text)
            self.assertIn("event: message_delta", payload_text)
            self.assertIn("event: message_stop", payload_text)
        finally:
            await session.close()
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_split_stream(self) -> None:
        temp_dir, engine, session, app_token = await self._create_session()
        try:
            chunk_one = (
                "data: "
                + json.dumps(
                    {
                        "id": "chatcmpl-stream-2",
                        "object": "chat.completion.chunk",
                        "created": 1_719_000_010,
                        "model": "gemini-3-flash-preview",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"role": "assistant", "content": "Hello "},
                                "finish_reason": None,
                            }
                        ],
                    }
                )
            )
            chunk_two = (
                "\n\n"
                + "data: "
                + json.dumps(
                    {
                        "id": "chatcmpl-stream-2",
                        "object": "chat.completion.chunk",
                        "created": 1_719_000_011,
                        "model": "gemini-3-flash-preview",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": "world"},
                                "finish_reason": "stop",
                            }
                        ],
                    }
                )
                + "\n\n"
                + "data: [DONE]\n\n"
            )

            async def upstream_stream():
                yield chunk_one[: len(chunk_one) // 2].encode("utf-8")
                yield chunk_one[len(chunk_one) // 2 :].encode("utf-8")
                yield chunk_two[: len(chunk_two) // 3].encode("utf-8")
                yield chunk_two[len(chunk_two) // 3 :].encode("utf-8")

            class FakeStreamResponse:
                def __init__(self) -> None:
                    self.body_iterator = upstream_stream()

            async def fake_proxy_chat_completion_stream(*args, **kwargs):
                _ = args, kwargs
                return FakeStreamResponse()

            payload = AnthropicMessagesRequest(
                model="google/gemini-3.1-flash",
                max_tokens=256,
                stream=True,
                messages=[
                    {
                        "role": "user",
                        "content": "Say hello.",
                    }
                ],
            )

            request = self._make_request()

            with patch("backend.app.routes.messages.proxy_chat_completion_stream", side_effect=fake_proxy_chat_completion_stream):
                response = await anthropic_messages_route(payload, session, request, app_token)

            chunks: list[str] = []
            async for chunk in response.body_iterator:
                if isinstance(chunk, bytes):
                    chunks.append(chunk.decode("utf-8"))
                else:
                    chunks.append(str(chunk))

            payload_text = "".join(chunks)
            self.assertIn("event: message_start", payload_text)
            self.assertIn("event: content_block_delta", payload_text)
            self.assertIn("event: message_stop", payload_text)
            self.assertIn("Hello ", payload_text)
            self.assertIn("world", payload_text)
        finally:
            await session.close()
            await engine.dispose()
            temp_dir.cleanup()

    async def _run_mixed_stream(self) -> None:
        temp_dir, engine, session, app_token = await self._create_session()
        try:
            async def upstream_stream():
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "id": "chatcmpl-stream-3",
                            "object": "chat.completion.chunk",
                            "created": 1_719_000_020,
                            "model": "gemini-3-flash-preview",
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "role": "assistant",
                                        "content": "Thinking before the tool call.",
                                        "tool_calls": [
                                            {
                                                "id": "call_3",
                                                "type": "function",
                                                "function": {
                                                    "name": "demo",
                                                    "arguments": "{\"answer\":\"pong\"}",
                                                },
                                            }
                                        ],
                                    },
                                    "finish_reason": "tool_calls",
                                }
                            ],
                        }
                    )
                    + "\n\n"
                )
                yield "data: [DONE]\n\n"

            class FakeStreamResponse:
                def __init__(self) -> None:
                    self.body_iterator = upstream_stream()

            async def fake_proxy_chat_completion_stream(*args, **kwargs):
                _ = args, kwargs
                self.assertEqual(kwargs["protocol_in"], "anthropic")
                self.assertEqual(kwargs["protocol_out"], "anthropic")
                return FakeStreamResponse()

            payload = AnthropicMessagesRequest(
                model="google/gemini-3.1-flash",
                max_tokens=256,
                stream=True,
                messages=[
                    {
                        "role": "user",
                        "content": "Call the demo tool and keep text separate from the tool block.",
                    }
                ],
            )

            request = self._make_request()

            with patch("backend.app.routes.messages.proxy_chat_completion_stream", side_effect=fake_proxy_chat_completion_stream):
                response = await anthropic_messages_route(payload, session, request, app_token)

            chunks: list[str] = []
            async for chunk in response.body_iterator:
                if isinstance(chunk, bytes):
                    chunks.append(chunk.decode("utf-8"))
                else:
                    chunks.append(str(chunk))

            payload_text = "".join(chunks)
            self.assertIn("event: message_start", payload_text)
            self.assertGreaterEqual(payload_text.count("event: content_block_start"), 2)
            self.assertIn("Thinking before the tool call.", payload_text)
            self.assertIn('"type": "tool_use"', payload_text)
            self.assertIn("event: message_stop", payload_text)
        finally:
            await session.close()
            await engine.dispose()
            temp_dir.cleanup()
