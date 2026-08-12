"""Unit tests for S3-48: Lua atomic distraction cap (D6).

ACs covered:
 AC 1  — _DISTRACTION_GUARD_LUA constant exists and contains EXISTS / INCR / return 'ok'
 AC 2  — _can_intervene_distraction accepts (session_id, redis, settings) and uses redis.eval
 AC 3  — Returns True/'ok', False/'cooldown', False/'max_reached'
 AC 4  — Fail-closed on any Redis error
 AC 5  — process_attention_signal source uses _can_intervene_distraction, not redis.exists
 AC 6  — No dispatch when guard returns False
 AC 7  — route_from_teaching source has no _can_intervene_distraction call
 AC 8  — intervening_node source uses nx=True for cooldown key
 AC 9  — intervening_node source uses nx=True for fatigue key (count >= 2)
 AC 10 — redis.eval called with correct key count and KEYS/ARGV layout
 AC 11 — No separate redis.exists / redis.get two-step in _can_intervene_distraction

All tests are @pytest.mark.unit — no real Redis, no real state machine.
asyncio_mode = "auto" (pyproject.toml) runs the async tests directly.
"""

from __future__ import annotations

import ast
import inspect
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.tutor.state_machine.graph as graph_mod
from app.modules.tutor.state_machine.graph import (
    _DISTRACTION_GUARD_LUA,
    _can_intervene_distraction,
)

# ── helpers ───────────────────────────────────────────────────────────────────


def _mock_settings(max_distraction: int = 3) -> MagicMock:
    s = MagicMock()
    s.max_distraction_per_session = max_distraction
    s.intervention_cooldown_seconds = 120
    return s


def _mock_redis(eval_return: bytes | str = b"ok") -> AsyncMock:
    r = AsyncMock()
    r.eval = AsyncMock(return_value=eval_return)
    return r


# ── AC 1: constant exists and contains required Lua instructions ──────────────


def test_distraction_guard_lua_constant_exists():
    assert hasattr(graph_mod, "_DISTRACTION_GUARD_LUA")
    assert isinstance(_DISTRACTION_GUARD_LUA, str)
    assert len(_DISTRACTION_GUARD_LUA.strip()) > 0


def test_lua_script_contains_exists_incr_ok():
    lua = _DISTRACTION_GUARD_LUA
    assert "EXISTS" in lua, "Lua script must call redis.call('EXISTS', ...)"
    assert "INCR" in lua, "Lua script must call redis.call('INCR', ...)"
    assert "'ok'" in lua or '"ok"' in lua, "Lua script must return 'ok' on success"
    assert "'cooldown'" in lua or '"cooldown"' in lua, "Lua script must return 'cooldown' string"
    assert "'max_reached'" in lua or '"max_reached"' in lua, (
        "Lua script must return 'max_reached' string"
    )


# ── AC 2: signature accepts (session_id, redis, settings) and uses eval ───────


def test_can_intervene_distraction_signature_accepts_redis_settings():
    sig = inspect.signature(_can_intervene_distraction)
    params = list(sig.parameters.keys())
    assert "session_id" in params
    assert "redis" in params
    assert "settings" in params


def test_can_intervene_distraction_source_has_eval():
    src = inspect.getsource(_can_intervene_distraction)
    assert "redis.eval" in src, "_can_intervene_distraction must use redis.eval"


# ── AC 11: no separate EXISTS/GET two-step ────────────────────────────────────


def test_can_intervene_distraction_source_no_separate_exists_get():
    src = inspect.getsource(_can_intervene_distraction)
    assert "redis.exists(" not in src, (
        "_can_intervene_distraction must not call redis.exists separately"
    )
    assert "redis.get(" not in src, (
        "_can_intervene_distraction must not call redis.get separately"
    )


def test_no_non_atomic_two_step_in_can_intervene_distraction():
    """CI guard: parse the AST and assert no Call to redis.exists or redis.get."""
    src = inspect.getsource(_can_intervene_distraction)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                assert func.attr not in ("exists", "get"), (
                    f"Non-atomic call redis.{func.attr}() found in _can_intervene_distraction"
                )


# ── AC 3: return values map correctly ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_can_intervene_distraction_returns_true_on_lua_ok():
    redis = _mock_redis(b"ok")
    result = await _can_intervene_distraction("sess-1", redis, _mock_settings())
    assert result is True


@pytest.mark.asyncio
async def test_can_intervene_distraction_returns_true_on_lua_ok_str():
    redis = _mock_redis("ok")
    result = await _can_intervene_distraction("sess-1", redis, _mock_settings())
    assert result is True


@pytest.mark.asyncio
async def test_can_intervene_distraction_returns_false_on_lua_cooldown():
    redis = _mock_redis(b"cooldown")
    result = await _can_intervene_distraction("sess-1", redis, _mock_settings())
    assert result is False


@pytest.mark.asyncio
async def test_can_intervene_distraction_returns_false_on_lua_max_reached():
    redis = _mock_redis(b"max_reached")
    result = await _can_intervene_distraction("sess-1", redis, _mock_settings())
    assert result is False


# ── AC 4: fail-closed on Redis error ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_can_intervene_distraction_fails_closed_on_redis_error():
    redis = AsyncMock()
    redis.eval = AsyncMock(side_effect=ConnectionError("redis down"))
    result = await _can_intervene_distraction("sess-1", redis, _mock_settings())
    assert result is False


# ── AC 10: eval called with correct keys and args ────────────────────────────


@pytest.mark.asyncio
async def test_can_intervene_distraction_eval_called_with_correct_keys_and_args():
    redis = _mock_redis(b"ok")
    settings = _mock_settings(max_distraction=5)
    await _can_intervene_distraction("sess-xyz", redis, settings)

    redis.eval.assert_called_once()
    call_args = redis.eval.call_args[0]  # positional args
    _script, num_keys, cooldown_key, count_key, max_arg, ttl_arg = call_args
    assert num_keys == 2
    assert cooldown_key == "tutor_cooldown:sess-xyz"
    assert count_key == "tutor_distraction_count:sess-xyz"
    assert max_arg == "5"
    # TTL arg matches _STATE_TTL (86_400)
    assert ttl_arg == str(graph_mod._STATE_TTL)


# ── AC 5: process_attention_signal source uses _can_intervene_distraction ────


def test_process_attention_signal_source_uses_can_intervene_not_exists():
    import app.modules.tutor.service as svc_mod

    src = inspect.getsource(svc_mod.process_attention_signal)
    assert "_can_intervene_distraction" in src, (
        "process_attention_signal must call _can_intervene_distraction"
    )
    # Must NOT contain the old non-atomic guard
    assert "redis.exists(cooldown_key)" not in src, (
        "process_attention_signal must not use redis.exists(cooldown_key) — replaced by Lua guard"
    )


# ── AC 6: no dispatch when guard returns False ────────────────────────────────


@pytest.mark.asyncio
async def test_process_attention_signal_no_dispatch_when_guard_returns_false():
    """When _can_intervene_distraction returns False, dispatch_event must NOT be called."""
    from app.modules.tutor.service import process_attention_signal

    mock_redis = AsyncMock()
    # Two consecutive low CES values to satisfy the 2-window threshold
    mock_redis.set = AsyncMock()
    mock_redis.lpush = AsyncMock()
    mock_redis.ltrim = AsyncMock()
    mock_redis.expire = AsyncMock()
    mock_redis.lrange = AsyncMock(return_value=["0.1", "0.1"])
    mock_redis.get = AsyncMock(return_value="TEACHING")

    mock_dispatch = AsyncMock(return_value={"current_state": "INTERVENING"})

    signal = {
        "session_id": "sess-guard",
        "quiz_accuracy": None,
        "teachback_score": None,
        "behavioral_score": 0.1,
        "head_pose_score": 0.1,
        "blink_rate": 0.1,
    }

    with (
        patch("app.config.get_settings") as mock_get_settings,
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch(
            "app.modules.tutor.state_machine.graph.dispatch_event",
            mock_dispatch,
        ),
        patch(
            "app.modules.tutor.state_machine.graph._can_intervene_distraction",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "app.modules.tutor.service._segment_intervention_messages",
            new_callable=AsyncMock,
            return_value={},
        ),
    ):
        s = MagicMock()
        s.ces_threshold = 50.0
        s.ces_weight_quiz = 0.35
        s.ces_weight_teachback = 0.25
        s.ces_weight_behavioral = 0.20
        s.ces_weight_head_pose = 0.12
        s.ces_weight_blink = 0.08
        s.max_distraction_per_session = 3
        s.intervention_cooldown_seconds = 120
        s.ces_fatigue_blink_threshold = 0.3
        s.ces_fatigue_head_pose_threshold = 0.3
        s.ces_fatigue_min_session_seconds = 900
        mock_get_settings.return_value = s

        result = await process_attention_signal("sess-guard", signal)

    mock_dispatch.assert_not_called()
    assert not result.intervention_dispatched


# ── AC 7: route_from_teaching no longer calls _can_intervene_distraction ─────


def test_route_from_teaching_source_no_can_intervene_distraction_call():
    from app.modules.tutor.state_machine.graph import route_from_teaching

    src = inspect.getsource(route_from_teaching)
    # The call to _can_intervene_distraction must NOT appear in route_from_teaching —
    # the guard moved to service.py.  The name may still appear in a comment; we check
    # for the call pattern specifically.
    call_pattern = re.compile(r"await\s+_can_intervene_distraction\s*\(")
    assert not call_pattern.search(src), (
        "route_from_teaching must not call _can_intervene_distraction — guard moved to service.py"
    )


# ── AC 8: intervening_node uses nx=True for cooldown key ─────────────────────


def test_intervening_node_source_uses_nx_for_cooldown():
    from app.modules.tutor.state_machine.graph import intervening_node

    src = inspect.getsource(intervening_node)
    assert "nx=True" in src, "intervening_node must use nx=True for SET calls"
    assert "cooldown_key" in src, "intervening_node must write the cooldown key"
    # Ensure the cooldown SET specifically has nx=True nearby
    # (simple heuristic: nx=True appears at least once in the cooldown block)
    assert src.count("nx=True") >= 1


# ── AC 9: intervening_node uses nx=True for fatigue key (count >= 2) ─────────


def test_intervening_node_source_uses_nx_for_fatigue():
    from app.modules.tutor.state_machine.graph import intervening_node

    src = inspect.getsource(intervening_node)
    assert "tutor_fatigue_fired" in src, "intervening_node must write the fatigue_fired key"
    # Both the fatigue and cooldown writes must use nx=True → at least 2 occurrences
    assert src.count("nx=True") >= 2, (
        "intervening_node must have nx=True for BOTH fatigue_fired and cooldown writes"
    )


# ── Guard: distraction INCR removed from intervening_node (Lua owns it) ──────


def test_intervening_node_source_no_distraction_incr():
    """Lua script does the INCR; intervening_node must not double-count."""
    from app.modules.tutor.state_machine.graph import intervening_node

    src = inspect.getsource(intervening_node)
    # A plain redis.incr call for the distraction count would double-increment.
    incr_pattern = re.compile(r"redis\.incr\s*\(.*tutor_distraction_count")
    assert not incr_pattern.search(src), (
        "intervening_node must not call redis.incr(tutor_distraction_count) — Lua already did it"
    )
