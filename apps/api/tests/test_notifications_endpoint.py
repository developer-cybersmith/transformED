"""Tests for PATCH /api/auth/notifications — Story 4-23 / D60 Dev 4 scope.

Coverage:
- AC 1  — endpoint registered in auth/router.py, has CurrentUser dependency
- AC 2  — no JWT → 401/403
- AC 3  — invalid/expired JWT → 401
- AC 4  — valid JWT + preference fields → 200 with full NotificationPreferencesResponse
- AC 5  — user_id comes exclusively from JWT sub (never from request body)
- AC 6  — partial update: omitted fields retain their stored value
- AC 7  — empty request body (no fields) → 422
- AC 8  — updated_at is refreshed on every successful PATCH
- AC 9  — all Supabase calls wrapped in asyncio.to_thread (source inspection)
- AC 10 — no LLM call in the implementation (source inspection)
- AC 11 — DB upsert failure → HTTPException(500)
- AC 12 — read query uses .maybe_single() (Scale Contract Q4 bounded read)
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.config import get_settings

# ── JWT test constants (mirrors test_auth.py) ──────────────────────────────────

_SECRET = "test-jwt-secret-padded-to-32-bytes!!"
_PAST_EPOCH = 1_700_000_000  # 2023 — provably in the past
_FUTURE_EPOCH = 4_102_444_800  # 2100 — provably in the future
_FAKE_USER_ID = "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"

# ── Fake data ─────────────────────────────────────────────────────────────────

_STORED_PREFS = {
    "user_id": _FAKE_USER_ID,
    "session_report_email": True,
    "lesson_ready_email": True,
    "weekly_progress_email": False,  # user already opted out of this one
    "streak_reminders": True,
    "updated_at": "2026-08-01T10:00:00+00:00",
}

_DEFAULT_PREFS = {
    "user_id": _FAKE_USER_ID,
    "session_report_email": True,
    "lesson_ready_email": True,
    "weekly_progress_email": True,
    "streak_reminders": True,
    "updated_at": "2026-08-06T12:00:00+00:00",
}


# ── Mock builders ─────────────────────────────────────────────────────────────


def _build_supabase(
    existing_row: dict | None = None,
    read_raises: Exception | None = None,
    upsert_row: dict | None = None,
    upsert_raises: Exception | None = None,
) -> Any:
    """Build a mock Supabase client for the read-merge-upsert pattern.

    - ``existing_row``:  data returned by `.maybe_single()` read (None = no row yet)
    - ``read_raises``:   exception the read step should raise (simulates DB failure)
    - ``upsert_row``:    row returned by `.upsert().execute()` (defaults to _DEFAULT_PREFS)
    - ``upsert_raises``: exception the upsert step should raise (simulates DB failure)
    """
    tbl = MagicMock()

    # Read chain: .select(...).eq(...).maybe_single().execute()
    if read_raises:
        read_chain = MagicMock()
        read_chain.eq.return_value = read_chain
        read_chain.maybe_single.return_value = read_chain
        read_chain.execute.side_effect = read_raises
        tbl.select.return_value = read_chain
    else:
        read_result = MagicMock()
        read_result.data = existing_row  # None → "no row" branch
        read_chain = MagicMock()
        read_chain.eq.return_value = read_chain
        read_chain.maybe_single.return_value = read_chain
        read_chain.execute.return_value = read_result
        tbl.select.return_value = read_chain

    # Upsert chain: .upsert(data, on_conflict="user_id").execute()
    if upsert_raises:
        upsert_chain = MagicMock()
        upsert_chain.execute.side_effect = upsert_raises
        tbl.upsert.return_value = upsert_chain
    else:
        upsert_result = MagicMock()
        upsert_result.data = [upsert_row or _DEFAULT_PREFS]
        upsert_chain = MagicMock()
        upsert_chain.execute.return_value = upsert_result
        tbl.upsert.return_value = upsert_chain

    supabase = MagicMock()
    supabase.table.return_value = tbl
    return supabase


# ── TestClient app for JWT tests ──────────────────────────────────────────────


def _fake_settings() -> MagicMock:
    s = MagicMock()
    s.supabase_jwt_secret = _SECRET
    return s


def _token(**overrides) -> str:
    claims = {
        "sub": _FAKE_USER_ID,
        "iat": _PAST_EPOCH,
        "exp": _FUTURE_EPOCH,
        "aud": "authenticated",
    }
    claims.update(overrides)
    return jwt.encode(claims, _SECRET, algorithm="HS256")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


from app.modules.auth.router import router as _auth_router  # noqa: E402

_app = FastAPI()
_app.include_router(_auth_router, prefix="/api/auth")
_app.dependency_overrides[get_settings] = _fake_settings
_client = TestClient(_app, raise_server_exceptions=False)


# ── AC 1 — endpoint registered with CurrentUser dependency ────────────────────


@pytest.mark.unit
def test_patch_notifications_endpoint_has_current_user_dependency():
    """AC 1: patch_notifications must declare CurrentUser so FastAPI enforces JWT.

    The handler must be importable and must have 'current_user: CurrentUser'
    in its signature — FastAPI resolves this before calling the handler.
    """
    from app.modules.auth.router import patch_notifications

    sig = inspect.signature(patch_notifications)
    assert "current_user" in sig.parameters, (
        "patch_notifications must declare 'current_user: CurrentUser' for FastAPI JWT enforcement"
    )


# ── AC 2 — no JWT → 401/403 ───────────────────────────────────────────────────


@pytest.mark.unit
def test_patch_notifications_no_jwt_returns_401_or_403():
    """AC 2: PATCH /api/auth/notifications without Authorization header → 401/403."""
    resp = _client.patch(
        "/api/auth/notifications",
        json={"session_report_email": False},
    )
    assert resp.status_code in (401, 403), (
        f"Expected 401 or 403 for missing JWT, got {resp.status_code}"
    )


# ── AC 3 — invalid JWT → 401 ──────────────────────────────────────────────────


@pytest.mark.unit
def test_patch_notifications_invalid_jwt_returns_401():
    """AC 3: PATCH /api/auth/notifications with an invalid JWT → 401."""
    resp = _client.patch(
        "/api/auth/notifications",
        json={"session_report_email": False},
        headers=_auth("not-a-valid-token"),
    )
    assert resp.status_code == 401, f"Expected 401 for invalid JWT, got {resp.status_code}"


@pytest.mark.unit
def test_patch_notifications_expired_jwt_returns_401():
    """AC 3: PATCH /api/auth/notifications with an expired JWT → 401."""
    expired = _token(iat=_PAST_EPOCH, exp=_PAST_EPOCH + 3600)
    resp = _client.patch(
        "/api/auth/notifications",
        json={"session_report_email": False},
        headers=_auth(expired),
    )
    assert resp.status_code == 401, f"Expected 401 for expired JWT, got {resp.status_code}"


# ── AC 4 — valid JWT + fields → 200 with full response ────────────────────────


@pytest.mark.unit
def test_patch_notifications_valid_request_returns_200_with_full_response():
    """AC 4: valid JWT + at least one preference field → 200 + all required fields."""
    from app.modules.auth.router import NotificationPatchRequest, patch_notifications

    upsert_row = {
        "user_id": _FAKE_USER_ID,
        "session_report_email": False,
        "lesson_ready_email": True,
        "weekly_progress_email": True,
        "streak_reminders": True,
        "updated_at": "2026-08-06T12:00:00+00:00",
    }
    supabase = _build_supabase(existing_row=None, upsert_row=upsert_row)
    body = NotificationPatchRequest(session_report_email=False)
    current_user = {"sub": _FAKE_USER_ID}

    with patch("app.core.db.get_supabase", return_value=supabase):
        result = asyncio.run(patch_notifications(body=body, current_user=current_user))

    assert result.user_id == _FAKE_USER_ID
    assert result.session_report_email is False
    # All 4 boolean fields present
    assert hasattr(result, "session_report_email")
    assert hasattr(result, "lesson_ready_email")
    assert hasattr(result, "weekly_progress_email")
    assert hasattr(result, "streak_reminders")
    assert hasattr(result, "updated_at")


# ── AC 5 — user_id comes from JWT only ────────────────────────────────────────


@pytest.mark.unit
def test_patch_notifications_user_id_comes_from_jwt_not_body():
    """AC 5: user_id written to DB is always current_user['sub'], never from body.

    We call the handler with current_user['sub'] = 'jwt-owner' and verify the
    upsert payload carries 'jwt-owner', not any other value.
    """
    from app.modules.auth.router import NotificationPatchRequest, patch_notifications

    jwt_user_id = "jwt-owner-uuid-0001"
    upsert_row = {**_DEFAULT_PREFS, "user_id": jwt_user_id}
    supabase = _build_supabase(existing_row=None, upsert_row=upsert_row)
    body = NotificationPatchRequest(session_report_email=False)
    current_user = {"sub": jwt_user_id}

    with patch("app.core.db.get_supabase", return_value=supabase):
        result = asyncio.run(patch_notifications(body=body, current_user=current_user))

    # Verify the upsert received the JWT-derived user_id
    upsert_call_kwargs = supabase.table.return_value.upsert.call_args
    upsert_payload = upsert_call_kwargs[0][0]  # first positional arg to .upsert()
    assert upsert_payload["user_id"] == jwt_user_id, (
        f"Expected upsert user_id={jwt_user_id!r}, got {upsert_payload.get('user_id')!r}"
    )
    assert result.user_id == jwt_user_id


# ── AC 6 — partial update preserves omitted fields ────────────────────────────


@pytest.mark.unit
def test_patch_notifications_partial_update_preserves_omitted_fields():
    """AC 6: sending only session_report_email=False must not reset weekly_progress_email.

    _STORED_PREFS has weekly_progress_email=False. The PATCH only provides
    session_report_email=False. The returned row must still show
    weekly_progress_email=False — the omitted field was preserved, not reset to True.
    """
    from app.modules.auth.router import NotificationPatchRequest, patch_notifications

    # The upsert should receive weekly_progress_email=False (preserved from existing row)
    merged_upsert_row = {
        **_STORED_PREFS,
        "session_report_email": False,
        "updated_at": "2026-08-06T13:00:00+00:00",
    }
    supabase = _build_supabase(
        existing_row=_STORED_PREFS,
        upsert_row=merged_upsert_row,
    )
    body = NotificationPatchRequest(session_report_email=False)
    current_user = {"sub": _FAKE_USER_ID}

    with patch("app.core.db.get_supabase", return_value=supabase):
        result = asyncio.run(patch_notifications(body=body, current_user=current_user))

    # The omitted weekly_progress_email must be preserved at False
    assert result.weekly_progress_email is False, (
        "Omitted field weekly_progress_email was reset — partial update is broken"
    )
    # The provided field was applied
    assert result.session_report_email is False

    # Also verify the upsert payload sent to Supabase preserved the omitted field
    upsert_payload = supabase.table.return_value.upsert.call_args[0][0]
    assert upsert_payload["weekly_progress_email"] is False, (
        "Upsert payload should carry the existing weekly_progress_email=False"
    )


# ── AC 7 — empty body → 422 ───────────────────────────────────────────────────


@pytest.mark.unit
def test_patch_notifications_empty_body_returns_422():
    """AC 7: a request body with no preference fields → 422 Unprocessable Entity.

    The Pydantic model validator should reject all-None bodies before any DB call.
    We call the model validator directly (no HTTP layer needed).
    """
    from pydantic import ValidationError

    from app.modules.auth.router import NotificationPatchRequest

    with pytest.raises(ValidationError) as exc_info:
        NotificationPatchRequest()  # no fields at all

    errors = exc_info.value.errors()
    # Should have at least one validation error about the empty body
    assert len(errors) >= 1


# ── AC 8 — updated_at refreshed ───────────────────────────────────────────────


@pytest.mark.unit
def test_patch_notifications_updated_at_is_refreshed():
    """AC 8: updated_at in the upsert payload must be newer than the stored value.

    We mock the read to return a row with updated_at='2026-08-01T10:00:00+00:00'
    and verify the upsert payload carries a more recent timestamp.
    """
    from datetime import datetime

    from app.modules.auth.router import NotificationPatchRequest, patch_notifications

    old_ts = "2026-08-01T10:00:00+00:00"
    new_ts = "2026-08-06T12:00:00+00:00"
    upsert_row = {**_STORED_PREFS, "updated_at": new_ts}

    supabase = _build_supabase(existing_row=_STORED_PREFS, upsert_row=upsert_row)
    body = NotificationPatchRequest(session_report_email=False)
    current_user = {"sub": _FAKE_USER_ID}

    with patch("app.core.db.get_supabase", return_value=supabase):
        result = asyncio.run(patch_notifications(body=body, current_user=current_user))

    # The upsert payload's updated_at must be a fresh datetime, not the old one
    upsert_payload = supabase.table.return_value.upsert.call_args[0][0]
    sent_ts = upsert_payload["updated_at"]

    # Parse both as datetimes and compare
    sent_dt = datetime.fromisoformat(str(sent_ts).replace("Z", "+00:00"))
    old_dt = datetime.fromisoformat(old_ts)
    assert sent_dt > old_dt, (
        f"updated_at was not refreshed: sent {sent_ts!r} is not newer than {old_ts!r}"
    )

    # AC 8 also requires the RESPONSE field to carry the refreshed value (not just the payload)
    assert result.updated_at == new_ts, (
        f"Response updated_at should be {new_ts!r}, got {result.updated_at!r}"
    )


# ── AC 9 — asyncio.to_thread wraps DB calls (source inspection) ───────────────


@pytest.mark.unit
def test_patch_notifications_wraps_db_calls_in_asyncio_to_thread():
    """AC 9: all Supabase calls must use asyncio.to_thread to avoid blocking.

    supabase-py v2 is synchronous. Source inspection verifies the pattern is present.
    """
    import inspect as ins

    from app.modules.auth import router as auth_router_mod

    source = ins.getsource(auth_router_mod.patch_notifications)
    assert "asyncio.to_thread" in source, (
        "patch_notifications must wrap Supabase calls in asyncio.to_thread — "
        "supabase-py v2 is synchronous and blocks the event loop if called directly"
    )


# ── AC 10 — no LLM call (source inspection) ───────────────────────────────────


@pytest.mark.unit
def test_patch_notifications_makes_no_llm_call():
    """AC 10: the notification endpoint must not invoke any LLM.

    Source inspection on auth/router.py: no LLM identifier should appear in the
    patch_notifications function body.
    """
    import inspect as ins

    from app.modules.auth import router as auth_router_mod

    source = ins.getsource(auth_router_mod.patch_notifications)
    llm_identifiers = ["openai", "LLMProvider", "llm_", "gpt-4", "claude", "gemini"]
    found = [kw for kw in llm_identifiers if kw in source]
    assert not found, f"patch_notifications must not contain LLM references; found: {found}"


# ── AC 11 — DB upsert failure → 500 ──────────────────────────────────────────


@pytest.mark.unit
def test_patch_notifications_upsert_failure_returns_500():
    """AC 11: when the DB upsert raises an exception, the endpoint raises HTTP 500.

    The failure must not be silently swallowed — the user must know their
    preference was not saved.
    """
    from fastapi import HTTPException

    from app.modules.auth.router import NotificationPatchRequest, patch_notifications

    supabase = _build_supabase(
        existing_row=None,
        upsert_raises=RuntimeError("connection lost"),
    )
    body = NotificationPatchRequest(session_report_email=False)
    current_user = {"sub": _FAKE_USER_ID}

    with patch("app.core.db.get_supabase", return_value=supabase):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(patch_notifications(body=body, current_user=current_user))

    assert exc_info.value.status_code == 500


# ── AC 12 — read query uses .maybe_single() ──────────────────────────────────


@pytest.mark.unit
def test_patch_notifications_read_uses_maybe_single():
    """AC 12: read query must use .maybe_single() — Scale Contract Q4 bounded read.

    Source inspection: the read query chain must call .maybe_single() to satisfy
    test_unbounded_queries.py and docs/SCALE-CONTRACT.md Q4 (no unbounded SELECT on a
    request path).  A regression removing the call would fail the unbounded-query CI scan.
    """
    import inspect as ins

    from app.modules.auth import router as auth_router_mod

    source = ins.getsource(auth_router_mod.patch_notifications)
    assert "maybe_single" in source, (
        "patch_notifications read query must use .maybe_single() — "
        "required by Scale Contract Q4 and the test_unbounded_queries.py scanner"
    )


# ── Read failure → 503 (not fail-open) ───────────────────────────────────────


@pytest.mark.unit
def test_patch_notifications_read_failure_raises_503():
    """DB read failure → 503 Service Unavailable; upsert must NOT be called.

    Fail-open on a WRITE path would merge _NOTIF_DEFAULTS over the user's stored
    non-default preferences, silently corrupting their data.  Instead, the endpoint
    raises 503 so the caller can retry once the DB is healthy.
    """
    from fastapi import HTTPException

    from app.modules.auth.router import NotificationPatchRequest, patch_notifications

    supabase = _build_supabase(read_raises=RuntimeError("connection timeout"))
    body = NotificationPatchRequest(session_report_email=False)
    current_user = {"sub": _FAKE_USER_ID}

    with patch("app.core.db.get_supabase", return_value=supabase):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(patch_notifications(body=body, current_user=current_user))

    assert exc_info.value.status_code == 503, (
        f"Read failure must return 503 to prevent data corruption; got {exc_info.value.status_code}"
    )
    # Upsert must NOT have been called — read failure aborts the entire request
    supabase.table.return_value.upsert.assert_not_called()


# ── AC 5 HTTP boundary — extra body fields rejected ──────────────────────────


@pytest.mark.unit
def test_patch_notifications_extra_body_fields_returns_422():
    """AC 5: extra body fields (including user_id) are rejected with 422.

    NotificationPatchRequest uses ConfigDict(extra='forbid').  Sending user_id or any
    unknown field returns 422 Unprocessable Entity before the handler runs — the JWT-derived
    user_id cannot be overridden from the request body.
    """
    token = _token()
    resp = _client.patch(
        "/api/auth/notifications",
        json={"session_report_email": False, "user_id": "attacker-uuid"},
        headers=_auth(token),
    )
    assert resp.status_code == 422, (
        f"Sending user_id in the body should return 422 (extra='forbid'), got {resp.status_code}. "
        "NotificationPatchRequest must use ConfigDict(extra='forbid')."
    )


# ── Upsert empty response → 500 (guard against IndexError) ───────────────────


@pytest.mark.unit
def test_patch_notifications_upsert_empty_response_raises_500():
    """Upsert committed but returned no rows (empty data list) → 500.

    Prevents an uncontrolled IndexError on upsert_resp.data[0] when the Supabase client
    is configured with Prefer: return=minimal or a version difference suppresses RETURNING.
    """
    from fastapi import HTTPException

    from app.modules.auth.router import NotificationPatchRequest, patch_notifications

    tbl = MagicMock()

    read_result = MagicMock()
    read_result.data = None  # no existing row — new user
    read_chain = MagicMock()
    read_chain.eq.return_value = read_chain
    read_chain.maybe_single.return_value = read_chain
    read_chain.execute.return_value = read_result
    tbl.select.return_value = read_chain

    upsert_result = MagicMock()
    upsert_result.data = []  # empty — no RETURNING rows
    upsert_chain = MagicMock()
    upsert_chain.execute.return_value = upsert_result
    tbl.upsert.return_value = upsert_chain

    supabase = MagicMock()
    supabase.table.return_value = tbl

    body = NotificationPatchRequest(session_report_email=False)
    current_user = {"sub": _FAKE_USER_ID}

    with patch("app.core.db.get_supabase", return_value=supabase):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(patch_notifications(body=body, current_user=current_user))

    assert exc_info.value.status_code == 500
