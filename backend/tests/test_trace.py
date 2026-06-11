from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.core.config import Settings
from backend.app.core.logging import clear_request_context, request_body_ctx
from backend.app.database.base import Base
from backend.app.database.models import AppToken, KeyStatus, ProviderKey
from backend.app.schemas.proxy import ChatCompletionRequest
from backend.app.services.crypto import encrypt_text
from backend.app.services.proxy import proxy_chat_completion
from backend.app.services.trace import ProxyTraceRecorder


class ProxyTraceTest(unittest.TestCase):
    def test_trace_writer_redacts_sensitive_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(
                trace_proxy_enabled=True,
                trace_proxy_dir=str(Path(temp_dir) / "traces"),
                trace_proxy_redact=True,
            )
            trace = ProxyTraceRecorder.from_settings(settings)
            trace.start(
                protocol_in="openai",
                request_payload={
                    "message": "hello",
                    "api_key": "secret-value",
                    "nested": {"password": "hidden"},
                },
                app_token_name="Atlas",
            )
            trace.record_final_response(status_code=200, body={"authorization": "Bearer abc123"})
            trace.write()

            trace_files = list((Path(temp_dir) / "traces").glob("*.json"))
            self.assertEqual(len(trace_files), 1)
            content = json.loads(trace_files[0].read_text(encoding="utf-8"))
            self.assertEqual(content["client"]["payload"]["api_key"], "[redacted]")
            self.assertEqual(content["client"]["payload"]["nested"]["password"], "[redacted]")
            self.assertEqual(content["result"]["body"]["authorization"], "[redacted]")

    def test_proxy_chat_completion_writes_trace_file(self) -> None:
        asyncio.run(self._run_proxy_trace())

    async def _run_proxy_trace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "proxy-trace.sqlite"
            trace_dir = Path(temp_dir) / "traces"
            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
            settings = Settings(
                proxy_timeout_seconds=5,
                trace_proxy_enabled=True,
                trace_proxy_dir=str(trace_dir),
                trace_proxy_redact=True,
            )

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
                )

                request_body_ctx.set(json.dumps(payload.model_dump(exclude_none=False), ensure_ascii=False))

                upstream_body = {
                    "id": "chatcmpl-trace-1",
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

                captured: dict[str, object] = {}

                def handler(request: httpx.Request) -> httpx.Response:
                    captured["body"] = json.loads(request.content.decode("utf-8"))
                    return httpx.Response(200, json=upstream_body, request=request)

                original_async_client = httpx.AsyncClient

                def client_factory(*args, **kwargs):
                    timeout = kwargs.get("timeout")
                    return original_async_client(transport=httpx.MockTransport(handler), timeout=timeout)

                with patch("backend.app.services.proxy.get_settings", return_value=settings):
                    with patch("backend.app.services.proxy.httpx.AsyncClient", side_effect=client_factory):
                        status_code, body = await proxy_chat_completion(session, app_token, payload)

                self.assertEqual(status_code, 200)
                self.assertEqual(body, upstream_body)
                self.assertEqual(captured["body"]["model"], "gemini-3-flash-preview")

                trace_files = list(trace_dir.glob("*.json"))
                self.assertEqual(len(trace_files), 1)
                trace_content = json.loads(trace_files[0].read_text(encoding="utf-8"))
                self.assertEqual(trace_content["client"]["payload"]["model"], "google/gemini-3.1-flash")
                self.assertEqual(trace_content["route"]["kind"], "provider")
                self.assertEqual(trace_content["provider"]["attempts"][0]["provider"], "google")
                self.assertEqual(trace_content["provider"]["responses"][0]["status_code"], 200)
                self.assertEqual(trace_content["result"]["status_code"], 200)
                self.assertEqual(trace_content["result"]["body"]["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "demo")

            clear_request_context()
            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
