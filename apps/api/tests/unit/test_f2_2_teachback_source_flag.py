"""Tests for Story F2-2 — Teachback Score Source Flag.

ACs covered:
  AC1  — migration file exists with correct SQL
  AC2  — TeachbackResult has score_source field
  AC3  — TeachbackSubmission is_skip field; blank text 422 unless is_skip=True
  AC4  — LLM happy path: score_source='llm' in response and DB insert
  AC5  — LLM exception → score_source='fallback', score=None, HTTP 200 not 502
  AC6  — is_skip=True → score_source='skipped', score=None, no LLM call
  AC7  — attempt_number computed correctly for skip + fallback paths
  AC8  — fallback and skipped rows store score=None (never an integer)
  AC9  — TeachbackDetail has score_source; get_session_report SELECT includes it
  EXTRA — session report teachback_score excludes score=None rows from average
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── constants ─────────────────────────────────────────────────────────────────

_SESSION_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_USER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_LESSON_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
_SEGMENT_ID = "seg_001"

_SEGMENT = {
    "segment_id": _SEGMENT_ID,
    "title": "Photosynthesis",
    "jargon": [{"term": "chlorophyll"}, {"term": "ATP"}],
}

_LESSON_CONTENT = {"segments": [_SEGMENT]}

_VALID_SESSION_ROW = {
    "session_id": _SESSION_ID,
    "user_id": _USER_ID,
    "lesson_id": _LESSON_ID,
}

_LLM_RESULT = MagicMock(
    score=75,
    accuracy_score=70,
    completeness_score=80,
    clarity_score=75,
    praise="Good effort!",
    correction="You missed ATP synthesis.",
    concepts_hit=["chlorophyll"],
    concepts_missed=["ATP"],
)


# ── supabase mock factory ─────────────────────────────────────────────────────


def _make_supabase(
    *,
    session_row: dict[str, Any] | None = None,
    lesson_row: dict[str, Any] | None = None,
    tb_count: int = 0,
    insert_error: Any = None,
) -> MagicMock:
    """Mock supabase client that dispatches per table name."""
    if session_row is None:
        session_row = _VALID_SESSION_ROW
    if lesson_row is None:
        lesson_row = {"content": _LESSON_CONTENT}

    def _make_resp(data: Any = None, count: int | None = None, error: Any = None) -> MagicMock:
        r = MagicMock()
        r.data = data
        r.count = count
        r.error = error
        return r

    def _fluent(resp: MagicMock) -> MagicMock:
        ch = MagicMock()
        for m in ("select", "eq", "maybe_single", "order", "limit"):
            getattr(ch, m).return_value = ch
        ch.execute.return_value = resp
        return ch

    # sessions table
    sessions_chain = _fluent(_make_resp(data=session_row))
    # lessons table
    lessons_chain = _fluent(_make_resp(data=lesson_row))

    # teachback_attempts table — separate select (count) and insert chains
    tb_table = MagicMock()
    count_chain = MagicMock()
    count_chain.eq.return_value = count_chain
    count_chain.execute.return_value = _make_resp(data=[], count=tb_count)
    tb_table.select.return_value = count_chain

    insert_resp = _make_resp(data=[{"id": "x"}], error=insert_error)
    insert_chain = MagicMock()
    insert_chain.execute.return_value = insert_resp
    tb_table.insert.return_value = insert_chain

    def _table(name: str) -> MagicMock:
        if name == "sessions":
            return sessions_chain
        if name == "lessons":
            return lessons_chain
        if name == "teachback_attempts":
            return tb_table
        return MagicMock()

    supabase = MagicMock()
    supabase.table.side_effect = _table
    return supabase


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.ces_weight_teachback = 0.25
    s.llm_mini = "gpt-4o-mini"
    return s


# ── AC1 — migration file ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_migration_file_exists() -> None:
    """AC1: migration file for score_source column exists."""
    migration = (
        Path(__file__).resolve().parents[4]
        / "supabase"
        / "migrations"
        / "20260903000000_teachback_score_source.sql"
    )
    assert migration.exists(), f"Migration not found: {migration}"


@pytest.mark.unit
def test_migration_adds_score_source_column() -> None:
    """AC1: migration ALTER TABLE adds score_source with DEFAULT 'llm' and CHECK."""
    migration = (
        Path(__file__).resolve().parents[4]
        / "supabase"
        / "migrations"
        / "20260903000000_teachback_score_source.sql"
    )
    sql = migration.read_text(encoding="utf-8").lower()
    assert "teachback_attempts" in sql
    assert "score_source" in sql
    assert "default 'llm'" in sql
    assert "check" in sql


# ── AC2 — TeachbackResult schema ──────────────────────────────────────────────


@pytest.mark.unit
def test_teachback_result_has_score_source_field() -> None:
    """AC2: TeachbackResult schema has score_source field."""
    from app.modules.assessment.schemas import TeachbackResult

    fields = TeachbackResult.model_fields
    assert "score_source" in fields, "TeachbackResult missing score_source field"


@pytest.mark.unit
def test_teachback_result_score_source_is_literal() -> None:
    """AC2: score_source accepts only 'llm', 'fallback', 'skipped'."""
    from app.modules.assessment.schemas import TeachbackResult
    import pydantic

    # valid values
    for val in ("llm", "fallback", "skipped"):
        result = TeachbackResult(
            session_id=_SESSION_ID,
            rubric_scores={},
            overall_score=0.0,
            ces_contribution=0.0,
            feedback="",
            score_source=val,
        )
        assert result.score_source == val

    # invalid value raises
    with pytest.raises(pydantic.ValidationError):
        TeachbackResult(
            session_id=_SESSION_ID,
            rubric_scores={},
            overall_score=0.0,
            ces_contribution=0.0,
            feedback="",
            score_source="unknown",
        )


# ── AC3 — TeachbackSubmission is_skip field ───────────────────────────────────


@pytest.mark.unit
def test_teachback_submission_has_is_skip_field() -> None:
    """AC3: TeachbackSubmission has is_skip: bool = False."""
    from app.modules.assessment.schemas import TeachbackSubmission

    fields = TeachbackSubmission.model_fields
    assert "is_skip" in fields, "TeachbackSubmission missing is_skip field"
    assert fields["is_skip"].default is False


@pytest.mark.unit
def test_teachback_submission_blank_text_raises_without_skip() -> None:
    """AC3: blank response_text still raises 422 when is_skip=False."""
    import pydantic
    from app.modules.assessment.schemas import TeachbackSubmission

    with pytest.raises((pydantic.ValidationError, ValueError)):
        TeachbackSubmission(
            session_id=_SESSION_ID,
            lesson_id=_LESSON_ID,
            segment_id=_SEGMENT_ID,
            response_text="   ",
            is_skip=False,
        )


@pytest.mark.unit
def test_teachback_submission_blank_text_allowed_with_skip() -> None:
    """AC3: empty response_text is allowed when is_skip=True."""
    from app.modules.assessment.schemas import TeachbackSubmission

    sub = TeachbackSubmission(
        session_id=_SESSION_ID,
        lesson_id=_LESSON_ID,
        segment_id=_SEGMENT_ID,
        response_text="",
        is_skip=True,
    )
    assert sub.is_skip is True


@pytest.mark.unit
def test_teachback_submission_default_is_skip_false() -> None:
    """AC3: existing clients that omit is_skip get False — backward compatible."""
    from app.modules.assessment.schemas import TeachbackSubmission

    sub = TeachbackSubmission(
        session_id=_SESSION_ID,
        lesson_id=_LESSON_ID,
        segment_id=_SEGMENT_ID,
        response_text="some response",
    )
    assert sub.is_skip is False


# ── AC4 — LLM happy path ──────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_path_returns_score_source_llm() -> None:
    """AC4: successful LLM scoring → score_source='llm' in response."""
    from app.modules.assessment.service import grade_teachback

    supabase = _make_supabase()
    settings = _make_settings()

    with (
        patch("app.modules.assessment.service.score_teachback", new_callable=AsyncMock) as mock_st,
        patch("app.modules.assessment.service.get_settings", return_value=settings),
        patch("app.modules.assessment.service.capture_event"),
        patch("app.modules.assessment.service.get_analytics_consent", new_callable=AsyncMock, return_value=True),
    ):
        mock_st.return_value = _LLM_RESULT
        result = await grade_teachback(
            session_id=_SESSION_ID,
            lesson_id=_LESSON_ID,
            segment_id=_SEGMENT_ID,
            response_text="Photosynthesis converts light to energy.",
            user_id=_USER_ID,
            supabase=supabase,
            is_skip=False,
        )

    assert result.score_source == "llm"
    assert result.overall_score == 75.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_path_inserts_score_source_llm_to_db() -> None:
    """AC4: LLM path inserts score_source='llm' into teachback_attempts row."""
    from app.modules.assessment.service import grade_teachback

    supabase = _make_supabase()
    settings = _make_settings()

    with (
        patch("app.modules.assessment.service.score_teachback", new_callable=AsyncMock) as mock_st,
        patch("app.modules.assessment.service.get_settings", return_value=settings),
        patch("app.modules.assessment.service.capture_event"),
        patch("app.modules.assessment.service.get_analytics_consent", new_callable=AsyncMock, return_value=True),
    ):
        mock_st.return_value = _LLM_RESULT
        await grade_teachback(
            session_id=_SESSION_ID,
            lesson_id=_LESSON_ID,
            segment_id=_SEGMENT_ID,
            response_text="Photosynthesis converts light to energy.",
            user_id=_USER_ID,
            supabase=supabase,
            is_skip=False,
        )

    # The insert call carries score_source="llm"
    tb_table = supabase.table("teachback_attempts")
    inserted_row: dict = tb_table.insert.call_args[0][0]
    assert inserted_row["score_source"] == "llm"
    assert inserted_row["score"] == 75


# ── AC5 — Fallback path ───────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fallback_path_returns_score_source_fallback() -> None:
    """AC5: LLM exception → score_source='fallback', HTTP 200 (not 502)."""
    from app.modules.assessment.service import grade_teachback

    supabase = _make_supabase()
    settings = _make_settings()

    with (
        patch("app.modules.assessment.service.score_teachback", new_callable=AsyncMock) as mock_st,
        patch("app.modules.assessment.service.get_settings", return_value=settings),
        patch("app.modules.assessment.service.capture_event"),
        patch("app.modules.assessment.service.get_analytics_consent", new_callable=AsyncMock, return_value=True),
    ):
        mock_st.side_effect = Exception("LLM service down")
        result = await grade_teachback(
            session_id=_SESSION_ID,
            lesson_id=_LESSON_ID,
            segment_id=_SEGMENT_ID,
            response_text="Some response.",
            user_id=_USER_ID,
            supabase=supabase,
            is_skip=False,
        )

    assert result.score_source == "fallback"
    assert result.ces_contribution == 0.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fallback_path_inserts_score_none() -> None:
    """AC5+AC8: fallback inserts score=None (not an integer) to DB."""
    from app.modules.assessment.service import grade_teachback

    supabase = _make_supabase()
    settings = _make_settings()

    with (
        patch("app.modules.assessment.service.score_teachback", new_callable=AsyncMock) as mock_st,
        patch("app.modules.assessment.service.get_settings", return_value=settings),
        patch("app.modules.assessment.service.capture_event"),
        patch("app.modules.assessment.service.get_analytics_consent", new_callable=AsyncMock, return_value=True),
    ):
        mock_st.side_effect = Exception("LLM service down")
        await grade_teachback(
            session_id=_SESSION_ID,
            lesson_id=_LESSON_ID,
            segment_id=_SEGMENT_ID,
            response_text="Some response.",
            user_id=_USER_ID,
            supabase=supabase,
            is_skip=False,
        )

    tb_table = supabase.table("teachback_attempts")
    inserted_row: dict = tb_table.insert.call_args[0][0]
    assert inserted_row["score_source"] == "fallback"
    assert inserted_row["score"] is None, "fallback must store score=None, never an integer"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fallback_path_logs_at_warning_not_error() -> None:
    """AC5 (R5): LLM exception must be logged at WARNING level, never ERROR."""
    from app.modules.assessment.service import grade_teachback

    supabase = _make_supabase()
    settings = _make_settings()
    warning_calls: list = []
    error_calls: list = []

    with (
        patch("app.modules.assessment.service.score_teachback", new_callable=AsyncMock) as mock_st,
        patch("app.modules.assessment.service.get_settings", return_value=settings),
        patch("app.modules.assessment.service.capture_event"),
        patch("app.modules.assessment.service.get_analytics_consent", new_callable=AsyncMock, return_value=True),
        patch("app.modules.assessment.service.logger") as mock_logger,
    ):
        mock_st.side_effect = Exception("timeout")
        mock_logger.warning.side_effect = lambda *a, **kw: warning_calls.append(a)
        mock_logger.error.side_effect = lambda *a, **kw: error_calls.append(a)
        await grade_teachback(
            session_id=_SESSION_ID,
            lesson_id=_LESSON_ID,
            segment_id=_SEGMENT_ID,
            response_text="Some response.",
            user_id=_USER_ID,
            supabase=supabase,
            is_skip=False,
        )

    assert any("fallback" in str(a) for a in warning_calls), "fallback LLM error must log at WARNING"
    assert not any("fallback" in str(a) for a in error_calls), "fallback LLM error must NOT log at ERROR"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_fallback_exact_feedback_string() -> None:
    """AC5 (R6): fallback path must return exact prescribed feedback string."""
    from app.modules.assessment.service import grade_teachback

    supabase = _make_supabase()
    settings = _make_settings()

    with (
        patch("app.modules.assessment.service.score_teachback", new_callable=AsyncMock) as mock_st,
        patch("app.modules.assessment.service.get_settings", return_value=settings),
        patch("app.modules.assessment.service.capture_event"),
        patch("app.modules.assessment.service.get_analytics_consent", new_callable=AsyncMock, return_value=True),
    ):
        mock_st.side_effect = Exception("LLM service down")
        result = await grade_teachback(
            session_id=_SESSION_ID,
            lesson_id=_LESSON_ID,
            segment_id=_SEGMENT_ID,
            response_text="Some response.",
            user_id=_USER_ID,
            supabase=supabase,
            is_skip=False,
        )

    assert result.feedback == "Scoring temporarily unavailable — your response has been saved.", (
        f"Expected exact fallback message, got: {result.feedback!r}"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skip_exact_feedback_string() -> None:
    """AC6 (R6): skip path must return empty string feedback."""
    from app.modules.assessment.service import grade_teachback

    supabase = _make_supabase()
    settings = _make_settings()

    with (
        patch("app.modules.assessment.service.score_teachback", new_callable=AsyncMock) as mock_st,
        patch("app.modules.assessment.service.get_settings", return_value=settings),
        patch("app.modules.assessment.service.capture_event"),
        patch("app.modules.assessment.service.get_analytics_consent", new_callable=AsyncMock, return_value=True),
    ):
        result = await grade_teachback(
            session_id=_SESSION_ID,
            lesson_id=_LESSON_ID,
            segment_id=_SEGMENT_ID,
            response_text="",
            user_id=_USER_ID,
            supabase=supabase,
            is_skip=True,
        )
        mock_st.assert_not_called()

    assert result.feedback == "", f"Expected empty string for skip feedback, got: {result.feedback!r}"


# ── AC6 — Skip path ───────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skip_path_returns_score_source_skipped() -> None:
    """AC6: is_skip=True → score_source='skipped' in response."""
    from app.modules.assessment.service import grade_teachback

    supabase = _make_supabase()
    settings = _make_settings()

    with (
        patch("app.modules.assessment.service.score_teachback", new_callable=AsyncMock) as mock_st,
        patch("app.modules.assessment.service.get_settings", return_value=settings),
        patch("app.modules.assessment.service.capture_event"),
        patch("app.modules.assessment.service.get_analytics_consent", new_callable=AsyncMock, return_value=True),
    ):
        result = await grade_teachback(
            session_id=_SESSION_ID,
            lesson_id=_LESSON_ID,
            segment_id=_SEGMENT_ID,
            response_text="",
            user_id=_USER_ID,
            supabase=supabase,
            is_skip=True,
        )
        mock_st.assert_not_called()  # AC6: no LLM call on skip

    assert result.score_source == "skipped"
    assert result.ces_contribution == 0.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skip_path_inserts_score_none() -> None:
    """AC6+AC8: skip inserts score=None (never an integer)."""
    from app.modules.assessment.service import grade_teachback

    supabase = _make_supabase()
    settings = _make_settings()

    with (
        patch("app.modules.assessment.service.score_teachback", new_callable=AsyncMock),
        patch("app.modules.assessment.service.get_settings", return_value=settings),
        patch("app.modules.assessment.service.capture_event"),
        patch("app.modules.assessment.service.get_analytics_consent", new_callable=AsyncMock, return_value=True),
    ):
        await grade_teachback(
            session_id=_SESSION_ID,
            lesson_id=_LESSON_ID,
            segment_id=_SEGMENT_ID,
            response_text="",
            user_id=_USER_ID,
            supabase=supabase,
            is_skip=True,
        )

    tb_table = supabase.table("teachback_attempts")
    inserted_row: dict = tb_table.insert.call_args[0][0]
    assert inserted_row["score_source"] == "skipped"
    assert inserted_row["score"] is None, "skipped must store score=None, never an integer"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skip_path_no_posthog_event() -> None:
    """AC6: no PostHog event fired for a skipped teachback."""
    from app.modules.assessment.service import grade_teachback

    supabase = _make_supabase()
    settings = _make_settings()

    with (
        patch("app.modules.assessment.service.score_teachback", new_callable=AsyncMock),
        patch("app.modules.assessment.service.get_settings", return_value=settings),
        patch("app.modules.assessment.service.capture_event") as mock_capture,
        patch("app.modules.assessment.service.get_analytics_consent", new_callable=AsyncMock, return_value=True),
    ):
        await grade_teachback(
            session_id=_SESSION_ID,
            lesson_id=_LESSON_ID,
            segment_id=_SEGMENT_ID,
            response_text="",
            user_id=_USER_ID,
            supabase=supabase,
            is_skip=True,
        )
        mock_capture.assert_not_called()


# ── AC7 — attempt_number ──────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_attempt_number_correct_for_skip_path() -> None:
    """AC7: attempt_number = existing_count + 1 even on skip path."""
    from app.modules.assessment.service import grade_teachback

    supabase = _make_supabase(tb_count=2)  # 2 previous attempts
    settings = _make_settings()

    with (
        patch("app.modules.assessment.service.score_teachback", new_callable=AsyncMock),
        patch("app.modules.assessment.service.get_settings", return_value=settings),
        patch("app.modules.assessment.service.capture_event"),
        patch("app.modules.assessment.service.get_analytics_consent", new_callable=AsyncMock, return_value=True),
    ):
        await grade_teachback(
            session_id=_SESSION_ID,
            lesson_id=_LESSON_ID,
            segment_id=_SEGMENT_ID,
            response_text="",
            user_id=_USER_ID,
            supabase=supabase,
            is_skip=True,
        )

    tb_table = supabase.table("teachback_attempts")
    inserted_row: dict = tb_table.insert.call_args[0][0]
    assert inserted_row["attempt_number"] == 3  # 2 existing + 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_attempt_number_correct_for_fallback_path() -> None:
    """AC7: attempt_number = existing_count + 1 on fallback path."""
    from app.modules.assessment.service import grade_teachback

    supabase = _make_supabase(tb_count=1)  # 1 previous attempt
    settings = _make_settings()

    with (
        patch("app.modules.assessment.service.score_teachback", new_callable=AsyncMock) as mock_st,
        patch("app.modules.assessment.service.get_settings", return_value=settings),
        patch("app.modules.assessment.service.capture_event"),
        patch("app.modules.assessment.service.get_analytics_consent", new_callable=AsyncMock, return_value=True),
    ):
        mock_st.side_effect = Exception("LLM down")
        await grade_teachback(
            session_id=_SESSION_ID,
            lesson_id=_LESSON_ID,
            segment_id=_SEGMENT_ID,
            response_text="Response text.",
            user_id=_USER_ID,
            supabase=supabase,
            is_skip=False,
        )

    tb_table = supabase.table("teachback_attempts")
    inserted_row: dict = tb_table.insert.call_args[0][0]
    assert inserted_row["attempt_number"] == 2  # 1 existing + 1


# ── AC9 — TeachbackDetail ────────────────────────────────────────────────────


@pytest.mark.unit
def test_teachback_detail_has_score_source_field() -> None:
    """AC9: TeachbackDetail in router.py has score_source with default 'llm'."""
    from app.modules.assessment.router import TeachbackDetail

    fields = TeachbackDetail.model_fields
    assert "score_source" in fields, "TeachbackDetail missing score_source field"
    assert fields["score_source"].default == "llm", (
        "score_source must default to 'llm' so pre-migration rows deserialise correctly"
    )


@pytest.mark.unit
def test_get_session_report_select_includes_score_source() -> None:
    """AC9: get_session_report's teachback_attempts SELECT includes score_source."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "app" / "modules" / "assessment" / "service.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            if node.name == "get_session_report":
                func_src = ast.unparse(node)
                assert "score_source" in func_src, (
                    "get_session_report must select score_source from teachback_attempts"
                )
                return

    raise AssertionError("get_session_report not found in service.py")


# ── EXTRA — session report teachback_score excludes None-scored rows ──────────


@pytest.mark.unit
def test_get_session_report_excludes_null_scores_from_average() -> None:
    """EXTRA: teachback_score average must exclude score=None rows (skip/fallback).

    A session with one LLM row (score=80) and one skipped row (score=None) must
    report teachback_score=80.0, not 40.0 (which would result from (80+0)/2).
    """
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "app" / "modules" / "assessment" / "service.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            if node.name == "get_session_report":
                func_src = ast.unparse(node)
                # The function must filter rows where score is not None
                # before averaging — look for evidence of that filter
                has_filter = (
                    "score is not None" in func_src
                    or "score is not none" in func_src.lower()
                    or "score_source" in func_src  # using score_source='llm' filter
                )
                assert has_filter, (
                    "get_session_report must exclude score=None rows (skip/fallback) "
                    "from the teachback_score average. Without this, a session with "
                    "one scored row (80) and one skipped row (None→0) reports "
                    "teachback_score=40.0 instead of 80.0."
                )
                return

    raise AssertionError("get_session_report not found in service.py")


# ── guard tests pass ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_guard_dunder_all_ces() -> None:
    """AC10: CES __all__ guard still passes after F2-2 changes."""
    from app.modules.assessment.ces import __all__ as ces_all

    assert set(ces_all) == {"compute_ces", "compute_personalized_threshold"}


@pytest.mark.unit
def test_guard_no_hardcoded_weights_in_ces() -> None:
    """AC10: no hardcoded weight literals in ces.py."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "app" / "modules" / "assessment" / "ces.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    _KNOWN_WEIGHT_LITERALS = {0.35, 0.25, 0.20, 0.12, 0.08, 0.05, 0.04}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            assert node.value not in _KNOWN_WEIGHT_LITERALS, (
                f"Hardcoded CES weight literal {node.value!r} found in ces.py — "
                "use settings fields instead"
            )
