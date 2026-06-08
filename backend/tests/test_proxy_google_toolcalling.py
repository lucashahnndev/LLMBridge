import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.database.base import Base
from backend.app.database.models import AppToken, KeyStatus, ProviderKey, UsageLog
from backend.app.schemas.proxy import ChatCompletionRequest
from backend.app.services.crypto import encrypt_text
from backend.app.services.proxy import proxy_chat_completion, proxy_chat_completion_stream


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


class ProxyGoogleToolCallingIntegrationTest(unittest.TestCase):
    def test_google_model_openai_style_tool_calling_is_normalized_and_passthrough_response_is_stable(self) -> None:
        asyncio.run(self._run())

    def test_google_native_tool_calling_response_is_normalized_to_openai_shape(self) -> None:
        asyncio.run(self._run_google_native())

    def test_google_ollama_style_tool_calling_response_is_normalized_to_openai_shape(self) -> None:
        asyncio.run(self._run_ollama_style())

    def test_google_stream_openai_style_tool_calling_passthrough_is_supported(self) -> None:
        asyncio.run(self._run_stream())

    def test_google_stream_native_tool_calling_is_normalized_to_openai_shape(self) -> None:
        asyncio.run(self._run_stream_google_native())

    def test_google_stream_ollama_style_tool_calling_is_normalized(self) -> None:
        asyncio.run(self._run_stream_ollama_style())

    async def _run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "proxy-google.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                app_token = AppToken(
                    name="Atlas",
                    environment="development",
                    token="app-token-1",
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

                captured: dict[str, object] = {}
                upstream_body = {
                    "id": "chatcmpl-tool-1",
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
                        "prompt_tokens": 12,
                        "completion_tokens": 8,
                        "total_tokens": 20,
                    },
                }

                def handler(request: httpx.Request) -> httpx.Response:
                    captured["url"] = str(request.url)
                    captured["headers"] = dict(request.headers)
                    captured["body"] = json.loads(request.content.decode("utf-8"))
                    return httpx.Response(200, json=upstream_body, request=request)

                original_async_client = httpx.AsyncClient

                def client_factory(*args, **kwargs):
                    timeout = kwargs.get("timeout")
                    return original_async_client(transport=httpx.MockTransport(handler), timeout=timeout)

                payload = ChatCompletionRequest(
                    model="google/gemini-3.1-flash",
                    messages=[
                        {
                            "role": "user",
                            "content": "Call the demo tool and return the structured result.",
                        }
                    ],
                    tools=[
                        {
                            "type": "function",
                            "function": {
                                "name": "demo",
                                "description": "Demo tool",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "answer": {"type": "string"},
                                    },
                                    "required": ["answer"],
                                },
                            },
                        }
                    ],
                    tool_choice="required",
                    response_format={"type": "json_object"},
                    parallel_tool_calls=True,
                )

                with patch("backend.app.services.proxy.httpx.AsyncClient", side_effect=client_factory):
                    status_code, body = await proxy_chat_completion(session, app_token, payload)

                self.assertEqual(status_code, 200)
                self.assertEqual(body, upstream_body)

                sent_body = captured["body"]
                self.assertIsInstance(sent_body, dict)
                self.assertEqual(sent_body["model"], "gemini-3-flash-preview")
                self.assertNotIn("response_format", sent_body)
                self.assertNotIn("parallel_tool_calls", sent_body)
                self.assertEqual(sent_body["tool_choice"], "auto")
                self.assertIn("tools", sent_body)
                self.assertEqual(sent_body["tools"][0]["function"]["name"], "demo")
                self.assertTrue(str(captured["url"]).endswith("/chat/completions"))

                result = await session.execute(select(UsageLog).order_by(UsageLog.id.desc()))
                usage_log = result.scalar_one()
                self.assertEqual(usage_log.model_requested, "google/gemini-3.1-flash")
                self.assertEqual(usage_log.provider_used, "google")
                self.assertEqual(usage_log.resolved_model, "google/gemini-3-flash-preview")
                self.assertIsNone(usage_log.queue_name)
                self.assertEqual(usage_log.protocol_in, "openai")
                self.assertEqual(usage_log.protocol_out, "openai")
                self.assertEqual(usage_log.route_kind, "provider")
                self.assertTrue(usage_log.tool_calling)
                self.assertEqual(usage_log.status_code, 200)
                self.assertFalse(usage_log.was_rotated)

            await engine.dispose()

    async def _run_google_native(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "proxy-google-native.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                app_token = AppToken(
                    name="Atlas",
                    environment="development",
                    token="app-token-1",
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

                captured: dict[str, object] = {}
                upstream_native_body = {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [
                                    {"text": "Let me call the tool."},
                                    {
                                        "functionCall": {
                                            "name": "demo",
                                            "args": {"answer": "pong"},
                                        }
                                    },
                                ],
                            },
                            "finishReason": "FUNCTION_CALL",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 12,
                        "candidatesTokenCount": 8,
                        "totalTokenCount": 20,
                    },
                }

                def handler(request: httpx.Request) -> httpx.Response:
                    captured["body"] = json.loads(request.content.decode("utf-8"))
                    return httpx.Response(200, json=upstream_native_body, request=request)

                original_async_client = httpx.AsyncClient

                def client_factory(*args, **kwargs):
                    timeout = kwargs.get("timeout")
                    return original_async_client(transport=httpx.MockTransport(handler), timeout=timeout)

                payload = ChatCompletionRequest(
                    model="google/gemini-3.1-flash",
                    messages=[
                        {
                            "role": "user",
                            "content": "Call the demo tool and return the structured result.",
                        }
                    ],
                    tools=[
                        {
                            "type": "function",
                            "function": {
                                "name": "demo",
                                "description": "Demo tool",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "answer": {"type": "string"},
                                    },
                                    "required": ["answer"],
                                },
                            },
                        }
                    ],
                    tool_choice="required",
                    response_format={"type": "json_object"},
                    parallel_tool_calls=True,
                )

                with patch("backend.app.services.proxy.httpx.AsyncClient", side_effect=client_factory):
                    status_code, body = await proxy_chat_completion(session, app_token, payload)

                self.assertEqual(status_code, 200)
                self.assertIsInstance(body, dict)
                self.assertEqual(body["object"], "chat.completion")
                self.assertEqual(body["model"], "gemini-3-flash-preview")
                self.assertIn("choices", body)
                self.assertEqual(body["choices"][0]["message"]["role"], "assistant")
                self.assertIsNone(body["choices"][0]["message"]["content"])
                self.assertEqual(body["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "demo")
                self.assertEqual(body["choices"][0]["finish_reason"], "tool_calls")
                self.assertEqual(body["usage"]["prompt_tokens"], 12)
                self.assertEqual(body["usage"]["completion_tokens"], 8)
                self.assertEqual(body["usage"]["total_tokens"], 20)

                sent_body = captured["body"]
                self.assertIsInstance(sent_body, dict)
                self.assertEqual(sent_body["model"], "gemini-3-flash-preview")
                self.assertEqual(sent_body["tool_choice"], "auto")
                self.assertNotIn("response_format", sent_body)
                self.assertNotIn("parallel_tool_calls", sent_body)

                result = await session.execute(select(UsageLog).order_by(UsageLog.id.desc()))
                usage_log = result.scalar_one()
                self.assertEqual(usage_log.model_requested, "google/gemini-3.1-flash")
                self.assertEqual(usage_log.resolved_model, "google/gemini-3-flash-preview")
                self.assertEqual(usage_log.status_code, 200)
                self.assertFalse(usage_log.was_rotated)

            await engine.dispose()

    async def _run_ollama_style(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "proxy-google-ollama.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                app_token = AppToken(
                    name="Atlas",
                    environment="development",
                    token="app-token-1",
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

                captured: dict[str, object] = {}
                upstream_ollama_body = {
                    "model": "gemma3",
                    "created_at": "2026-06-08T00:00:00Z",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_ollama_1",
                                "function": {
                                    "name": "demo",
                                    "arguments": {"answer": "pong"},
                                },
                            }
                        ],
                    },
                    "done_reason": "tool_calls",
                    "prompt_eval_count": 12,
                    "eval_count": 8,
                }

                def handler(request: httpx.Request) -> httpx.Response:
                    captured["body"] = json.loads(request.content.decode("utf-8"))
                    return httpx.Response(200, json=upstream_ollama_body, request=request)

                original_async_client = httpx.AsyncClient

                def client_factory(*args, **kwargs):
                    timeout = kwargs.get("timeout")
                    return original_async_client(transport=httpx.MockTransport(handler), timeout=timeout)

                payload = ChatCompletionRequest(
                    model="google/gemini-3.1-flash",
                    messages=[
                        {
                            "role": "user",
                            "content": "Call the demo tool and return the structured result.",
                        }
                    ],
                    tools=[
                        {
                            "type": "function",
                            "function": {
                                "name": "demo",
                                "description": "Demo tool",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "answer": {"type": "string"},
                                    },
                                    "required": ["answer"],
                                },
                            },
                        }
                    ],
                    tool_choice="required",
                    response_format={"type": "json_object"},
                    parallel_tool_calls=True,
                )

                with patch("backend.app.services.proxy.httpx.AsyncClient", side_effect=client_factory):
                    status_code, body = await proxy_chat_completion(session, app_token, payload)

                self.assertEqual(status_code, 200)
                self.assertIsInstance(body, dict)
                self.assertEqual(body["object"], "chat.completion")
                self.assertEqual(body["model"], "gemini-3-flash-preview")
                self.assertEqual(body["choices"][0]["message"]["role"], "assistant")
                self.assertIsNone(body["choices"][0]["message"]["content"])
                self.assertEqual(body["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "demo")
                self.assertEqual(body["choices"][0]["finish_reason"], "tool_calls")
                self.assertEqual(body["usage"]["prompt_tokens"], 12)
                self.assertEqual(body["usage"]["completion_tokens"], 8)
                self.assertEqual(body["usage"]["total_tokens"], 20)

                sent_body = captured["body"]
                self.assertIsInstance(sent_body, dict)
                self.assertEqual(sent_body["model"], "gemini-3-flash-preview")
                self.assertEqual(sent_body["tool_choice"], "auto")
                self.assertNotIn("response_format", sent_body)
                self.assertNotIn("parallel_tool_calls", sent_body)

                result = await session.execute(select(UsageLog).order_by(UsageLog.id.desc()))
                usage_log = result.scalar_one()
                self.assertEqual(usage_log.model_requested, "google/gemini-3.1-flash")
                self.assertEqual(usage_log.resolved_model, "google/gemini-3-flash-preview")
                self.assertEqual(usage_log.status_code, 200)
                self.assertFalse(usage_log.was_rotated)

            await engine.dispose()

    async def _run_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "proxy-google-stream.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                app_token = AppToken(
                    name="Atlas",
                    environment="development",
                    token="app-token-1",
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

                captured: dict[str, object] = {}
                upstream_stream_body = (
                    'data: {"id":"stream-1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant","tool_calls":[{"id":"call_1","type":"function","function":{"name":"demo","arguments":"{\\"answer\\":\\"pong\\"}"}}]},"finish_reason":null}]}\n\n'
                    'data: {"id":"stream-1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}\n\n'
                    'data: [DONE]\n\n'
                ).encode("utf-8")

                def handler(request: httpx.Request) -> httpx.Response:
                    captured["body"] = json.loads(request.content.decode("utf-8"))
                    return httpx.Response(
                        200,
                        content=upstream_stream_body,
                        headers={"content-type": "text/event-stream"},
                        request=request,
                    )

                original_async_client = httpx.AsyncClient

                def client_factory(*args, **kwargs):
                    timeout = kwargs.get("timeout")
                    return original_async_client(transport=httpx.MockTransport(handler), timeout=timeout)

                payload = ChatCompletionRequest(
                    model="google/gemini-3.1-flash",
                    messages=[
                        {
                            "role": "user",
                            "content": "Call the demo tool and return the structured result.",
                        }
                    ],
                    tools=[
                        {
                            "type": "function",
                            "function": {
                                "name": "demo",
                                "description": "Demo tool",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "answer": {"type": "string"},
                                    },
                                    "required": ["answer"],
                                },
                            },
                        }
                    ],
                    tool_choice="required",
                    response_format={"type": "json_object"},
                    parallel_tool_calls=True,
                    stream=True,
                )

                with patch("backend.app.services.proxy.httpx.AsyncClient", side_effect=client_factory):
                    response = await proxy_chat_completion_stream(session, app_token, payload)

                self.assertEqual(response.media_type, "text/event-stream")
                chunks: list[bytes] = []
                async for chunk in response.body_iterator:
                    if isinstance(chunk, str):
                        chunks.append(chunk.encode("utf-8"))
                    else:
                        chunks.append(chunk)
                joined = b"".join(chunks).decode("utf-8")
                payloads = _extract_sse_payloads(joined)
                self.assertGreaterEqual(len(payloads), 2)
                first_event = json.loads(payloads[0])
                self.assertEqual(first_event["object"], "chat.completion.chunk")
                self.assertEqual(first_event["choices"][0]["delta"]["role"], "assistant")
                self.assertIsNone(first_event["choices"][0]["delta"]["content"])
                self.assertEqual(first_event["choices"][0]["delta"]["tool_calls"][0]["function"]["name"], "demo")
                self.assertEqual(first_event["choices"][0]["finish_reason"], "tool_calls")
                second_event = json.loads(payloads[1])
                self.assertEqual(second_event["object"], "chat.completion.chunk")
                self.assertEqual(second_event["choices"][0]["finish_reason"], "tool_calls")
                self.assertEqual(payloads[-1], "[DONE]")

                sent_body = captured["body"]
                self.assertIsInstance(sent_body, dict)
                self.assertEqual(sent_body["model"], "gemini-3-flash-preview")
                self.assertEqual(sent_body["tool_choice"], "auto")
                self.assertNotIn("response_format", sent_body)
                self.assertNotIn("parallel_tool_calls", sent_body)

                result = await session.execute(select(UsageLog).order_by(UsageLog.id.desc()))
                usage_log = result.scalar_one()
                self.assertEqual(usage_log.model_requested, "google/gemini-3.1-flash")
                self.assertEqual(usage_log.resolved_model, "google/gemini-3-flash-preview")
                self.assertEqual(usage_log.status_code, 200)
                self.assertFalse(usage_log.was_rotated)

            await engine.dispose()

    async def _run_stream_google_native(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "proxy-google-stream-native.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                app_token = AppToken(
                    name="Atlas",
                    environment="development",
                    token="app-token-1",
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

                captured: dict[str, object] = {}
                upstream_stream_body = (
                    'data: {"candidates":[{"content":{"role":"model","parts":[{"text":"Thinking..."},{"functionCall":{"name":"demo","args":{"answer":"pong"}}}]},"finishReason":"FUNCTION_CALL"}],"usageMetadata":{"promptTokenCount":12,"candidatesTokenCount":8,"totalTokenCount":20}}\n\n'
                    'data: [DONE]\n\n'
                ).encode("utf-8")

                def handler(request: httpx.Request) -> httpx.Response:
                    captured["body"] = json.loads(request.content.decode("utf-8"))
                    return httpx.Response(
                        200,
                        content=upstream_stream_body,
                        headers={"content-type": "text/event-stream"},
                        request=request,
                    )

                original_async_client = httpx.AsyncClient

                def client_factory(*args, **kwargs):
                    timeout = kwargs.get("timeout")
                    return original_async_client(transport=httpx.MockTransport(handler), timeout=timeout)

                payload = ChatCompletionRequest(
                    model="google/gemini-3.1-flash",
                    messages=[
                        {
                            "role": "user",
                            "content": "Call the demo tool and return the structured result.",
                        }
                    ],
                    tools=[
                        {
                            "type": "function",
                            "function": {
                                "name": "demo",
                                "description": "Demo tool",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "answer": {"type": "string"},
                                    },
                                    "required": ["answer"],
                                },
                            },
                        }
                    ],
                    tool_choice="required",
                    response_format={"type": "json_object"},
                    parallel_tool_calls=True,
                    stream=True,
                )

                with patch("backend.app.services.proxy.httpx.AsyncClient", side_effect=client_factory):
                    response = await proxy_chat_completion_stream(session, app_token, payload)

                self.assertEqual(response.media_type, "text/event-stream")
                chunks: list[bytes] = []
                async for chunk in response.body_iterator:
                    if isinstance(chunk, str):
                        chunks.append(chunk.encode("utf-8"))
                    else:
                        chunks.append(chunk)
                joined = b"".join(chunks).decode("utf-8")
                payloads = _extract_sse_payloads(joined)
                self.assertGreaterEqual(len(payloads), 1)
                first_event = json.loads(payloads[0])
                self.assertEqual(first_event["object"], "chat.completion.chunk")
                self.assertEqual(first_event["model"], "gemini-3-flash-preview")
                self.assertEqual(first_event["choices"][0]["delta"]["role"], "assistant")
                self.assertIsNone(first_event["choices"][0]["delta"]["content"])
                self.assertEqual(first_event["choices"][0]["delta"]["tool_calls"][0]["function"]["name"], "demo")
                self.assertEqual(first_event["choices"][0]["finish_reason"], "tool_calls")
                self.assertIn("[DONE]", payloads[-1])

                sent_body = captured["body"]
                self.assertIsInstance(sent_body, dict)
                self.assertEqual(sent_body["model"], "gemini-3-flash-preview")
                self.assertEqual(sent_body["tool_choice"], "auto")
                self.assertNotIn("response_format", sent_body)
                self.assertNotIn("parallel_tool_calls", sent_body)

                result = await session.execute(select(UsageLog).order_by(UsageLog.id.desc()))
                usage_log = result.scalar_one()
                self.assertEqual(usage_log.model_requested, "google/gemini-3.1-flash")
                self.assertEqual(usage_log.resolved_model, "google/gemini-3-flash-preview")
                self.assertEqual(usage_log.status_code, 200)
                self.assertFalse(usage_log.was_rotated)

            await engine.dispose()

    async def _run_stream_ollama_style(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "proxy-google-stream-ollama.sqlite"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                app_token = AppToken(
                    name="Atlas",
                    environment="development",
                    token="app-token-1",
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

                captured: dict[str, object] = {}
                upstream_stream_body = (
                    'data: {"model":"gemma3","created_at":"2026-06-08T00:00:00Z","message":{"role":"assistant","content":null,"tool_calls":[{"id":"call_ollama_1","function":{"name":"demo","arguments":{"answer":"pong"}}}]},"done_reason":"tool_calls","prompt_eval_count":12,"eval_count":8}\n\n'
                    'data: [DONE]\n\n'
                ).encode("utf-8")

                def handler(request: httpx.Request) -> httpx.Response:
                    captured["body"] = json.loads(request.content.decode("utf-8"))
                    return httpx.Response(
                        200,
                        content=upstream_stream_body,
                        headers={"content-type": "text/event-stream"},
                        request=request,
                    )

                original_async_client = httpx.AsyncClient

                def client_factory(*args, **kwargs):
                    timeout = kwargs.get("timeout")
                    return original_async_client(transport=httpx.MockTransport(handler), timeout=timeout)

                payload = ChatCompletionRequest(
                    model="google/gemini-3.1-flash",
                    messages=[
                        {
                            "role": "user",
                            "content": "Call the demo tool and return the structured result.",
                        }
                    ],
                    tools=[
                        {
                            "type": "function",
                            "function": {
                                "name": "demo",
                                "description": "Demo tool",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "answer": {"type": "string"},
                                    },
                                    "required": ["answer"],
                                },
                            },
                        }
                    ],
                    tool_choice="required",
                    response_format={"type": "json_object"},
                    parallel_tool_calls=True,
                    stream=True,
                )

                with patch("backend.app.services.proxy.httpx.AsyncClient", side_effect=client_factory):
                    response = await proxy_chat_completion_stream(session, app_token, payload)

                self.assertEqual(response.media_type, "text/event-stream")
                chunks: list[bytes] = []
                async for chunk in response.body_iterator:
                    if isinstance(chunk, str):
                        chunks.append(chunk.encode("utf-8"))
                    else:
                        chunks.append(chunk)
                joined = b"".join(chunks).decode("utf-8")
                payloads = _extract_sse_payloads(joined)
                self.assertGreaterEqual(len(payloads), 1)
                first_event = json.loads(payloads[0])
                self.assertEqual(first_event["object"], "chat.completion.chunk")
                self.assertEqual(first_event["choices"][0]["delta"]["role"], "assistant")
                self.assertEqual(first_event["choices"][0]["delta"]["tool_calls"][0]["function"]["name"], "demo")
                self.assertEqual(first_event["choices"][0]["finish_reason"], "tool_calls")
                self.assertEqual(payloads[-1], "[DONE]")

                sent_body = captured["body"]
                self.assertIsInstance(sent_body, dict)
                self.assertEqual(sent_body["model"], "gemini-3-flash-preview")
                self.assertEqual(sent_body["tool_choice"], "auto")
                self.assertNotIn("response_format", sent_body)
                self.assertNotIn("parallel_tool_calls", sent_body)

                result = await session.execute(select(UsageLog).order_by(UsageLog.id.desc()))
                usage_log = result.scalar_one()
                self.assertEqual(usage_log.model_requested, "google/gemini-3.1-flash")
                self.assertEqual(usage_log.resolved_model, "google/gemini-3-flash-preview")
                self.assertEqual(usage_log.status_code, 200)
                self.assertFalse(usage_log.was_rotated)

            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
