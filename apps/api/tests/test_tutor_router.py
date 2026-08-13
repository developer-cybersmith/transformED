"""Tests for GET /api/tutor/session/{session_id}/state
          and POST /api/tutor/session/{session_id}/intervene
— Story 4-26 (tutor router implementation).

Coverage:
- AC 1  — GET returns 200 + TutorSessionState when session exists in Redis
- AC 2  — GET returns 404 when tutor_state key absent from Redis
- AC 3  — GET enforces JWT (no JWT → 401)
- AC 4  — GET is fault-tolerant: missing CES/count/flag keys return zero-values (not 500)
- AC 5  — GET cooldown_remaining = Redis TTL of tutor_cooldown key (0 when absent)
- AC 6  — POST dispatches correct FSM event per intervention_type (×3 types)
- AC 7  — POST returns dispatched=False with reason when a guard blocks (force=false)
- AC 8  — POST force=True deletes cooldown key before dispatch
- AC 9  — POST returns 404 when session absent from Redis
- AC 10 — POST rejects invalid intervention_type with 422
- AC 11 — POST enforces JWT (no JWT → 401)
- AC 12 — all tests use mocked Redis (no live Redis required)
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.config import get_settings
from app.core.redis import get_redis

# ── Test constants ────────────────────────────────────────────────────────────

_SECRET = "test-jwt-secret-padded-to-32-bytes!!"
_PAST_EPOCH = 1_700_000_000   # 2023 — provably in the past
_FUTURE_EPOCH = 4_102_444_800  # 2100 — provably in the future
_USER_ID = "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"
_SESSION_ID = "sess1111-2222-3333-4444-555555555555"

# ── JWT helpers ───────────────────────────────────────────────────────────────


def _token(**overrides: Any) -> str:
    claims: dict[str, Any] = {
        "sub": _USER_ID,
        "iat": _PAST_EPOCH,
        "exp": _FUTURE_EPOCH,
        "aud": "authenticated",
    }
    claims.update(overrides)
    return jwt.encode(claims, _SECRET, algorithm="HS256")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── Fake Settings (JWT secret only) ──────────────────────────────────────────


def _fake_settings() -> MagicMock:
    s = MagicMock()
    s.supabase_jwt_secret = _SECRET
    return s


# ── Redis mock builder ────────────────────────────────────────────────────────


def _make_redis(
    *,
    state: str | None = "TEACHING",
    ces: str | None = "72.5",
    distraction_count: str | None = "1",
    fatigue_fired: int = 0,  # redis.exists() returns count of existing keys
    cooldown_ttl: int = 0,   # redis.ttl() returns -2 if key absent, -1 if no TTL, else seconds
) -> AsyncMock:
    """Build an AsyncMock redis with preset responses for the five state keys."""
    redis = AsyncMock()

    async def _get(key: str) -> str | None:
        if f"tutor_state:{_SESSION_ID}" in key:
            return state
        if f"tutor_ces:{_SESSION_ID}" in key:
            return ces
        if f"tutor_distraction_count:{_SESSION_ID}" in key:
            return distraction_count
        return None

    redis.get.side_effect = _get
    redis.exists.return_value = fatigue_fired
    redis.ttl.return_value = cooldown_ttl
    redis.delete.return_value = 1
    return redis


# ── Test app ──────────────────────────────────────────────────────────────────


def _make_app(redis_mock: AsyncMock) -> TestClient:
    from app.modules.tutor.router import router as tutor_router

    app = FastAPI()
    app.include_router(tutor_router, prefix="/api/tutor")
    app.dependency_overrides[get_settings] = _fake_settings
    app.dependency_overrides[get_redis] = lambda: redis_mock
    return TestClient(app, raise_server_exceptions=False)


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/tutor/session/{session_id}/state
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_get_session_state_enforces_jwt_ac3():
    """AC 3 — no Authorization header → 401 (JWT enforcement)."""
    client = _make_app(_make_redis())
    resp = client.get(f"/api/tutor/session/{_SESSION_ID}/state")
    assert resp.status_code == 401


@pytest.mark.unit
def test_get_session_state_returns_404_when_session_missing_ac2():
    """AC 2 — tutor_state key absent from Redis → 404, not 200/500."""
    redis = _make_redis(state=None)
    client = _make_app(redis)
    resp = client.get(
        f"/api/tutor/session/{_SESSION_ID}/state",
        headers=_auth(_token()),
    )
    assert resp.status_code == 404


@pytest.mark.unit
def test_get_session_state_returns_full_state_ac1():
    """AC 1 — session exists → 200 with all TutorSessionState fields populated."""
    redis = _make_redis(
        state="TEACHING",
        ces="72.5",
        distraction_count="2",
        fatigue_fired=1,
        cooldown_ttl=90,
    )
    client = _make_app(redis)
    resp = client.get(
        f"/api/tutor/session/{_SESSION_ID}/state",
        headers=_auth(_token()),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == _SESSION_ID
    assert body["state"] == "TEACHING"
    assert abs(body["ces_score"] - 72.5) < 0.001
    assert body["distraction_count"] == 2
    assert body["fatigue_fired"] is True
    assert body["intervention_cooldown_remaining_seconds"] == 90


@pytest.mark.unit
def test_get_session_state_missing_optional_keys_return_zero_values_ac4():
    """AC 4 — CES, count, fatigue keys absent → zero-values, not 500."""
    redis = _make_redis(
        state="IDLE",
        ces=None,
        distraction_count=None,
        fatigue_fired=0,
        cooldown_ttl=-2,  # redis returns -2 when key does not exist
    )
    client = _make_app(redis)
    resp = client.get(
        f"/api/tutor/session/{_SESSION_ID}/state",
        headers=_auth(_token()),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert abs(body["ces_score"] - 0.0) < 0.001
    assert body["distraction_count"] == 0
    assert body["fatigue_fired"] is False
    assert body["intervention_cooldown_remaining_seconds"] == 0


@pytest.mark.unit
def test_get_session_state_cooldown_remaining_equals_redis_ttl_ac5():
    """AC 5 — cooldown_remaining = Redis TTL of tutor_cooldown key."""
    redis = _make_redis(state="TEACHING", cooldown_ttl=75)
    client = _make_app(redis)
    resp = client.get(
        f"/api/tutor/session/{_SESSION_ID}/state",
        headers=_auth(_token()),
    )
    assert resp.status_code == 200
    assert resp.json()["intervention_cooldown_remaining_seconds"] == 75


@pytest.mark.unit
def test_get_session_state_no_cooldown_returns_zero_ac5():
    """AC 5 — tutor_cooldown key absent (ttl = -2) → cooldown_remaining = 0."""
    redis = _make_redis(state="TEACHING", cooldown_ttl=-2)
    client = _make_app(redis)
    resp = client.get(
        f"/api/tutor/session/{_SESSION_ID}/state",
        headers=_auth(_token()),
    )
    assert resp.status_code == 200
    assert resp.json()["intervention_cooldown_remaining_seconds"] == 0


@pytest.mark.unit
def test_get_session_state_has_current_user_dependency():
    """AC 3 — handler signature must declare 'current_user: CurrentUser'."""
    from app.modules.tutor.router import get_session_state

    sig = inspect.signature(get_session_state)
    assert "current_user" in sig.parameters, (
        "get_session_state must declare 'current_user: CurrentUser' for JWT enforcement"
    )


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/tutor/session/{session_id}/intervene
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_post_intervene_enforces_jwt_ac11():
    """AC 11 — no Authorization header → 401."""
    client = _make_app(_make_redis())
    resp = client.post(
        f"/api/tutor/session/{_SESSION_ID}/intervene",
        json={"intervention_type": "distraction"},
    )
    assert resp.status_code == 401


@pytest.mark.unit
def test_post_intervene_missing_session_returns_404_ac9():
    """AC 9 — tutor_state key absent → 404."""
    redis = _make_redis(state=None)
    client = _make_app(redis)
    resp = client.post(
        f"/api/tutor/session/{_SESSION_ID}/intervene",
        json={"intervention_type": "distraction"},
        headers=_auth(_token()),
    )
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.parametrize("bad_type", ["encouragement", "quiz_prompt", "", "DISTRACTION", "none"])
def test_post_intervene_invalid_type_returns_422_ac10(bad_type: str):
    """AC 10 — intervention_type not in Literal set → 422 (Pydantic enforced)."""
    redis = _make_redis()
    client = _make_app(redis)
    resp = client.post(
        f"/api/tutor/session/{_SESSION_ID}/intervene",
        json={"intervention_type": bad_type},
        headers=_auth(_token()),
    )
    assert resp.status_code == 422, (
        f"Expected 422 for invalid type '{bad_type}', got {resp.status_code}"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "intervention_type,expected_event",
    [
        ("distraction", "distraction_detected"),
        ("fatigue", "fatigue_detected"),
        ("confusion", "teachback_failed"),
    ],
)
def test_post_intervene_dispatches_correct_fsm_event_ac6(
    intervention_type: str, expected_event: str
) -> None:
    """AC 6 — each intervention_type maps to its specific FSM event."""
    redis = _make_redis(state="TEACHING")

    _dispatch_result: dict[str, Any] = {
        "current_state": "INTERVENING",
        "intervention_message": "Take a moment.",
        "intervention_type": intervention_type,
    }

    with patch(
        "app.modules.tutor.router.dispatch_event",
        new_callable=AsyncMock,
        return_value=_dispatch_result,
    ) as mock_dispatch, patch(
        "app.modules.tutor.router._segment_intervention_messages",
        new_callable=AsyncMock,
        return_value={},
    ), patch(
        "app.modules.tutor.router.manager",
        new_callable=MagicMock,
    ) as mock_manager:
        mock_manager.send = AsyncMock()
        client = _make_app(redis)
        resp = client.post(
            f"/api/tutor/session/{_SESSION_ID}/intervene",
            json={"intervention_type": intervention_type},
            headers=_auth(_token()),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["dispatched"] is True
    mock_dispatch.assert_called_once()
    call_args = mock_dispatch.call_args
    assert call_args.args[1] == expected_event, (
        f"Expected event '{expected_event}' for type '{intervention_type}', "
        f"got '{call_args.args[1]}'"
    )


@pytest.mark.unit
def test_post_intervene_guard_blocked_returns_dispatched_false_ac7():
    """AC 7 — guard blocks dispatch (FSM stays TEACHING) → dispatched=False + reason."""
    redis = _make_redis(state="TEACHING")

    _dispatch_result: dict[str, Any] = {
        "current_state": "TEACHING",  # guard blocked — stayed in TEACHING
        "intervention_message": None,
        "intervention_type": None,
    }

    with patch(
        "app.modules.tutor.router.dispatch_event",
        new_callable=AsyncMock,
        return_value=_dispatch_result,
    ), patch(
        "app.modules.tutor.router._segment_intervention_messages",
        new_callable=AsyncMock,
        return_value={},
    ):
        client = _make_app(redis)
        resp = client.post(
            f"/api/tutor/session/{_SESSION_ID}/intervene",
            json={"intervention_type": "distraction"},
            headers=_auth(_token()),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["dispatched"] is False
    assert body["reason"] is not None  # some guard name provided
    assert body["to_state"] == "TEACHING"


@pytest.mark.unit
def test_post_intervene_force_deletes_cooldown_key_before_dispatch_ac8():
    """AC 8 — force=True deletes tutor_cooldown key before calling dispatch_event."""
    redis = _make_redis(state="TEACHING")

    _dispatch_result: dict[str, Any] = {
        "current_state": "INTERVENING",
        "intervention_message": "Take a moment.",
        "intervention_type": "distraction",
    }

    with patch(
        "app.modules.tutor.router.dispatch_event",
        new_callable=AsyncMock,
        return_value=_dispatch_result,
    ), patch(
        "app.modules.tutor.router._segment_intervention_messages",
        new_callable=AsyncMock,
        return_value={},
    ), patch(
        "app.modules.tutor.router.manager",
        new_callable=MagicMock,
    ) as mock_manager:
        mock_manager.send = AsyncMock()
        client = _make_app(redis)
        resp = client.post(
            f"/api/tutor/session/{_SESSION_ID}/intervene",
            json={"intervention_type": "distraction", "force": True},
            headers=_auth(_token()),
        )

    assert resp.status_code == 200
    # The cooldown key must have been deleted
    redis.delete.assert_called_once_with(f"tutor_cooldown:{_SESSION_ID}")


@pytest.mark.unit
def test_post_intervene_force_false_does_not_delete_cooldown():
    """AC 8 (negative) — force=False (default) must NOT touch the cooldown key."""
    redis = _make_redis(state="TEACHING")

    _dispatch_result: dict[str, Any] = {
        "current_state": "INTERVENING",
        "intervention_message": "Distraction message.",
        "intervention_type": "distraction",
    }

    with patch(
        "app.modules.tutor.router.dispatch_event",
        new_callable=AsyncMock,
        return_value=_dispatch_result,
    ), patch(
        "app.modules.tutor.router._segment_intervention_messages",
        new_callable=AsyncMock,
        return_value={},
    ), patch(
        "app.modules.tutor.router.manager",
        new_callable=MagicMock,
    ) as mock_manager:
        mock_manager.send = AsyncMock()
        client = _make_app(redis)
        resp = client.post(
            f"/api/tutor/session/{_SESSION_ID}/intervene",
            json={"intervention_type": "distraction", "force": False},
            headers=_auth(_token()),
        )

    assert resp.status_code == 200
    redis.delete.assert_not_called()


@pytest.mark.unit
def test_post_intervene_sends_ws_message_when_intervention_fires():
    """AC 6 extension — when dispatch transitions to INTERVENING, manager.send is called
    with the tutor_intervene WS message so the overlay renders without an attention signal."""
    redis = _make_redis(state="TEACHING")

    _msg = "Great job so far — take a short break!"
    _dispatch_result: dict[str, Any] = {
        "current_state": "INTERVENING",
        "intervention_message": _msg,
        "intervention_type": "distraction",
    }

    with patch(
        "app.modules.tutor.router.dispatch_event",
        new_callable=AsyncMock,
        return_value=_dispatch_result,
    ), patch(
        "app.modules.tutor.router._segment_intervention_messages",
        new_callable=AsyncMock,
        return_value={},
    ), patch(
        "app.modules.tutor.router.manager",
        new_callable=MagicMock,
    ) as mock_manager:
        mock_manager.send = AsyncMock()
        client = _make_app(redis)
        client.post(
            f"/api/tutor/session/{_SESSION_ID}/intervene",
            json={"intervention_type": "distraction"},
            headers=_auth(_token()),
        )

    mock_manager.send.assert_awaited_once()
    call_kwargs = mock_manager.send.call_args
    sent_msg = call_kwargs.args[1]
    assert sent_msg["type"] == "tutor_intervene"
    assert sent_msg["payload"]["message"] == _msg
    assert sent_msg["payload"]["type"] == "distraction"


@pytest.mark.unit
def test_post_intervene_no_ws_message_when_guard_blocks():
    """AC 7 extension — when guard blocks (no INTERVENING), manager.send is NOT called."""
    redis = _make_redis(state="TEACHING")

    _dispatch_result: dict[str, Any] = {
        "current_state": "TEACHING",
        "intervention_message": None,
        "intervention_type": None,
    }

    with patch(
        "app.modules.tutor.router.dispatch_event",
        new_callable=AsyncMock,
        return_value=_dispatch_result,
    ), patch(
        "app.modules.tutor.router._segment_intervention_messages",
        new_callable=AsyncMock,
        return_value={},
    ), patch(
        "app.modules.tutor.router.manager",
        new_callable=MagicMock,
    ) as mock_manager:
        mock_manager.send = AsyncMock()
        client = _make_app(redis)
        client.post(
            f"/api/tutor/session/{_SESSION_ID}/intervene",
            json={"intervention_type": "fatigue"},
            headers=_auth(_token()),
        )

    mock_manager.send.assert_not_awaited()


@pytest.mark.unit
def test_post_intervene_has_current_user_dependency():
    """AC 11 — handler signature must declare 'current_user: CurrentUser'."""
    from app.modules.tutor.router import trigger_intervention

    sig = inspect.signature(trigger_intervention)
    assert "current_user" in sig.parameters, (
        "trigger_intervention must declare 'current_user: CurrentUser' for JWT enforcement"
    )


@pytest.mark.unit
def test_intervention_request_type_is_literal_not_str_ac10():
    """AC 10 — InterventionRequest.intervention_type must be Literal, not bare str.

    A bare str accepts any value at parse time and would require runtime string
    comparison. Literal enforces the constraint at the FastAPI/Pydantic boundary.
    """
    import typing

    from app.modules.tutor.router import InterventionRequest

    type_hint = InterventionRequest.model_fields["intervention_type"].annotation
    # Literal types have __origin__ == Literal (typing.Literal)
    origin = getattr(type_hint, "__origin__", None)
    assert origin is typing.Literal, (
        f"InterventionRequest.intervention_type should be Literal[...], "
        f"got annotation={type_hint!r} (origin={origin!r}). "
        "Change it from 'str' to 'Literal[\"distraction\", \"fatigue\", \"confusion\"]'."
    )
