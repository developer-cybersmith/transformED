"""Unit tests for WebSocket session lifecycle and tutor guard rules.

Covers two tracker tasks in ``apps/api/app/core/websocket.py``:
- ``session_state_init``  → ``_init_session_state()``
- ``idle_to_teaching``    → ``_handle_session_start()``

All tests are ``@pytest.mark.unit`` — no real Redis / state machine required.
``asyncio_mode = "auto"`` (see pyproject.toml) runs the async tests directly.

Patch-target note
-----------------
``_init_session_state`` lazily imports ``get_redis`` *inside* the function
(per the no-module-level-imports rule in websocket.py), so the only effective
patch target is ``app.core.redis.get_redis`` — the namespace the lazy
``from app.core.redis import get_redis`` actually resolves against. Patching
``app.core.websocket.get_redis`` would not intercept it (the name never lives
on the websocket module).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── Group A — _init_session_state ──────────────────────────────────────────────


@pytest.mark.unit
async def test_a1_init_sets_tutor_state_idle(mocker):
    mock_redis = AsyncMock()
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import _init_session_state

    await _init_session_state("sess-001")

    mock_redis.set.assert_any_call("tutor_state:sess-001", "IDLE", ex=86400)


@pytest.mark.unit
async def test_a2_init_zeros_distraction_count(mocker):
    mock_redis = AsyncMock()
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import _init_session_state

    await _init_session_state("sess-001")

    mock_redis.set.assert_any_call("tutor_distraction_count:sess-001", "0", ex=86400)


@pytest.mark.unit
async def test_a3_init_clears_stale_cooldown_and_fatigue_keys(mocker):
    mock_redis = AsyncMock()
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import _init_session_state

    await _init_session_state("sess-001")

    mock_redis.delete.assert_any_call("tutor_cooldown:sess-001")
    mock_redis.delete.assert_any_call("tutor_fatigue_fired:sess-001")
    mock_redis.delete.assert_any_call("session:sess-001:segment_index")  # reset segment pointer


@pytest.mark.unit
async def test_a4_init_redis_failure_does_not_raise(mocker):
    mocker.patch("app.core.redis.get_redis", side_effect=ConnectionError("down"))

    from app.core.websocket import _init_session_state

    await _init_session_state("sess-fail")  # must not raise


# ── Group B — _handle_session_start ───────────────────────────────────────────


@pytest.mark.unit
async def test_b1_session_start_dispatches_event(mocker):
    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    from app.core.websocket import _handle_session_start

    await _handle_session_start("sess-002")

    mock_dispatch.assert_called_once_with("sess-002", "session_start")


@pytest.mark.unit
async def test_b2_session_start_dispatch_failure_does_not_raise(mocker):
    mocker.patch(
        "app.modules.tutor.state_machine.graph.dispatch_event",
        side_effect=RuntimeError("FSM crash"),
    )

    from app.core.websocket import _handle_session_start

    await _handle_session_start("sess-fail")  # must not raise


# ── Group C — Cooldown guard G2 ───────────────────────────────────────────────


@pytest.mark.unit
async def test_c1_g2_cooldown_active_blocks_intervention(mocker):
    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(return_value=1)  # in cooldown
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    mock_settings = MagicMock()
    mock_settings.max_distraction_per_session = 3
    mocker.patch("app.config.get_settings", return_value=mock_settings)

    from app.modules.tutor.state_machine.graph import _can_intervene_distraction

    result = await _can_intervene_distraction("sess-003")

    assert result is False


@pytest.mark.unit
async def test_c2_g2_no_cooldown_below_max_allows_intervention(mocker):
    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(return_value=0)   # not in cooldown
    mock_redis.get = AsyncMock(return_value="1")    # count = 1, below max of 3
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    mock_settings = MagicMock()
    mock_settings.max_distraction_per_session = 3
    mocker.patch("app.config.get_settings", return_value=mock_settings)

    from app.modules.tutor.state_machine.graph import _can_intervene_distraction

    result = await _can_intervene_distraction("sess-003")

    assert result is True


@pytest.mark.unit
async def test_c3_g2_at_max_count_blocks_intervention(mocker):
    mock_redis = AsyncMock()
    mock_redis.exists = AsyncMock(return_value=0)   # not in cooldown
    mock_redis.get = AsyncMock(return_value="3")    # count == max of 3 → must block
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    mock_settings = MagicMock()
    mock_settings.max_distraction_per_session = 3
    mocker.patch("app.config.get_settings", return_value=mock_settings)

    from app.modules.tutor.state_machine.graph import _can_intervene_distraction

    result = await _can_intervene_distraction("sess-003")

    assert result is False


# ── Group D — TEACH_BACK guard G5 ─────────────────────────────────────────────


@pytest.mark.unit
async def test_d1_g5_teach_back_state_blocks_intervention(mocker):
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="TEACH_BACK")
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.modules.tutor.state_machine.graph import _is_in_teachback

    result = await _is_in_teachback("sess-004")

    assert result is True


@pytest.mark.unit
async def test_d2_g5_teach_back_absent_allows_intervention(mocker):
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="TEACHING")
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.modules.tutor.state_machine.graph import _is_in_teachback

    result = await _is_in_teachback("sess-004")

    assert result is False


# ── Group E — quizzing/teachback flow dispatch (s2-3) ─────────────────────────


@pytest.mark.unit
async def test_e1_flow_event_dispatches_to_fsm(mocker):
    """A client-drivable lifecycle event is dispatched into the tutor FSM."""
    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)

    from app.core.websocket import _handle_tutor_event

    await _handle_tutor_event("sess-q", "quiz_failed")

    mock_dispatch.assert_called_once_with("sess-q", "quiz_failed")


@pytest.mark.unit
@pytest.mark.parametrize("event", ["distraction_detected", "fatigue_detected", "session_reset"])
async def test_e2_server_only_event_rejected_by_service(event):
    """Server/engine/admin-only events must NOT be client-drivable — advance_tutor_state rejects them."""
    from app.modules.tutor.service import advance_tutor_state

    with pytest.raises(ValueError):
        await advance_tutor_state("sess-x", event)


@pytest.mark.unit
async def test_e3_tutor_event_failure_does_not_raise(mocker):
    """A transient FSM error during a flow event must be swallowed at the WS boundary (B2 analog)."""
    mocker.patch(
        "app.modules.tutor.state_machine.graph.dispatch_event",
        side_effect=RuntimeError("FSM crash"),
    )

    from app.core.websocket import _handle_tutor_event

    await _handle_tutor_event("sess-q", "quiz_failed")  # must not raise


@pytest.mark.unit
def test_e4_client_event_allowlists_match():
    """The WS-routing allow-list and the service allow-list must stay in sync (no silent drift)."""
    from app.core.websocket import _TUTOR_CLIENT_EVENTS
    from app.modules.tutor.service import _CLIENT_DRIVABLE_EVENTS

    assert _TUTOR_CLIENT_EVENTS == _CLIENT_DRIVABLE_EVENTS


# ── Group F — session restore on reconnect (s2-4) ─────────────────────────────


@pytest.mark.unit
async def test_f1_reconnect_syncs_state_and_no_reset(mocker):
    """A reconnect (tutor_state present) pushes a state_change sync and does NOT reset the session."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="QUIZZING")
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import ConnectionManager

    ws = AsyncMock()
    mgr = ConnectionManager()
    await mgr.connect(ws, "sess-r1")

    # On-contract ws.ts state_change (from == to, i.e. a sync, not a transition).
    ws.send_json.assert_called_once_with(
        {
            "type": "state_change",
            "payload": {"session_id": "sess-r1", "from_state": "QUIZZING", "to_state": "QUIZZING"},
        }
    )
    mock_redis.set.assert_not_called()  # reconnect must not reset state


@pytest.mark.unit
async def test_f5_reconnect_decodes_bytes_state(mocker):
    """Restore handles a bytes tutor_state (real redis without decode_responses) and any state value."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=b"TEACH_BACK")
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import ConnectionManager

    ws = AsyncMock()
    await ConnectionManager().connect(ws, "sess-bytes")

    ws.send_json.assert_called_once_with(
        {
            "type": "state_change",
            "payload": {"session_id": "sess-bytes", "from_state": "TEACH_BACK", "to_state": "TEACH_BACK"},
        }
    )


@pytest.mark.unit
async def test_f6_reconnect_send_failure_does_not_break_connect(mocker):
    """If the reconnecting socket is already gone, the failed sync send must not break connect, and the
    dead socket is dropped from the registry (no leak)."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="TEACHING")
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import ConnectionManager

    ws = AsyncMock()
    ws.send_json = AsyncMock(side_effect=RuntimeError("socket closed"))
    mgr = ConnectionManager()

    await mgr.connect(ws, "sess-deadsock")  # must not raise

    # The dead socket was reaped, not left registered.
    assert "sess-deadsock" not in mgr._connections


@pytest.mark.unit
async def test_f2_new_session_inits_and_no_sync(mocker):
    """A fresh session (no prior tutor_state) initialises and sends no sync message."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import ConnectionManager

    ws = AsyncMock()
    mgr = ConnectionManager()
    await mgr.connect(ws, "sess-new")

    mock_redis.set.assert_any_call("tutor_state:sess-new", "IDLE", ex=86400)  # fresh init
    ws.send_json.assert_not_called()  # no restore


@pytest.mark.unit
async def test_f3_reconnect_read_failure_degrades_to_init(mocker):
    """A Redis read failure on connect degrades to fresh init — never breaks the handshake."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=ConnectionError("down"))
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import ConnectionManager

    ws = AsyncMock()
    mgr = ConnectionManager()
    await mgr.connect(ws, "sess-fail")  # must not raise

    ws.send_json.assert_not_called()  # no sync message when state couldn't be read


# ── s4-5 reconnect_test: state correctly restored from Redis for ALL 7 FSM states ──


@pytest.mark.unit
@pytest.mark.parametrize(
    "state",
    ["IDLE", "TEACHING", "INTERVENING", "CHECKING_IN", "QUIZZING", "TEACH_BACK", "SESSION_END"],
)
async def test_f7_reconnect_restores_each_of_7_states(mocker, state):
    """AC: a reconnect restores the live tutor state from Redis for ALL 7 FSM states — pushes a
    state_change sync (from == to) and does not reset.

    The reconnect path now also calls _seed_learner_tier (Story 4-19 race-condition fix), which
    reads lesson_package:{sid}.  We return None for that key so no tier seeding occurs — this
    test is verifying reconnect/state-restore behaviour only, not tier seeding.
    """
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(
        side_effect=lambda key: state if "tutor_state" in key else None
    )
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)

    from app.core.websocket import ConnectionManager

    ws = AsyncMock()
    sid = f"sess-{state}"
    await ConnectionManager().connect(ws, sid)

    # tutor_state key was read (restored from Redis).
    mock_redis.get.assert_any_await(f"tutor_state:{sid}")
    # Synced to the client via the frozen state_change (from == to), and NOT reset.
    ws.send_json.assert_called_once_with(
        {"type": "state_change", "payload": {"session_id": sid, "from_state": state, "to_state": state}}
    )
    # No core session keys reset (tier keys not written — lesson package absent).
    mock_redis.set.assert_not_called()


# ── Group G — Story 4-19: Learner tier seeding (post-review patches) ──────────
#
# _seed_learner_tier (extracted from _init_session_state) reads
# lesson_package:{session_id} from Redis.  Security patches applied:
#   - session_id validated as UUID at route boundary (_SESSION_ID_RE)
#   - tier validated against allowlist {T1,T2,T3} before any Redis write
#   - metadata type-checked (isinstance dict) before .get("learner_tier")
#   - two tier keys written atomically via Redis pipeline
#   - _qa(tier) called once (assigned to qa_secs) to avoid double lookup
#   - _seed_learner_tier called on reconnect path too (race-condition fix)


def _make_pkg(tier: str | None) -> str:
    """Return a minimal lesson_package JSON with the given learner_tier."""
    pkg: dict = {"metadata": {"title": "Test"}, "segments": []}
    if tier is not None:
        pkg["metadata"]["learner_tier"] = tier
    return json.dumps(pkg)


def _mock_settings(mocker, t1=600, t2=300, t3=150, default=300):
    s = MagicMock()
    s.learner_tier_t1_qa_seconds = t1
    s.learner_tier_t2_qa_seconds = t2
    s.learner_tier_t3_qa_seconds = t3
    s.learner_tier_default_qa_seconds = default
    mocker.patch("app.config.get_settings", return_value=s)
    return s


def _make_redis_with_pipeline(pkg_json=None):
    """Return (mock_redis, mock_pipe) with pipeline wired for tier seeding tests.

    Tier keys are written via pipe.set() (MagicMock — synchronous, records calls).
    pipe.execute() is an AsyncMock.  Core session keys still go through
    mock_redis.set (AsyncMock) in _init_session_state's own try block.
    """
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=pkg_json)
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[True, True])
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)
    return mock_redis, mock_pipe


@pytest.mark.unit
async def test_g1_tier_t1_writes_600s(mocker):
    """AC2+AC3: T1 → learner_tier='T1' and qa_phase_seconds='600' via pipeline."""
    mock_redis, mock_pipe = _make_redis_with_pipeline(_make_pkg("T1"))
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)

    from app.core.websocket import _seed_learner_tier

    await _seed_learner_tier("sess-g1")

    mock_pipe.set.assert_any_call("session:sess-g1:learner_tier", "T1", ex=86400)
    mock_pipe.set.assert_any_call("session:sess-g1:qa_phase_seconds", "600", ex=86400)
    mock_pipe.execute.assert_awaited_once()


@pytest.mark.unit
async def test_g2_tier_t2_writes_300s(mocker):
    """AC3: T2 → qa_phase_seconds='300'."""
    mock_redis, mock_pipe = _make_redis_with_pipeline(_make_pkg("T2"))
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)

    from app.core.websocket import _seed_learner_tier

    await _seed_learner_tier("sess-g2")

    mock_pipe.set.assert_any_call("session:sess-g2:learner_tier", "T2", ex=86400)
    mock_pipe.set.assert_any_call("session:sess-g2:qa_phase_seconds", "300", ex=86400)


@pytest.mark.unit
async def test_g3_tier_t3_writes_150s(mocker):
    """AC3: T3 → qa_phase_seconds='150'."""
    mock_redis, mock_pipe = _make_redis_with_pipeline(_make_pkg("T3"))
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)

    from app.core.websocket import _seed_learner_tier

    await _seed_learner_tier("sess-g3")

    mock_pipe.set.assert_any_call("session:sess-g3:learner_tier", "T3", ex=86400)
    mock_pipe.set.assert_any_call("session:sess-g3:qa_phase_seconds", "150", ex=86400)


@pytest.mark.unit
async def test_g4_unknown_tier_writes_no_keys(mocker):
    """P1 (security): tier not in allowlist {T1,T2,T3} → pipeline never created, no keys written."""
    mock_redis, mock_pipe = _make_redis_with_pipeline(_make_pkg("TX"))
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)

    from app.core.websocket import _seed_learner_tier

    await _seed_learner_tier("sess-g4")

    mock_redis.pipeline.assert_not_called()
    mock_pipe.set.assert_not_called()


@pytest.mark.unit
async def test_g5_missing_cache_writes_no_tier_keys(mocker):
    """AC4: lesson_package cache absent → pipeline never created, no tier keys written."""
    mock_redis, mock_pipe = _make_redis_with_pipeline(None)
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)

    from app.core.websocket import _seed_learner_tier

    await _seed_learner_tier("sess-g5")

    mock_redis.pipeline.assert_not_called()
    mock_pipe.set.assert_not_called()


@pytest.mark.unit
async def test_g6_missing_tier_field_writes_no_tier_keys(mocker):
    """AC4: package present, no learner_tier field → pipeline never created, no tier keys written."""
    mock_redis, mock_pipe = _make_redis_with_pipeline(_make_pkg(None))
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)

    from app.core.websocket import _seed_learner_tier

    await _seed_learner_tier("sess-g6")

    mock_redis.pipeline.assert_not_called()
    mock_pipe.set.assert_not_called()


@pytest.mark.unit
async def test_g7_redis_failure_in_seed_tier_does_not_raise(mocker):
    """AC6: Redis failure during _seed_learner_tier must never crash the WS handshake."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)

    from app.core.websocket import _seed_learner_tier

    await _seed_learner_tier("sess-g7")  # must not raise


@pytest.mark.unit
def test_g8_qa_phase_seconds_helper_maps_all_tiers(mocker):
    """AC5+AC3: qa_phase_seconds() pure helper returns correct seconds for each tier."""
    _mock_settings(mocker)

    from app.modules.tutor.service import qa_phase_seconds

    assert qa_phase_seconds("T1") == 600
    assert qa_phase_seconds("T2") == 300
    assert qa_phase_seconds("T3") == 150
    assert qa_phase_seconds("TX") == 300   # unknown → default (helper still returns 300)
    assert qa_phase_seconds(None) == 300   # None → default


@pytest.mark.unit
def test_g9_settings_have_learner_tier_fields():
    """AC5: all four learner_tier_* fields exist on Settings with correct defaults."""
    from app.config import Settings

    fields = Settings.model_fields
    assert "learner_tier_t1_qa_seconds" in fields
    assert "learner_tier_t2_qa_seconds" in fields
    assert "learner_tier_t3_qa_seconds" in fields
    assert "learner_tier_default_qa_seconds" in fields

    assert fields["learner_tier_t1_qa_seconds"].default == 600
    assert fields["learner_tier_t2_qa_seconds"].default == 300
    assert fields["learner_tier_t3_qa_seconds"].default == 150
    assert fields["learner_tier_default_qa_seconds"].default == 300


@pytest.mark.unit
def test_g10_session_id_regex_accepts_valid_uuid():
    """P0: _SESSION_ID_RE accepts valid lowercase UUID format."""
    from app.core.websocket import _SESSION_ID_RE

    assert _SESSION_ID_RE.match("550e8400-e29b-41d4-a716-446655440000")
    assert _SESSION_ID_RE.match("00000000-0000-0000-0000-000000000000")
    assert _SESSION_ID_RE.match("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


@pytest.mark.unit
def test_g10b_session_id_regex_rejects_invalid_formats():
    """P0: _SESSION_ID_RE rejects non-UUID strings (prevents Redis key-namespace traversal)."""
    from app.core.websocket import _SESSION_ID_RE

    assert not _SESSION_ID_RE.match("../../etc/passwd")
    assert not _SESSION_ID_RE.match("session:other:key")
    assert not _SESSION_ID_RE.match("UPPERCASE-0000-0000-0000-000000000000")
    assert not _SESSION_ID_RE.match("")
    assert not _SESSION_ID_RE.match("not-a-uuid")
    assert not _SESSION_ID_RE.match("550e8400e29b41d4a716446655440000")  # no hyphens


@pytest.mark.unit
async def test_g11_reconnect_path_seeds_learner_tier(mocker):
    """P2 (race-condition fix): reconnect path calls _seed_learner_tier so tier is populated
    after lesson generation even when the session was first connected before the lesson was ready.
    """
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(
        side_effect=lambda key: (
            b"TEACHING" if "tutor_state" in key else _make_pkg("T2")
        )
    )
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[True, True])
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)

    from app.core.websocket import _restore_or_init_session

    result = await _restore_or_init_session(sid)

    assert result == "TEACHING"
    mock_pipe.set.assert_any_call(f"session:{sid}:learner_tier", "T2", ex=86400)
    mock_pipe.set.assert_any_call(f"session:{sid}:qa_phase_seconds", "300", ex=86400)


@pytest.mark.unit
async def test_g12_non_dict_metadata_writes_no_tier_keys(mocker):
    """P4: non-dict truthy metadata (e.g. a list) is rejected; no keys written."""
    bad_pkg = json.dumps({"metadata": ["T1"], "segments": []})  # list, not dict
    mock_redis, mock_pipe = _make_redis_with_pipeline(bad_pkg)
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)

    from app.core.websocket import _seed_learner_tier

    await _seed_learner_tier("sess-g12")

    mock_redis.pipeline.assert_not_called()
    mock_pipe.set.assert_not_called()


# ── Group H — Story 4-21: learner tier override via session_start WS payload ──
#
# _handle_session_start now accepts the full payload dict and, when the client
# supplies a valid learner_tier, OVERWRITES the 4-19 value in Redis before
# dispatching the IDLE→TEACHING event.  Precedence: 4-21 always runs after 4-19
# (session_start arrives after connect), so the WS-payload tier wins — the client
# is authoritative for the student's tier.
#
# ACs covered:
#   AC1 — signature accepts full payload; extracts payload.get("learner_tier")
#   AC2 — valid T1/T2/T3 → writes both tier keys (learner_tier + qa_phase_seconds)
#   AC3 — absent / None / unrecognised → NO tier write (4-19 value preserved)
#   AC5 — valid → write; absent → no write; invalid → no write; Redis failure → no crash
#   AC6 — session_start dispatch still fires on every path (backward compatible)


def _patch_dispatch(mocker):
    """Patch the FSM dispatch so start_session is a no-op that we can assert on."""
    mock_dispatch = AsyncMock()
    mocker.patch("app.modules.tutor.state_machine.graph.dispatch_event", mock_dispatch)
    return mock_dispatch


def _redis_with_pipe():
    """(mock_redis, mock_pipe) wired for the tier-override pipeline write.

    Tier keys go through pipe.set() (MagicMock — synchronous, records calls);
    pipe.execute() is an AsyncMock. Mirrors Group G's _make_redis_with_pipeline
    (the override path writes both keys atomically via a pipeline, per the
    code-review fix aligning 4-21 with Story 4-19's atomicity invariant).
    """
    mock_redis = AsyncMock()
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[True, True])
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)
    return mock_redis, mock_pipe


@pytest.mark.unit
@pytest.mark.parametrize("tier,secs", [("T1", "600"), ("T2", "300"), ("T3", "150")])
async def test_h1_valid_tier_overwrites_redis(mocker, tier, secs):
    """AC1+AC2+AC5: a valid tier in the session_start payload writes both tier keys atomically."""
    mock_redis, mock_pipe = _redis_with_pipe()
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)
    _patch_dispatch(mocker)

    from app.core.websocket import _handle_session_start

    await _handle_session_start("sess-h1", payload={"type": "session_start", "learner_tier": tier})

    mock_pipe.set.assert_any_call("session:sess-h1:learner_tier", tier, ex=86400)
    mock_pipe.set.assert_any_call("session:sess-h1:qa_phase_seconds", secs, ex=86400)
    mock_pipe.execute.assert_awaited_once()  # both keys committed in a single round-trip


@pytest.mark.unit
async def test_h2_valid_tier_still_dispatches_session_start(mocker):
    """AC6: seeding the tier must NOT skip the IDLE→TEACHING dispatch."""
    mock_redis, _ = _redis_with_pipe()
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)
    mock_dispatch = _patch_dispatch(mocker)

    from app.core.websocket import _handle_session_start

    await _handle_session_start("sess-h2", payload={"learner_tier": "T1"})

    mock_dispatch.assert_called_once_with("sess-h2", "session_start")


@pytest.mark.unit
async def test_h3_absent_tier_writes_no_tier_keys(mocker):
    """AC3: payload without learner_tier → no tier write (4-19 value preserved)."""
    mock_redis, mock_pipe = _redis_with_pipe()
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)
    mock_dispatch = _patch_dispatch(mocker)

    from app.core.websocket import _handle_session_start

    await _handle_session_start("sess-h3", payload={"type": "session_start"})

    mock_redis.pipeline.assert_not_called()  # nothing written for the tier
    mock_pipe.set.assert_not_called()
    mock_dispatch.assert_called_once_with("sess-h3", "session_start")  # dispatch still fires


@pytest.mark.unit
async def test_h4_none_payload_writes_no_tier_keys(mocker):
    """AC3+AC6: payload=None (backward-compatible call) → no tier write, dispatch still fires."""
    mock_redis, mock_pipe = _redis_with_pipe()
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)
    mock_dispatch = _patch_dispatch(mocker)

    from app.core.websocket import _handle_session_start

    await _handle_session_start("sess-h4", payload=None)

    mock_redis.pipeline.assert_not_called()
    mock_pipe.set.assert_not_called()
    mock_dispatch.assert_called_once_with("sess-h4", "session_start")


@pytest.mark.unit
async def test_h4b_missing_payload_arg_is_backward_compatible(mocker):
    """AC6: the original single-arg call site (Story 4-4/4-18) keeps working — no tier write."""
    mock_redis, mock_pipe = _redis_with_pipe()
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)
    mock_dispatch = _patch_dispatch(mocker)

    from app.core.websocket import _handle_session_start

    await _handle_session_start("sess-h4b")  # no payload kwarg at all

    mock_redis.pipeline.assert_not_called()
    mock_pipe.set.assert_not_called()
    mock_dispatch.assert_called_once_with("sess-h4b", "session_start")


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["T9", "t1", "T0", "", "ADMIN", "T1 ", "1"])
async def test_h5_invalid_tier_writes_no_tier_keys(mocker, bad):
    """AC3+AC5: an unrecognised tier string is rejected by the allowlist — no tier write."""
    mock_redis, mock_pipe = _redis_with_pipe()
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)
    mock_dispatch = _patch_dispatch(mocker)

    from app.core.websocket import _handle_session_start

    await _handle_session_start("sess-h5", payload={"learner_tier": bad})

    mock_redis.pipeline.assert_not_called()
    mock_pipe.set.assert_not_called()
    mock_dispatch.assert_called_once_with("sess-h5", "session_start")


@pytest.mark.unit
async def test_h6_non_string_tier_writes_no_tier_keys(mocker):
    """AC3+AC5: a non-string tier (int/list) is rejected by the isinstance guard — no tier write."""
    mock_redis, mock_pipe = _redis_with_pipe()
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)
    _patch_dispatch(mocker)

    from app.core.websocket import _handle_session_start

    await _handle_session_start("sess-h6", payload={"learner_tier": ["T1"]})

    mock_redis.pipeline.assert_not_called()
    mock_pipe.set.assert_not_called()


@pytest.mark.unit
async def test_h7_redis_failure_does_not_crash(mocker):
    """AC5: a Redis write failure during tier seeding must not crash — dispatch still fires.

    The failure is injected on pipe.execute() — the atomic commit point after the code-review
    fix — so a broken commit is exercised, and the IDLE→TEACHING dispatch must still run.
    """
    mock_redis, mock_pipe = _redis_with_pipe()
    mock_pipe.execute = AsyncMock(side_effect=ConnectionError("Redis down"))
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)
    mock_dispatch = _patch_dispatch(mocker)

    from app.core.websocket import _handle_session_start

    await _handle_session_start("sess-h7", payload={"learner_tier": "T1"})  # must not raise

    mock_dispatch.assert_called_once_with("sess-h7", "session_start")  # dispatch survives the tier failure


@pytest.mark.unit
async def test_h8_torn_write_cannot_occur_uses_single_atomic_commit(mocker):
    """Code-review fix: both tier keys are written through ONE pipeline commit, so a partial
    (fresh tier + stale qa_phase_seconds) pair is impossible — regression guard against the
    two-independent-set() torn-write defect."""
    mock_redis, mock_pipe = _redis_with_pipe()
    mocker.patch("app.core.redis.get_redis", return_value=mock_redis)
    _mock_settings(mocker)
    _patch_dispatch(mocker)

    from app.core.websocket import _handle_session_start

    await _handle_session_start("sess-h8", payload={"learner_tier": "T2"})

    mock_redis.set.assert_not_called()          # no non-atomic direct sets for the tier keys
    mock_redis.pipeline.assert_called_once()    # exactly one pipeline
    assert mock_pipe.set.call_count == 2        # both keys queued
    mock_pipe.execute.assert_awaited_once()     # committed together
