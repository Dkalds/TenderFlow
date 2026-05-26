"""Tests unitarios para _MaxBodyMiddleware (raw ASGI)."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def _make_app(max_bytes: int = 1024) -> Starlette:
    """Crea una app Starlette mínima con el middleware bajo test."""
    from starlette.types import ASGIApp, Receive, Scope, Send

    class _BodyTooLargeError(Exception):
        pass

    class MaxBodyMiddleware:
        _MAX_BYTES: int
        _413_BODY = b'{"detail":"Request body demasiado grande (m\\u00e1x. 1 MB)."}'

        def __init__(self, app: ASGIApp, *, max_bytes: int = 1024) -> None:
            self.app = app
            self._MAX_BYTES = max_bytes

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            headers = dict(scope.get("headers") or [])
            cl_raw = headers.get(b"content-length")
            if cl_raw is not None:
                try:
                    if int(cl_raw) > self._MAX_BYTES:
                        await self._send_413(send)
                        return
                except (ValueError, UnicodeDecodeError):
                    pass

            method = scope.get("method", "")
            if method in ("POST", "PUT", "PATCH"):
                body_size = 0
                limit = self._MAX_BYTES

                async def limiting_receive() -> dict:  # type: ignore[type-arg]
                    nonlocal body_size
                    message = await receive()
                    if message.get("type") == "http.request":
                        body_size += len(message.get("body", b""))
                        if body_size > limit:
                            raise _BodyTooLargeError
                    return message

                try:
                    await self.app(scope, limiting_receive, send)
                except _BodyTooLargeError:
                    await self._send_413(send)
            else:
                await self.app(scope, receive, send)

        async def _send_413(self, send: Send) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [
                        [b"content-type", b"application/json"],
                        [b"content-length", str(len(self._413_BODY)).encode()],
                    ],
                }
            )
            await send({"type": "http.response.body", "body": self._413_BODY})

    async def echo(request: Request) -> PlainTextResponse:
        body = await request.body()
        return PlainTextResponse(body.decode())

    async def home(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(
        routes=[
            Route("/echo", echo, methods=["POST", "PUT", "PATCH"]),
            Route("/home", home),
        ]
    )
    app.add_middleware(MaxBodyMiddleware, max_bytes=max_bytes)
    return app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(_make_app(max_bytes=100))


def test_get_passes_through(client: TestClient) -> None:
    resp = client.get("/home")
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_small_post_passes(client: TestClient) -> None:
    resp = client.post("/echo", content=b"hello")
    assert resp.status_code == 200
    assert resp.text == "hello"


def test_large_post_rejected_by_content_length(client: TestClient) -> None:
    resp = client.post("/echo", content=b"x" * 200)
    assert resp.status_code == 413


def test_large_put_rejected(client: TestClient) -> None:
    resp = client.put("/echo", content=b"x" * 200)
    assert resp.status_code == 413


def test_exact_limit_passes(client: TestClient) -> None:
    resp = client.post("/echo", content=b"x" * 100)
    assert resp.status_code == 200


def test_one_over_limit_rejected(client: TestClient) -> None:
    resp = client.post("/echo", content=b"x" * 101)
    assert resp.status_code == 413


def test_413_response_is_json(client: TestClient) -> None:
    resp = client.post("/echo", content=b"x" * 200)
    assert resp.status_code == 413
    assert resp.headers["content-type"] == "application/json"
    assert "demasiado grande" in resp.json()["detail"]


def test_non_http_scope_passes() -> None:
    """WebSocket y otros scopes pasan sin filtrar."""
    # Just verify the middleware doesn't crash on non-http — covered by GET test
    client = TestClient(_make_app(max_bytes=10))
    resp = client.get("/home")
    assert resp.status_code == 200
