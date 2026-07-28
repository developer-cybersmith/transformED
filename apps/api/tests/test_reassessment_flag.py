"""
Unit tests for Story 3-31 — Re-assessment Prompt After 10 Sessions.

Tests cover:
  AC 1  — _REASSESSMENT_INTERVAL constant = 10
  AC 2  — fuse_learner_dna() accepts optional redis=None kwarg
  AC 3  — Step 7: Redis flag set non-fatally after upsert
  AC 4  — Flag set at sessions 10, 20, 30; NOT at 1, 11
  AC 5  — redis=None skips Step 7 entirely
  AC 6  — get_learner_dna_data() accepts optional redis=None
  AC 7  — reassessment_due=True when key exists; False when absent; False on exception
  AC 8  — redis=None path returns False without Redis call
  AC 9  — router passes get_redis() to get_learner_dna_data()
  AC 10 — submit_onboarding_diagnostic clears flag; failure is non-fatal
  AC 12 — user_id from JWT only
  AC 13 — log injection prevention (_safe_uid)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── helpers ────────────────────────────────────────────────────────────────────

NINE_DIMS = (
    "pattern_recognition",
    "logical_deduction",
    "processing_speed",
    "frustration_tolerance",
    "persistence",
    "help_seeking",
    "goal_orientation",
    "curiosity_index",
    "study_independence",
)

_DNA_FILE = Path(__file__).parent.parent / "app" / "modules" / "assessment" / "dna_fusion.py"
_SERVICE_FILE = Path(__file__).parent.parent / "app" / "modules" / "assessment" / "service.py"


def _settings():
    from app.config import Settings

    return Settings(
        supabase_url="http://x",
        supabase_anon_key="x",
        supabase_service_role_key="x",
        supabase_jwt_secret="x",
        openai_api_key="x",
        sarvam_api_key="x",
        heygen_api_key="x",
        langfuse_public_key="x",
        langfuse_secret_key="x",
    )


def _session_row(ended_at="2026-07-21T10:00:00Z", user_id="user-123"):
    return {"session_id": "sess-001", "user_id": user_id, "ended_at": ended_at}


def _dna_row(session_count: int = 9) -> dict:
    row = {dim: 75.0 for dim in NINE_DIMS}
    row["session_count"] = session_count
    return row


def _build_supabase(
    session_count: int = 9,
    growth_error: bool = False,
    user_id: str = "user-123",
) -> MagicMock:
    """Build a supabase mock suitable for fuse_learner_dna() with session_count sessions done."""
    supabase = MagicMock()

    def _resp(data):
        r = MagicMock()
        r.data = data
        r.error = None
        return r

    def _table(name):
        tbl = MagicMock()
        if name == "sessions":
            tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = _resp(
                _session_row(user_id=user_id)
            )
        elif name == "quiz_attempts":
            tbl.select.return_value.eq.return_value.execute.return_value = _resp([])
        elif name == "teachback_attempts":
            tbl.select.return_value.eq.return_value.execute.return_value = _resp([])
        elif name == "session_events":
            # Two chained calls: events for signals + events for dna_update
            tbl.select.return_value.eq.return_value.execute.return_value = _resp([])
            if growth_error:
                tbl.insert.return_value.execute.side_effect = Exception("insert failed")
            else:
                tbl.insert.return_value.execute.return_value = _resp([])
        elif name == "learner_dna":
            dna = _dna_row(session_count)
            tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = _resp(
                dna
            )
            tbl.upsert.return_value.execute.return_value = _resp([])
        return tbl

    supabase.table.side_effect = _table
    return supabase


def _build_dna_service_supabase(dna_data: dict | None = None) -> MagicMock:
    """Build supabase mock for get_learner_dna_data()."""
    supabase = MagicMock()

    def _resp(data):
        r = MagicMock()
        r.data = data
        r.error = None
        return r

    def _table(name):
        tbl = MagicMock()
        if name == "learner_dna":
            tbl.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
                _resp(dna_data)
            )
        return tbl

    supabase.table.side_effect = _table
    return supabase


_DEFAULT_DNA_ROW = {
    "user_id": "user-123",
    "badge_labels": ["Pattern Thinker"],
    "profile_text": "A dedicated learner. Data processed under DPDP Act 2023.",
    "session_count": 10,
    "last_updated": "2026-07-21T10:00:00Z",
}

# ── AC 1: _REASSESSMENT_INTERVAL constant ─────────────────────────────────────


@pytest.mark.unit
def test_reassessment_interval_constant_is_10():
    from app.modules.assessment.dna_fusion import _REASSESSMENT_INTERVAL

    assert _REASSESSMENT_INTERVAL == 10


# ── AC 2: fuse_learner_dna() accepts optional redis=None ──────────────────────


@pytest.mark.unit
def test_fuse_dna_redis_param_defaults_to_none():
    """fuse_learner_dna can be called without redis and completes normally."""
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    supabase = _build_supabase(session_count=4)
    with patch("app.modules.assessment.dna_growth.record_dna_growth", new_callable=AsyncMock):
        result = asyncio.run(
            fuse_learner_dna(
                user_id="user-123",
                session_id="sess-001",
                supabase=supabase,
                settings=_settings(),
            )
        )
    assert result is not None
    assert len(result) == 9


# ── AC 3 + AC 4: Redis flag set at session 10 ─────────────────────────────────


@pytest.mark.unit
def test_fuse_dna_sets_flag_at_session_10():
    """After session 10 (count 9→10), Redis flag is set."""
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    supabase = _build_supabase(session_count=9)  # new_count becomes 10
    mock_redis = AsyncMock()

    with patch("app.modules.assessment.dna_growth.record_dna_growth", new_callable=AsyncMock):
        asyncio.run(
            fuse_learner_dna(
                user_id="user-123",
                session_id="sess-001",
                supabase=supabase,
                settings=_settings(),
                redis=mock_redis,
            )
        )

    mock_redis.set.assert_called_once_with("user:user-123:reassessment_due", "1")


@pytest.mark.unit
def test_fuse_dna_sets_flag_at_session_20():
    """After session 20 (count 19→20), Redis flag is set."""
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    supabase = _build_supabase(session_count=19)
    mock_redis = AsyncMock()

    with patch("app.modules.assessment.dna_growth.record_dna_growth", new_callable=AsyncMock):
        asyncio.run(
            fuse_learner_dna(
                user_id="user-123",
                session_id="sess-001",
                supabase=supabase,
                settings=_settings(),
                redis=mock_redis,
            )
        )

    mock_redis.set.assert_called_once_with("user:user-123:reassessment_due", "1")


@pytest.mark.unit
def test_fuse_dna_sets_flag_at_session_30():
    """After session 30 (count 29→30), Redis flag is set."""
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    supabase = _build_supabase(session_count=29)
    mock_redis = AsyncMock()

    with patch("app.modules.assessment.dna_growth.record_dna_growth", new_callable=AsyncMock):
        asyncio.run(
            fuse_learner_dna(
                user_id="user-123",
                session_id="sess-001",
                supabase=supabase,
                settings=_settings(),
                redis=mock_redis,
            )
        )

    mock_redis.set.assert_called_once_with("user:user-123:reassessment_due", "1")


@pytest.mark.unit
def test_fuse_dna_does_not_set_flag_at_session_11():
    """session_count 10→11 is not a multiple of 10; flag must NOT be set."""
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    supabase = _build_supabase(session_count=10)  # new_count = 11
    mock_redis = AsyncMock()

    with patch("app.modules.assessment.dna_growth.record_dna_growth", new_callable=AsyncMock):
        asyncio.run(
            fuse_learner_dna(
                user_id="user-123",
                session_id="sess-001",
                supabase=supabase,
                settings=_settings(),
                redis=mock_redis,
            )
        )

    mock_redis.set.assert_not_called()


@pytest.mark.unit
def test_fuse_dna_does_not_set_flag_at_session_1():
    """First session (count 0→1) must NOT trigger the flag."""
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    supabase = _build_supabase(session_count=0)
    mock_redis = AsyncMock()

    with patch("app.modules.assessment.dna_growth.record_dna_growth", new_callable=AsyncMock):
        asyncio.run(
            fuse_learner_dna(
                user_id="user-123",
                session_id="sess-001",
                supabase=supabase,
                settings=_settings(),
                redis=mock_redis,
            )
        )

    mock_redis.set.assert_not_called()


# ── AC 3: Redis failure is non-fatal ──────────────────────────────────────────


@pytest.mark.unit
def test_fuse_dna_redis_failure_is_non_fatal():
    """Redis.set() raising an exception must not prevent fuse_learner_dna from returning."""
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    supabase = _build_supabase(session_count=9)  # new_count = 10 → triggers flag
    mock_redis = AsyncMock()
    mock_redis.set.side_effect = Exception("Redis connection reset")

    with patch("app.modules.assessment.dna_growth.record_dna_growth", new_callable=AsyncMock):
        result = asyncio.run(
            fuse_learner_dna(
                user_id="user-123",
                session_id="sess-001",
                supabase=supabase,
                settings=_settings(),
                redis=mock_redis,
            )
        )

    assert result is not None
    assert len(result) == 9


# ── AC 5: redis=None skips Step 7 ─────────────────────────────────────────────


@pytest.mark.unit
def test_fuse_dna_redis_none_skips_step7(caplog):
    """When redis=None, no Redis call is attempted (proven by zero warning logs).

    If the guard `if redis is not None` were removed, `None.set(...)` would
    raise AttributeError which is caught and logged as WARNING. The absence of
    that warning is the non-vacuous proof that the guard is working.
    """
    import logging

    from app.modules.assessment.dna_fusion import fuse_learner_dna

    supabase = _build_supabase(session_count=9)  # new_count = 10 — would trigger flag
    with (
        patch("app.modules.assessment.dna_growth.record_dna_growth", new_callable=AsyncMock),
        caplog.at_level(logging.WARNING, logger="app.modules.assessment.dna_fusion"),
    ):
        result = asyncio.run(
            fuse_learner_dna(
                user_id="user-123",
                session_id="sess-001",
                supabase=supabase,
                settings=_settings(),
                redis=None,
            )
        )

    # If guard were absent, AttributeError → except → warning logged.
    assert "reassessment flag set failed" not in caplog.text
    assert result is not None


# ── AC 6 + AC 7: get_learner_dna_data redis param ─────────────────────────────


@pytest.mark.unit
def test_get_learner_dna_data_flag_true_when_key_exists():
    """When Redis key exists (any truthy value), reassessment_due=True."""
    from app.modules.assessment.service import get_learner_dna_data

    supabase = _build_dna_service_supabase(_DEFAULT_DNA_ROW)
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="1")

    body = asyncio.run(
        get_learner_dna_data(user_id="user-123", supabase=supabase, redis=mock_redis)
    )

    assert body["reassessment_due"] is True
    mock_redis.get.assert_called_once_with("user:user-123:reassessment_due")


@pytest.mark.unit
def test_get_learner_dna_data_flag_false_when_key_absent():
    """When Redis key is absent (get returns None), reassessment_due=False."""
    from app.modules.assessment.service import get_learner_dna_data

    supabase = _build_dna_service_supabase(_DEFAULT_DNA_ROW)
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    body = asyncio.run(
        get_learner_dna_data(user_id="user-123", supabase=supabase, redis=mock_redis)
    )

    assert body["reassessment_due"] is False


@pytest.mark.unit
def test_get_learner_dna_data_flag_false_when_redis_none():
    """When redis=None, reassessment_due=False without any Redis call."""
    from app.modules.assessment.service import get_learner_dna_data

    supabase = _build_dna_service_supabase(_DEFAULT_DNA_ROW)
    mock_redis = AsyncMock()

    body = asyncio.run(
        get_learner_dna_data(user_id="user-123", supabase=supabase, redis=None)
    )

    assert body["reassessment_due"] is False
    mock_redis.get.assert_not_called()


@pytest.mark.unit
def test_get_learner_dna_data_redis_exception_returns_false():
    """Redis.get() raising an exception → reassessment_due=False (non-fatal)."""
    from app.modules.assessment.service import get_learner_dna_data

    supabase = _build_dna_service_supabase(_DEFAULT_DNA_ROW)
    mock_redis = AsyncMock()
    mock_redis.get.side_effect = Exception("timeout")

    body = asyncio.run(
        get_learner_dna_data(user_id="user-123", supabase=supabase, redis=mock_redis)
    )

    assert body["reassessment_due"] is False


# ── AC 10: submit_onboarding clears the flag ──────────────────────────────────


@pytest.mark.unit
def test_submit_onboarding_clears_reassessment_flag():
    """After successful onboarding, redis.delete(user:{uid}:reassessment_due) is called."""
    from app.modules.assessment.router import submit_onboarding_diagnostic
    from app.modules.assessment.schemas import OnboardingAnswer, OnboardingDiagnosticSubmission

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)  # onboarding_done key set OK
    mock_redis.get = AsyncMock(return_value=None)  # no reassessment pending
    mock_redis.delete = AsyncMock()

    dummy_result = MagicMock()
    dummy_responses = [
        OnboardingAnswer(
            question_id=f"q{i}",
            dimension="cognitive",
            selected_index=0,
            selected_text="Option A",
        )
        for i in range(20)
    ]
    body = OnboardingDiagnosticSubmission(responses=dummy_responses)
    current_user = {"sub": "user-123"}

    with (
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch(
            "app.modules.assessment.service.process_onboarding",
            new_callable=AsyncMock,
            return_value=dummy_result,
        ),
    ):
        asyncio.run(
            submit_onboarding_diagnostic(body=body, current_user=current_user)
        )

    # delete called for onboarding_done AND reassessment_due
    delete_keys = [c.args[0] for c in mock_redis.delete.call_args_list]
    assert "user:user-123:reassessment_due" in delete_keys


@pytest.mark.unit
def test_submit_onboarding_flag_clear_failure_is_non_fatal():
    """If reassessment flag delete raises, the onboarding result is still returned."""
    from app.modules.assessment.router import submit_onboarding_diagnostic
    from app.modules.assessment.schemas import OnboardingAnswer, OnboardingDiagnosticSubmission

    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.get = AsyncMock(return_value=None)  # no reassessment pending

    async def _selective_delete(key):
        if "reassessment_due" in key:
            raise Exception("Redis error")

    mock_redis.delete = _selective_delete

    dummy_result = MagicMock()
    dummy_responses = [
        OnboardingAnswer(
            question_id=f"q{i}",
            dimension="cognitive",
            selected_index=0,
            selected_text="Option A",
        )
        for i in range(20)
    ]
    body = OnboardingDiagnosticSubmission(responses=dummy_responses)
    current_user = {"sub": "user-123"}

    with (
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch(
            "app.modules.assessment.service.process_onboarding",
            new_callable=AsyncMock,
            return_value=dummy_result,
        ),
    ):
        result = asyncio.run(
            submit_onboarding_diagnostic(body=body, current_user=current_user)
        )

    assert result is dummy_result


# ── AC 4 negative boundary cases ──────────────────────────────────────────────


@pytest.mark.unit
def test_fuse_dna_does_not_set_flag_at_session_5():
    """session_count 4→5 is not a multiple of 10; flag must NOT be set."""
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    supabase = _build_supabase(session_count=4)
    mock_redis = AsyncMock()

    with patch("app.modules.assessment.dna_growth.record_dna_growth", new_callable=AsyncMock):
        asyncio.run(
            fuse_learner_dna(
                user_id="user-123",
                session_id="sess-001",
                supabase=supabase,
                settings=_settings(),
                redis=mock_redis,
            )
        )

    mock_redis.set.assert_not_called()


@pytest.mark.unit
def test_fuse_dna_does_not_set_flag_at_session_9():
    """session_count 8→9 is not a multiple of 10; flag must NOT be set."""
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    supabase = _build_supabase(session_count=8)
    mock_redis = AsyncMock()

    with patch("app.modules.assessment.dna_growth.record_dna_growth", new_callable=AsyncMock):
        asyncio.run(
            fuse_learner_dna(
                user_id="user-123",
                session_id="sess-001",
                supabase=supabase,
                settings=_settings(),
                redis=mock_redis,
            )
        )

    mock_redis.set.assert_not_called()


@pytest.mark.unit
def test_fuse_dna_does_not_set_flag_at_session_19():
    """session_count 18→19 is not a multiple of 10; flag must NOT be set."""
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    supabase = _build_supabase(session_count=18)
    mock_redis = AsyncMock()

    with patch("app.modules.assessment.dna_growth.record_dna_growth", new_callable=AsyncMock):
        asyncio.run(
            fuse_learner_dna(
                user_id="user-123",
                session_id="sess-001",
                supabase=supabase,
                settings=_settings(),
                redis=mock_redis,
            )
        )

    mock_redis.set.assert_not_called()


# ── AC 2: redis= is keyword-only (TypeError on positional call) ───────────────


@pytest.mark.unit
def test_fuse_dna_redis_raises_type_error_on_positional_arg():
    """Passing redis as a positional argument must raise TypeError (keyword-only guard)."""
    from app.modules.assessment.dna_fusion import fuse_learner_dna

    import inspect

    sig = inspect.signature(fuse_learner_dna)
    param = sig.parameters.get("redis")
    assert param is not None, "redis parameter must exist on fuse_learner_dna"
    assert param.kind == inspect.Parameter.KEYWORD_ONLY, (
        "redis must be keyword-only (declared after * in signature)"
    )


# ── AC 9: router passes redis client to get_learner_dna_data ─────────────────


@pytest.mark.unit
def test_get_learner_dna_router_passes_redis_client():
    """get_learner_dna handler passes redis= (not None) when get_redis() succeeds."""
    from app.modules.assessment.router import get_learner_dna

    mock_redis = AsyncMock()
    mock_dna_result = {
        "user_id": "user-123",
        "badge_labels": [],
        "profile_text": None,
        "session_count": 5,
        "reassessment_due": False,
        "last_updated": None,
    }
    current_user = {"sub": "user-123"}
    captured_call: dict = {}

    async def _capture(**kwargs):
        captured_call.update(kwargs)
        return mock_dna_result

    with (
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch("app.modules.assessment.service.get_learner_dna_data", side_effect=_capture),
        patch(
            "app.modules.assessment.service.get_analytics_consent",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("app.modules.assessment.router.capture_event"),
    ):
        asyncio.run(get_learner_dna(current_user=current_user))

    assert captured_call.get("redis") is mock_redis, (
        "router must pass the redis client to get_learner_dna_data, not None"
    )


# ── AC 13: log injection prevention ──────────────────────────────────────────


@pytest.mark.unit
def test_log_injection_prevention_strips_newlines(caplog):
    """user_id containing newlines is sanitised before appearing in log records."""
    import logging

    from app.modules.assessment.dna_fusion import fuse_learner_dna

    malicious_uid = "user-123\nINJECTED_LOG_LINE"
    supabase = _build_supabase(session_count=9, user_id=malicious_uid)
    mock_redis = AsyncMock()
    mock_redis.set.side_effect = Exception("forced error to trigger warning log")

    with (
        patch("app.modules.assessment.dna_growth.record_dna_growth", new_callable=AsyncMock),
        caplog.at_level(logging.WARNING, logger="app.modules.assessment.dna_fusion"),
    ):
        asyncio.run(
            fuse_learner_dna(
                user_id=malicious_uid,
                session_id="sess-001",
                supabase=supabase,
                settings=_settings(),
                redis=mock_redis,
            )
        )

    assert "reassessment flag set failed" in caplog.text, (
        "warning must be emitted when Redis.set raises"
    )
    # If \n were NOT stripped, the injected content would start a NEW log line.
    # After sanitisation (→ space), "INJECTED_LOG_LINE" stays on the same line as the warning.
    assert "\nINJECTED_LOG_LINE" not in caplog.text, (
        "newline must be stripped from user_id so injected text cannot start a new log line"
    )


# ── B5 validation: val == "1" strictness ──────────────────────────────────────


@pytest.mark.unit
def test_reassessment_due_false_for_non_one_redis_value():
    """reassessment_due=False when Redis returns a value other than '1'."""
    from app.modules.assessment.service import get_learner_dna_data

    supabase = _build_dna_service_supabase(_DEFAULT_DNA_ROW)
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="0")  # any non-"1" value must return False

    body = asyncio.run(
        get_learner_dna_data(user_id="user-123", supabase=supabase, redis=mock_redis)
    )

    assert body["reassessment_due"] is False


# ── B1 validation: re-assessment bypass unblocks returning users ───────────────


@pytest.mark.unit
def test_submit_onboarding_re_assessment_bypasses_idempotency_guard():
    """When reassessment_due is set, re-submission bypasses the 409 idempotency guard."""
    from app.modules.assessment.router import submit_onboarding_diagnostic
    from app.modules.assessment.schemas import OnboardingAnswer, OnboardingDiagnosticSubmission

    mock_redis = AsyncMock()
    # Simulate: onboarding_done exists (nx=True set returns None = not set)
    # reassessment_due flag IS set → bypass should delete onboarding_done first
    mock_redis.get = AsyncMock(return_value="1")  # reassessment_due present
    set_call_count = [0]

    async def _nx_set(key, value, nx=False):
        set_call_count[0] += 1
        if nx and set_call_count[0] == 1:
            return True  # after bypass delete, SET NX succeeds
        return True

    mock_redis.set = _nx_set
    mock_redis.delete = AsyncMock()

    dummy_result = MagicMock()
    dummy_responses = [
        OnboardingAnswer(
            question_id=f"q{i}",
            dimension="cognitive",
            selected_index=0,
            selected_text="Option A",
        )
        for i in range(20)
    ]
    body = OnboardingDiagnosticSubmission(responses=dummy_responses)
    current_user = {"sub": "user-123"}

    with (
        patch("app.core.redis.get_redis", return_value=mock_redis),
        patch("app.core.db.get_supabase", return_value=MagicMock()),
        patch(
            "app.modules.assessment.service.process_onboarding",
            new_callable=AsyncMock,
            return_value=dummy_result,
        ),
    ):
        result = asyncio.run(
            submit_onboarding_diagnostic(body=body, current_user=current_user)
        )

    # onboarding_done must have been deleted (bypass) before the SET NX
    delete_keys = [c.args[0] for c in mock_redis.delete.call_args_list]
    assert "user:user-123:onboarding_done" in delete_keys, (
        "bypass must delete onboarding_done when reassessment_due is set"
    )
    assert result is dummy_result
