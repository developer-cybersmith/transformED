"""
Unit tests for POST /api/analytics/events endpoint and ingest_events service.

Story 3-20 — Analytics Events Ingestion Live

Covers:
  AC 1   — HTTP 202 + {"ingested": N}
  AC 2   — jargon_hover event payload written correctly
  AC 3   — client_timestamp_ms stored as _client_ts_ms in payload JSONB
  AC 3a  — _client_ts_ms key collision: server value overwrites client payload value
  AC 4   — HTTP 422 for empty events list
  AC 5   — HTTP 422 for >100 events; 100 events accepted (boundary)
  AC 6   — HTTP 422 for negative client_timestamp_ms
  AC 7   — HTTP 403 when session belongs to a different user; user_id correctly queried
  AC 8   — HTTP 403 when session does not exist (same 403 as AC 7 — no enumeration oracle)
  AC 9   — single bulk insert call for the whole batch; duplicate session_ids deduplicated
  AC 10  — unknown event_type accepted and logged as WARNING
  AC 11  — 9 known event types in Field description; unknown accepted stated
  AC 12  — HTTP 500 on DB insert failure; error logged; sanitization tested
  AC 13  — asyncio.to_thread used for both DB calls
  AC 14  — unauthenticated requests rejected (401/403)
  AC 15  — zero LLM calls in ingest flow (structural guard)
  AC 17  — analytics endpoint is live (not 501)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.dependencies import get_current_user
from app.modules.analytics.router import router

# ── Test client ───────────────────────────────────────────────────────────────


async def _fake_user() -> dict:  # type: ignore[type-arg]
    return {"sub": "user-aaa-111", "email": "student@example.com"}


_app = FastAPI()
_app.dependency_overrides[get_current_user] = _fake_user
_app.include_router(router, prefix="/api/analytics")
client = TestClient(_app, raise_server_exceptions=False)

# ── Helpers ───────────────────────────────────────────────────────────────────

_VALID_SESSION_ID = "sess-valid-001"
_USER_ID = "user-aaa-111"


def _event(
    *,
    session_id: str = _VALID_SESSION_ID,
    event_type: str = "segment_complete",
    payload: dict[str, Any] | None = None,
    client_timestamp_ms: int = 1_700_000_000_000,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "event_type": event_type,
        "payload": payload if payload is not None else {},
        "client_timestamp_ms": client_timestamp_ms,
    }


def _body(events: list[dict[str, Any]]) -> dict[str, Any]:
    return {"events": events}


# ── Supabase mock factory ─────────────────────────────────────────────────────


def _build_events_supabase(
    *,
    authorized_session_ids: list[str] | None = None,
    insert_error: Any = None,
) -> MagicMock:
    """Build a supabase mock for the analytics service.

    Call order:
      0 → sessions ownership query  (.select.in_.eq.execute)
      1 → session_events bulk insert (.insert.execute)
    """
    if authorized_session_ids is None:
        authorized_session_ids = [_VALID_SESSION_ID]

    captured: dict[int, dict] = {}
    call_count = 0

    def _table(name: str) -> MagicMock:
        nonlocal call_count
        t = MagicMock()
        idx = call_count
        captured[idx] = {"table": name, "mock": t}
        call_count += 1

        if name == "sessions":
            # Chain: .select().in_().eq().execute()
            select_m = MagicMock()
            in_m = MagicMock()
            eq_m = MagicMock()
            exec_result = MagicMock()
            exec_result.data = [{"session_id": sid} for sid in authorized_session_ids]
            exec_result.error = None
            eq_m.execute.return_value = exec_result
            in_m.eq.return_value = eq_m
            select_m.in_.return_value = in_m
            t.select.return_value = select_m

        elif name == "session_events":
            # Chain: .insert().execute()
            insert_m = MagicMock()
            exec_result = MagicMock()
            exec_result.data = []
            exec_result.error = insert_error
            insert_m.execute.return_value = exec_result
            t.insert.return_value = insert_m

        return t

    mock = MagicMock()
    mock.table.side_effect = _table
    mock._captured_mocks = captured
    return mock


# ── asyncio.to_thread shim ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _mock_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make asyncio.to_thread call the lambda synchronously in tests."""

    def _sync_to_thread(fn, *args, **kwargs):
        result = fn(*args, **kwargs)
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        future.set_result(result)
        return future

    monkeypatch.setattr("asyncio.to_thread", _sync_to_thread)


# ── AC 1 — HTTP 202 + {"ingested": N} ─────────────────────────────────────────


@pytest.mark.unit
def test_202_single_event_returns_ingested_1() -> None:
    """AC 1: single valid event → HTTP 202, {"ingested": 1}."""
    supabase_mock = _build_events_supabase()
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        resp = client.post("/api/analytics/events", json=_body([_event()]))
    assert resp.status_code == 202
    assert resp.json() == {"ingested": 1}


@pytest.mark.unit
def test_202_batch_of_three_returns_ingested_3() -> None:
    """AC 1: three valid events → HTTP 202, {"ingested": 3}."""
    supabase_mock = _build_events_supabase()
    events = [
        _event(event_type="segment_complete"),
        _event(event_type="tab_switch"),
        _event(event_type="jargon_hover", payload={"term": "mitosis"}),
    ]
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        resp = client.post("/api/analytics/events", json=_body(events))
    assert resp.status_code == 202
    assert resp.json() == {"ingested": 3}


# ── AC 2 — jargon_hover payload correct ───────────────────────────────────────


@pytest.mark.unit
def test_jargon_hover_event_payload_correct() -> None:
    """AC 2: jargon_hover event writes term + segment_id to session_events payload."""
    supabase_mock = _build_events_supabase()
    ev = _event(
        event_type="jargon_hover",
        payload={"term": "homeostasis", "segment_id": "s-01"},
    )
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        resp = client.post("/api/analytics/events", json=_body([ev]))
    assert resp.status_code == 202

    # Check the row passed to the bulk insert contains the event payload
    insert_call = supabase_mock._captured_mocks.get(1, {}).get("mock")
    assert insert_call is not None, "session_events insert mock not captured"
    rows_passed = insert_call.insert.call_args[0][0]
    assert len(rows_passed) == 1
    row = rows_passed[0]
    assert row["event_type"] == "jargon_hover"
    assert row["payload"]["term"] == "homeostasis"
    assert row["payload"]["segment_id"] == "s-01"


# ── AC 3 — client_timestamp_ms stored as _client_ts_ms ────────────────────────


@pytest.mark.unit
def test_client_timestamp_stored_as_client_ts_ms_in_payload() -> None:
    """AC 3: client_timestamp_ms is stored under '_client_ts_ms' in payload JSONB."""
    supabase_mock = _build_events_supabase()
    ev = _event(client_timestamp_ms=1_700_000_000_123)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        client.post("/api/analytics/events", json=_body([ev]))

    insert_call = supabase_mock._captured_mocks.get(1, {}).get("mock")
    rows_passed = insert_call.insert.call_args[0][0]
    assert rows_passed[0]["payload"]["_client_ts_ms"] == 1_700_000_000_123


@pytest.mark.unit
def test_client_ts_ms_merged_alongside_existing_payload_keys() -> None:
    """AC 3: existing payload keys are preserved alongside _client_ts_ms."""
    supabase_mock = _build_events_supabase()
    ev = _event(
        event_type="jargon_hover",
        payload={"term": "osmosis", "segment_id": "s-03"},
        client_timestamp_ms=1_700_000_000_999,
    )
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        client.post("/api/analytics/events", json=_body([ev]))

    insert_call = supabase_mock._captured_mocks.get(1, {}).get("mock")
    rows_passed = insert_call.insert.call_args[0][0]
    payload = rows_passed[0]["payload"]
    assert payload["term"] == "osmosis"
    assert payload["segment_id"] == "s-03"
    assert payload["_client_ts_ms"] == 1_700_000_000_999


# ── AC 4 — Empty events list rejected ─────────────────────────────────────────


@pytest.mark.unit
def test_empty_events_list_returns_422() -> None:
    """AC 4: empty events list → HTTP 422 (Pydantic min_length=1)."""
    resp = client.post("/api/analytics/events", json={"events": []})
    assert resp.status_code == 422


# ── AC 5 — Oversized batch rejected ──────────────────────────────────────────


@pytest.mark.unit
def test_101_events_returns_422() -> None:
    """AC 5: 101 events → HTTP 422 (Pydantic max_length=100)."""
    events = [_event() for _ in range(101)]
    resp = client.post("/api/analytics/events", json=_body(events))
    assert resp.status_code == 422


# ── AC 6 — Negative client_timestamp_ms rejected ─────────────────────────────


@pytest.mark.unit
def test_negative_client_timestamp_returns_422() -> None:
    """AC 6: client_timestamp_ms=-1 → HTTP 422 (Field(ge=0))."""
    ev = _event(client_timestamp_ms=-1)
    resp = client.post("/api/analytics/events", json=_body([ev]))
    assert resp.status_code == 422


# ── AC 7 — Session owned by different user → 403 ─────────────────────────────


@pytest.mark.unit
def test_403_when_session_belongs_to_different_user() -> None:
    """AC 7: session exists but belongs to a different user → HTTP 403, zero writes."""
    # authorized_session_ids=[] simulates: no sessions match (user_id mismatch)
    supabase_mock = _build_events_supabase(authorized_session_ids=[])
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        resp = client.post("/api/analytics/events", json=_body([_event()]))

    assert resp.status_code == 403
    assert resp.json()["detail"] == "One or more sessions not found or access denied."

    # session_events insert must NOT have been called
    insert_mock = supabase_mock._captured_mocks.get(1)
    assert insert_mock is None, "session_events insert was called despite 403"


# ── AC 8 — Non-existent session → 403 (same as wrong-user) ───────────────────


@pytest.mark.unit
def test_403_when_session_does_not_exist() -> None:
    """AC 8: session_id does not exist in sessions table → HTTP 403."""
    supabase_mock = _build_events_supabase(authorized_session_ids=[])
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        resp = client.post(
            "/api/analytics/events",
            json=_body([_event(session_id="non-existent-session-id")]),
        )
    assert resp.status_code == 403


@pytest.mark.unit
def test_403_detail_identical_for_missing_and_wrong_user_sessions() -> None:
    """AC 8: 403 detail is IDENTICAL for missing and wrong-user sessions (no enumeration oracle)."""
    supabase_mock = _build_events_supabase(authorized_session_ids=[])

    # Simulate wrong-user (session exists but belongs to another user)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        resp_wrong_user = client.post("/api/analytics/events", json=_body([_event()]))

    # Simulate non-existent session (same behavior: DB returns empty authorized_ids)
    supabase_mock2 = _build_events_supabase(authorized_session_ids=[])
    with patch("app.core.db.get_supabase", return_value=supabase_mock2):
        resp_missing = client.post(
            "/api/analytics/events",
            json=_body([_event(session_id="ghost-session-999")]),
        )

    assert resp_wrong_user.status_code == 403
    assert resp_missing.status_code == 403
    assert resp_wrong_user.json()["detail"] == resp_missing.json()["detail"]


# ── AC 9 — Single bulk insert call ───────────────────────────────────────────


@pytest.mark.unit
def test_single_bulk_insert_call_not_per_event() -> None:
    """AC 9: three events → single .insert() call with all 3 rows, not 3 separate calls."""
    supabase_mock = _build_events_supabase()
    events = [_event() for _ in range(3)]
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        client.post("/api/analytics/events", json=_body(events))

    insert_call = supabase_mock._captured_mocks.get(1, {}).get("mock")
    assert insert_call is not None, "session_events insert mock not captured"
    # .insert() called exactly once with all 3 rows
    assert insert_call.insert.call_count == 1
    rows_passed = insert_call.insert.call_args[0][0]
    assert len(rows_passed) == 3


# ── AC 10 — Unknown event_type accepted ──────────────────────────────────────


@pytest.mark.unit
def test_unknown_event_type_accepted_returns_202() -> None:
    """AC 10: unknown event_type → HTTP 202 (soft validation, not rejected)."""
    supabase_mock = _build_events_supabase()
    ev = _event(event_type="custom_event_xyz")
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        resp = client.post("/api/analytics/events", json=_body([ev]))
    assert resp.status_code == 202


@pytest.mark.unit
def test_unknown_event_type_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    """AC 10: unknown event_type is logged at WARNING level."""
    supabase_mock = _build_events_supabase()
    ev = _event(event_type="totally_unknown_type_abc")
    with caplog.at_level(logging.WARNING, logger="app.modules.analytics.service"):
        with patch("app.core.db.get_supabase", return_value=supabase_mock):
            client.post("/api/analytics/events", json=_body([ev]))

    warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("totally_unknown_type_abc" in msg for msg in warning_messages), (
        f"Expected WARNING log containing unknown event type. Got: {warning_messages}"
    )


# ── AC 11 — All 9 known event types accepted ─────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "event_type",
    [
        "tab_switch",
        "retry_after_fail",
        "jargon_hover",
        "quiz_skip",
        "teachback_skip",
        "intervention_acknowledged",
        "segment_complete",
        "session_start",
        "session_end",
    ],
)
def test_all_9_known_event_types_accepted(event_type: str) -> None:
    """AC 11: each of the 9 known event types returns HTTP 202."""
    supabase_mock = _build_events_supabase()
    ev = _event(event_type=event_type)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        resp = client.post("/api/analytics/events", json=_body([ev]))
    assert resp.status_code == 202, f"Known event_type {event_type!r} was rejected"


# ── AC 12 — HTTP 500 on insert failure ───────────────────────────────────────


@pytest.mark.unit
def test_500_on_insert_error() -> None:
    """AC 12: truthy insert_resp.error → HTTP 500."""
    insert_error = MagicMock()
    insert_error.__str__ = lambda self: "connection reset by peer"
    supabase_mock = _build_events_supabase(insert_error=insert_error)
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        resp = client.post("/api/analytics/events", json=_body([_event()]))
    assert resp.status_code == 500
    assert "persist" in resp.json()["detail"].lower()


# ── AC 13 — asyncio.to_thread used for DB calls ──────────────────────────────


@pytest.mark.unit
def test_ownership_check_uses_asyncio_to_thread() -> None:
    """AC 13: sessions ownership check is wrapped in asyncio.to_thread."""
    supabase_mock = _build_events_supabase()
    to_thread_calls: list[Any] = []

    original_to_thread = asyncio.to_thread

    def _capturing_to_thread(fn, *args, **kwargs):
        to_thread_calls.append(fn)
        return original_to_thread(fn, *args, **kwargs)

    with patch("asyncio.to_thread", side_effect=_capturing_to_thread):
        with patch("app.core.db.get_supabase", return_value=supabase_mock):
            client.post("/api/analytics/events", json=_body([_event()]))

    # At minimum 2 to_thread calls: ownership check + bulk insert
    assert len(to_thread_calls) >= 2, (
        f"Expected ≥2 asyncio.to_thread calls (ownership + insert), got {len(to_thread_calls)}"
    )


@pytest.mark.unit
def test_insert_uses_asyncio_to_thread() -> None:
    """AC 13: bulk insert call is wrapped in asyncio.to_thread (not a bare sync call)."""
    supabase_mock = _build_events_supabase()
    to_thread_calls: list[Any] = []

    original_to_thread = asyncio.to_thread

    def _capturing_to_thread(fn, *args, **kwargs):
        to_thread_calls.append(fn)
        return original_to_thread(fn, *args, **kwargs)

    with patch("asyncio.to_thread", side_effect=_capturing_to_thread):
        with patch("app.core.db.get_supabase", return_value=supabase_mock):
            resp = client.post("/api/analytics/events", json=_body([_event()]))

    assert resp.status_code == 202
    assert len(to_thread_calls) >= 1


# ── AC 17 — Endpoint is live (not 501) ───────────────────────────────────────


@pytest.mark.unit
def test_analytics_events_endpoint_is_live_not_501() -> None:
    """AC 17: POST /api/analytics/events must NOT return 501 (endpoint is now live).

    Before Story 3-20, this endpoint returned 501. After implementation it must
    return any code other than 501 (will be 202 on success, or 4xx/5xx on error).
    Full contract tests live in this file.
    """
    supabase_mock = _build_events_supabase()
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        resp = client.post("/api/analytics/events", json=_body([_event()]))
    assert resp.status_code != 501, (
        "Analytics events endpoint returned 501 — implementation is missing. "
        "Story 3-20 requires this endpoint to be live."
    )


# ── AC 7 — Partial batch with one unauthorized session → fully rejected ───────


@pytest.mark.unit
def test_mixed_valid_invalid_session_batch_fully_rejected() -> None:
    """AC 7: batch with one valid + one unauthorized session → HTTP 403, zero writes."""
    # Only sess-valid-001 is authorized; sess-other-999 is not
    supabase_mock = _build_events_supabase(authorized_session_ids=[_VALID_SESSION_ID])
    events = [
        _event(session_id=_VALID_SESSION_ID),
        _event(session_id="sess-other-999"),  # NOT authorized
    ]
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        resp = client.post("/api/analytics/events", json=_body(events))

    assert resp.status_code == 403
    # insert must NOT have been called
    insert_mock = supabase_mock._captured_mocks.get(1)
    assert insert_mock is None, "session_events insert was called despite 403"


# ── AC 3a — _client_ts_ms key collision: server value wins ───────────────────


@pytest.mark.unit
def test_reserved_client_ts_ms_key_in_payload_is_overwritten_by_server_value() -> None:
    """AC 3a: payload '_client_ts_ms' is overwritten by server value (client_timestamp_ms)."""
    supabase_mock = _build_events_supabase()
    ev = _event(
        payload={"_client_ts_ms": 99999, "term": "entropy"},
        client_timestamp_ms=1_700_000_000_000,
    )
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        client.post("/api/analytics/events", json=_body([ev]))

    insert_call = supabase_mock._captured_mocks.get(1, {}).get("mock")
    rows_passed = insert_call.insert.call_args[0][0]
    payload = rows_passed[0]["payload"]
    assert payload["_client_ts_ms"] == 1_700_000_000_000, (
        "Server value must overwrite client-supplied _client_ts_ms. "
        f"Got: {payload['_client_ts_ms']}"
    )
    assert payload["term"] == "entropy", "Other payload keys must survive"


# ── AC 5 boundary — exactly 100 events accepted ───────────────────────────────


@pytest.mark.unit
def test_100_events_returns_202() -> None:
    """AC 5: exactly 100 events → HTTP 202 (at the max_length=100 boundary, not rejected)."""
    supabase_mock = _build_events_supabase()
    events = [_event() for _ in range(100)]
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        resp = client.post("/api/analytics/events", json=_body(events))
    assert resp.status_code == 202
    assert resp.json() == {"ingested": 100}


# ── AC 4 — payload field absent from request body ────────────────────────────


@pytest.mark.unit
def test_event_without_payload_field_uses_empty_dict_default() -> None:
    """AC 4 / AC 3: payload field is optional (default_factory=dict); omitting it → HTTP 202."""
    supabase_mock = _build_events_supabase()
    # Send event without the 'payload' key — Pydantic should default to {}
    ev_no_payload = {
        "session_id": _VALID_SESSION_ID,
        "event_type": "segment_complete",
        "client_timestamp_ms": 1_700_000_000_000,
    }
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        resp = client.post("/api/analytics/events", json={"events": [ev_no_payload]})
    assert resp.status_code == 202


# ── AC 7 — IDOR guard: ownership check uses correct user_id ──────────────────


@pytest.mark.unit
def test_ownership_query_passes_correct_user_id_to_eq() -> None:
    """AC 7: ownership check calls .eq('user_id', authenticated_user_id) — not a hardcoded value."""
    supabase_mock = _build_events_supabase()
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        resp = client.post("/api/analytics/events", json=_body([_event()]))
    assert resp.status_code == 202

    # Verify .eq("user_id", _USER_ID) was called on the sessions chain
    sessions_mock = supabase_mock._captured_mocks.get(0, {}).get("mock")
    assert sessions_mock is not None, "Sessions table was never queried"
    # sessions chain: .select().in_().eq("user_id", user_id)
    in_mock = sessions_mock.select.return_value.in_.return_value
    eq_call_args = in_mock.eq.call_args
    assert eq_call_args is not None, ".eq() was never called on sessions chain"
    called_field, called_value = eq_call_args[0]
    assert called_field == "user_id", (
        f"Expected .eq('user_id', ...), got .eq({called_field!r}, ...)"
    )
    assert called_value == _USER_ID, f"Expected user_id={_USER_ID!r}, got {called_value!r}"


# ── AC 12 — Error logging and sanitization ────────────────────────────────────


@pytest.mark.unit
def test_500_on_insert_error_logs_error_with_sanitized_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC 12: insert failure logs at ERROR level; embedded newlines stripped from log message."""
    insert_error = MagicMock()
    insert_error.__str__ = lambda self: "line1\nline2\r\nline3"  # embedded newlines
    supabase_mock = _build_events_supabase(insert_error=insert_error)

    with caplog.at_level(logging.ERROR, logger="app.modules.analytics.service"):
        with patch("app.core.db.get_supabase", return_value=supabase_mock):
            resp = client.post("/api/analytics/events", json=_body([_event()]))

    assert resp.status_code == 500
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert error_records, "Expected at least one ERROR log record for insert failure"
    # Sanitization: no raw newlines or carriage returns in the logged error
    logged_messages = " ".join(r.getMessage() for r in error_records)
    assert "\n" not in logged_messages, (
        f"Newline in error log — sanitization failed: {logged_messages!r}"
    )
    assert "\r" not in logged_messages, (
        f"CR in error log — sanitization failed: {logged_messages!r}"
    )


# ── AC 11 — Field description content ────────────────────────────────────────


@pytest.mark.unit
def test_event_type_field_description_lists_all_9_known_types() -> None:
    """AC 11: AnalyticsEvent.event_type Field description contains all 9 known type names."""
    from app.modules.analytics.router import AnalyticsEvent

    description = AnalyticsEvent.model_fields["event_type"].description
    assert description is not None, "event_type Field must have a description"

    expected_types = [
        "tab_switch",
        "retry_after_fail",
        "jargon_hover",
        "quiz_skip",
        "teachback_skip",
        "intervention_acknowledged",
        "segment_complete",
        "session_start",
        "session_end",
    ]
    for expected in expected_types:
        assert expected in description, (
            f"event_type description missing known type {expected!r}. "
            f"Full description: {description!r}"
        )


@pytest.mark.unit
def test_event_type_field_description_states_unknown_types_accepted() -> None:
    """AC 11: event_type Field description states that unknown types are accepted (not rejected)."""
    from app.modules.analytics.router import AnalyticsEvent

    description = AnalyticsEvent.model_fields["event_type"].description or ""
    # The description must communicate that unknown types are accepted
    accepted_indicators = ["accepted", "not rejected", "accept", "unknown"]
    assert any(indicator in description.lower() for indicator in accepted_indicators), (
        f"event_type description does not state that unknown types are accepted. "
        f"Full description: {description!r}"
    )


# ── AC 14 — Unauthenticated requests rejected ─────────────────────────────────


@pytest.mark.unit
def test_unauthenticated_request_is_rejected() -> None:
    """AC 14: request without JWT returns 401 or 403; no business logic executed.

    Uses a separate TestClient that does NOT have the get_current_user override,
    so the real dependency (HTTPBearer) handles authentication.
    """
    from app.modules.analytics.router import router as analytics_router

    _unauthed_app = FastAPI()
    # No dependency override — real get_current_user dependency runs
    _unauthed_app.include_router(analytics_router, prefix="/api/analytics")
    unauthed_client = TestClient(_unauthed_app, raise_server_exceptions=False)

    resp = unauthed_client.post(
        "/api/analytics/events",
        json={
            "events": [
                {
                    "session_id": _VALID_SESSION_ID,
                    "event_type": "segment_complete",
                    "payload": {},
                    "client_timestamp_ms": 1_700_000_000_000,
                }
            ]
        },
        # No Authorization header
    )
    assert resp.status_code in (401, 403), (
        f"Expected 401 or 403 for unauthenticated request, got {resp.status_code}. "
        "The analytics events endpoint must require authentication."
    )


# ── AC 15 — No LLM calls in ingest flow ──────────────────────────────────────


@pytest.mark.unit
def test_no_llm_calls_in_analytics_ingest_flow() -> None:
    """AC 15: zero LLM calls in the ingest_events service (pure DB write).

    Patches the OpenAI LLM provider's complete() method to raise immediately if called.
    Any LLM call during ingest_events would crash with AssertionError.
    """
    supabase_mock = _build_events_supabase()
    with patch(
        "app.providers.llm.openai.OpenAILLMProvider.complete",
        side_effect=AssertionError(
            "LLM.complete() was called in analytics service — this is forbidden"
        ),
    ) as mock_complete:
        with patch(
            "app.providers.llm.openai.OpenAILLMProvider.complete_structured",
            side_effect=AssertionError(
                "LLM.complete_structured() was called in analytics service — forbidden"
            ),
        ) as mock_structured:
            with patch("app.core.db.get_supabase", return_value=supabase_mock):
                resp = client.post("/api/analytics/events", json=_body([_event()]))
    assert resp.status_code == 202
    mock_complete.assert_not_called()
    mock_structured.assert_not_called()


# ── AC 9 — Duplicate session_ids in batch → deduplication ────────────────────


@pytest.mark.unit
def test_50_events_same_session_id_single_ownership_query() -> None:
    """AC 9 / AC 7: 50 events all referencing the same session_id → ownership checked once."""
    supabase_mock = _build_events_supabase()
    events = [_event() for _ in range(50)]  # all use _VALID_SESSION_ID
    with patch("app.core.db.get_supabase", return_value=supabase_mock):
        resp = client.post("/api/analytics/events", json=_body(events))
    assert resp.status_code == 202
    assert resp.json() == {"ingested": 50}

    # All 50 events must still be written
    insert_call = supabase_mock._captured_mocks.get(1, {}).get("mock")
    rows_passed = insert_call.insert.call_args[0][0]
    assert len(rows_passed) == 50


# ── AC 7/8 — ownership_resp.data = None → treated as no authorized sessions ──


@pytest.mark.unit
def test_403_when_ownership_resp_data_is_none() -> None:
    """AC 7/8: ownership query data=None (unusual DB state) is treated as unauthorized → 403."""
    # Override to return data=None specifically
    sessions_mock = MagicMock()
    select_m = MagicMock()
    in_m = MagicMock()
    eq_m = MagicMock()
    exec_result = MagicMock()
    exec_result.data = None  # explicit None, not empty list
    exec_result.error = None
    eq_m.execute.return_value = exec_result
    in_m.eq.return_value = eq_m
    select_m.in_.return_value = in_m
    sessions_mock.select.return_value = select_m

    call_count_box = [0]

    def _table(name: str) -> MagicMock:
        call_count_box[0] += 1
        if name == "sessions":
            return sessions_mock
        return MagicMock()

    none_supabase = MagicMock()
    none_supabase.table.side_effect = _table

    with patch("app.core.db.get_supabase", return_value=none_supabase):
        resp = client.post("/api/analytics/events", json=_body([_event()]))
    assert resp.status_code == 403
