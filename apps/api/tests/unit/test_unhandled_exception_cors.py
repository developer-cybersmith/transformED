"""Regression tests for UnhandledExceptionMiddleware (app/main.py).

Root cause this guards: Starlette's ServerErrorMiddleware -- which handles any
exception that escapes routing/dependencies, INCLUDING a handler registered via
``app.add_exception_handler(Exception, ...)``, since Starlette special-cases the
bare ``Exception`` class and routes it there instead of through
ExceptionMiddleware -- sits OUTSIDE CORSMiddleware in the stack. Its response
never passes back through CORS header injection, so a browser sees an opaque
"No 'Access-Control-Allow-Origin' header" CORS failure instead of the real 500.
Confirmed live against a real transient httpx.RemoteProtocolError talking to
Supabase's PostgREST inside POST /api/assessment/sessions.

Built as a standalone minimal app (not the real create_app()) so this test
exercises the middleware ORDERING mechanism in isolation, without needing the
real app's Supabase/Redis/ARQ lifespan dependencies.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.main import UnhandledExceptionMiddleware

TEST_ORIGIN = "http://localhost:3000"


def _make_test_app() -> FastAPI:
    app = FastAPI()
    # Same order as create_app(): UnhandledExceptionMiddleware BEFORE CORSMiddleware.
    app.add_middleware(UnhandledExceptionMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[TEST_ORIGIN],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/raises-httpx-error")
    async def _raises_httpx() -> None:
        raise httpx.RemoteProtocolError("simulated Server disconnected")

    @app.get("/raises-bare-exception")
    async def _raises_bare() -> None:
        raise RuntimeError("simulated unhandled exception")

    @app.get("/ok")
    async def _ok() -> dict[str, bool]:
        return {"ok": True}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_test_app(), raise_server_exceptions=False)


@pytest.mark.unit
def test_unhandled_specific_exception_type_gets_cors_headers(client: TestClient) -> None:
    resp = client.get("/raises-httpx-error", headers={"Origin": TEST_ORIGIN})
    assert resp.status_code == 500
    assert resp.headers.get("access-control-allow-origin") == TEST_ORIGIN
    assert resp.json() == {"detail": "Internal server error"}


@pytest.mark.unit
def test_unhandled_bare_exception_gets_cors_headers(client: TestClient) -> None:
    """The load-bearing case: BEFORE this middleware existed, a bare, truly
    unanticipated exception (no specific handler registered for its type)
    reached ServerErrorMiddleware and lost its CORS headers entirely."""
    resp = client.get("/raises-bare-exception", headers={"Origin": TEST_ORIGIN})
    assert resp.status_code == 500
    assert resp.headers.get("access-control-allow-origin") == TEST_ORIGIN
    assert resp.json() == {"detail": "Internal server error"}


@pytest.mark.unit
def test_normal_success_response_is_unaffected(client: TestClient) -> None:
    resp = client.get("/ok", headers={"Origin": TEST_ORIGIN})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert resp.headers.get("access-control-allow-origin") == TEST_ORIGIN


@pytest.mark.unit
def test_error_response_never_leaks_the_real_exception_message(client: TestClient) -> None:
    """Security: the internal exception string must never reach the client --
    matches this codebase's existing convention of generic, metadata-free error
    bodies (e.g. AC5's identical 404 body for absent/malformed/foreign resources)."""
    resp = client.get("/raises-bare-exception", headers={"Origin": TEST_ORIGIN})
    assert "simulated unhandled exception" not in resp.text


@pytest.mark.unit
def test_unhandled_exception_is_logged_and_reported_to_sentry(client: TestClient) -> None:
    """This middleware must not silently swallow errors from an observability
    standpoint -- CLAUDE.md requires observability wired before feature work."""
    with patch("app.main.sentry_sdk.capture_exception") as capture_mock:
        resp = client.get("/raises-bare-exception", headers={"Origin": TEST_ORIGIN})

    assert resp.status_code == 500
    capture_mock.assert_called_once()
    assert isinstance(capture_mock.call_args[0][0], RuntimeError)


@pytest.mark.unit
def test_sentry_capture_failure_does_not_break_the_error_response(client: TestClient) -> None:
    """A broken Sentry SDK call must not turn a handled 500 into an even worse,
    doubly-unhandled failure -- mirrors the guarded capture_exception pattern
    already used elsewhere in this codebase (graph.py, assessment/service.py)."""
    with patch("app.main.sentry_sdk.capture_exception", side_effect=RuntimeError("sentry is down")):
        resp = client.get("/raises-bare-exception", headers={"Origin": TEST_ORIGIN})

    assert resp.status_code == 500
    assert resp.headers.get("access-control-allow-origin") == TEST_ORIGIN
    assert resp.json() == {"detail": "Internal server error"}


@pytest.mark.unit
def test_no_cors_header_for_a_disallowed_origin() -> None:
    """Premise/regression guard the other way: this middleware must not
    accidentally widen CORS itself -- an origin NOT in allow_origins still
    gets no header, exactly like a normal successful response would."""
    client = TestClient(_make_test_app(), raise_server_exceptions=False)
    resp = client.get("/raises-bare-exception", headers={"Origin": "http://evil.example.com"})
    assert resp.status_code == 500
    assert "access-control-allow-origin" not in resp.headers
