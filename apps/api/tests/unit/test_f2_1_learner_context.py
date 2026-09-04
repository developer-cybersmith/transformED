"""Unit tests for GET /api/assessment/session/{session_id}/learner-context (Story F2-1).

All tests are @pytest.mark.unit — no real Supabase connection required.
asyncio.to_thread is shimmed to run synchronously so MagicMock chains work.

Covers:
  AC1  — 200 response with LearnerContext body
  AC2  — IDOR: 404 unified message for wrong-user sessions
  AC3  — DNA block populated when learner_dna row exists
  AC4  — DNA block is null when no learner_dna row exists
  AC5  — current_session block: quiz_accuracy, quiz_total, teachback_score, teachback_count, ces_score
  AC6  — prompt_text is LLM-ready (no raw numeric dimension values)
  AC7  — prompt_text is "" when no context exists
  AC8  — bounded queries (source scan, test_unbounded_queries.py is authoritative guard)
  AC9  — no LLM calls, no hardcoded model strings
  AC10 — LearnerContext in schemas.__all__
  AC11 — no transcript / duration_seconds / raw numeric scores in student-visible fields
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

# ── Path constants (source scan tests) ────────────────────────────────────────

_API_ROOT = Path(__file__).parents[2] / "app"
_SERVICE_PATH = _API_ROOT / "modules" / "assessment" / "service.py"
_SCHEMAS_PATH = _API_ROOT / "modules" / "assessment" / "schemas.py"
_ROUTER_PATH = _API_ROOT / "modules" / "assessment" / "router.py"


# ── Fixtures: fake data ────────────────────────────────────────────────────────

_USER_ID = "aaaaaaaa-0000-0000-0000-000000000001"
_OTHER_USER_ID = "bbbbbbbb-0000-0000-0000-000000000002"
_SESSION_ID = "cccccccc-0000-0000-0000-000000000003"
_LESSON_ID = "dddddddd-0000-0000-0000-000000000004"

_SESSION_ROW = {
    "session_id": _SESSION_ID,
    "user_id": _USER_ID,
    "lesson_id": _LESSON_ID,
    "ces_final": 71.50,
}

_DNA_ROW = {
    "user_id": _USER_ID,
    "pattern_recognition": 78.0,
    "logical_deduction": 62.5,
    "processing_speed": 55.0,
    "frustration_tolerance": 48.0,
    "persistence": 80.0,
    "help_seeking": 43.0,
    "goal_orientation": 70.0,
    "curiosity_index": 88.0,
    "study_independence": 66.0,
    "badge_labels": ["Pattern Thinker", "Curious Explorer"],
    "profile_text": "You tend to learn through patterns. — Pursuant to DPDP Act 2023.",
    "session_count": 4,
    "last_updated": "2026-09-04T10:00:00+00:00",
}

_QUIZ_ROWS = [
    {"is_correct": True},
    {"is_correct": True},
    {"is_correct": False},
    {"is_correct": True},
]  # accuracy = 3/4 = 0.75

_TEACHBACK_ROWS = [
    {"score": 80},
    {"score": 60},
]  # avg = 70.0


# ── HTTP layer setup ───────────────────────────────────────────────────────────


async def _fake_user() -> dict:
    return {"sub": _USER_ID, "email": "student@example.com"}


def _make_app():
    from app.dependencies import get_current_user
    from app.modules.assessment.router import router

    app = FastAPI()
    app.dependency_overrides[get_current_user] = _fake_user
    app.include_router(router, prefix="/api/assessment")
    return app


# ── Helpers ────────────────────────────────────────────────────────────────────


def _mock_supabase(
    *,
    session_row: dict | None = _SESSION_ROW,
    dna_row: dict | None = _DNA_ROW,
    quiz_rows: list[dict] | None = None,
    teachback_rows: list[dict] | None = None,
) -> MagicMock:
    """Build a Supabase client mock returning the given rows."""
    if quiz_rows is None:
        quiz_rows = _QUIZ_ROWS
    if teachback_rows is None:
        teachback_rows = _TEACHBACK_ROWS

    supabase = MagicMock()

    def _table_select(table_name: str):
        m = MagicMock()

        def _chain_sessions():
            chain = MagicMock()
            chain.eq.return_value = chain
            chain.is_.return_value = chain
            execute_resp = MagicMock()
            execute_resp.data = [session_row] if session_row else []
            chain.maybe_single.return_value.execute.return_value = execute_resp
            return chain

        def _chain_dna():
            chain = MagicMock()
            chain.eq.return_value = chain
            execute_resp = MagicMock()
            execute_resp.data = [dna_row] if dna_row else []
            chain.maybe_single.return_value.execute.return_value = execute_resp
            return chain

        def _chain_quiz():
            chain = MagicMock()
            chain.eq.return_value = chain
            execute_resp = MagicMock()
            execute_resp.data = quiz_rows or []
            chain.execute.return_value = execute_resp
            return chain

        def _chain_teachback():
            chain = MagicMock()
            chain.eq.return_value = chain
            execute_resp = MagicMock()
            execute_resp.data = teachback_rows or []
            chain.execute.return_value = execute_resp
            return chain

        if table_name == "sessions":
            m.select.return_value = _chain_sessions()
        elif table_name == "learner_dna":
            m.select.return_value = _chain_dna()
        elif table_name == "quiz_attempts":
            m.select.return_value = _chain_quiz()
        elif table_name == "teachback_attempts":
            m.select.return_value = _chain_teachback()
        else:
            m.select.return_value = MagicMock()

        return m

    supabase.table.side_effect = _table_select
    return supabase


# ══════════════════════════════════════════════════════════════════════════════
# AC10 — Schema presence guard (runs first, no network needed)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_learner_context_in_schemas_all():
    """AC10: LearnerContext (and its sub-schemas) must be exported in schemas.__all__."""
    from app.modules.assessment import schemas

    assert "LearnerContext" in schemas.__all__, (
        "LearnerContext missing from schemas.__all__ — add it so imports work across modules"
    )
    assert "LearnerContextDNA" in schemas.__all__, (
        "LearnerContextDNA missing from schemas.__all__"
    )
    assert "LearnerContextSession" in schemas.__all__, (
        "LearnerContextSession missing from schemas.__all__"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — 200 response with full LearnerContext body
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn())
@patch("app.modules.assessment.service.single_row")
def test_learner_context_200_happy_path(mock_single_row, mock_to_thread):
    """AC1: Authenticated student's own session returns 200 with LearnerContext."""
    mock_single_row.side_effect = lambda resp: resp.data[0] if resp.data else None

    client = TestClient(_make_app(), raise_server_exceptions=False)

    with patch("app.core.db.get_supabase", return_value=_mock_supabase()):
        resp = client.get(f"/api/assessment/session/{_SESSION_ID}/learner-context")

    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == _SESSION_ID
    assert body["user_id"] == _USER_ID
    assert "dna" in body
    assert "current_session" in body
    assert "prompt_text" in body


# ══════════════════════════════════════════════════════════════════════════════
# AC2 — IDOR protection
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn())
@patch("app.modules.assessment.service.single_row")
def test_learner_context_idor_returns_404(mock_single_row, mock_to_thread):
    """AC2: Session belonging to a different user returns 404 with unified message."""
    other_session = {**_SESSION_ROW, "user_id": _OTHER_USER_ID}
    mock_single_row.side_effect = lambda resp: resp.data[0] if resp.data else None

    client = TestClient(_make_app(), raise_server_exceptions=False)

    with patch("app.core.db.get_supabase", return_value=_mock_supabase(session_row=other_session)):
        resp = client.get(f"/api/assessment/session/{_SESSION_ID}/learner-context")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Session not found or access denied."


@pytest.mark.unit
@patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn())
@patch("app.modules.assessment.service.single_row")
def test_learner_context_missing_session_returns_404(mock_single_row, mock_to_thread):
    """AC2: Non-existent session_id returns 404 (same message — no existence oracle)."""
    mock_single_row.side_effect = lambda resp: resp.data[0] if resp.data else None

    client = TestClient(_make_app(), raise_server_exceptions=False)

    with patch("app.core.db.get_supabase", return_value=_mock_supabase(session_row=None)):
        resp = client.get(f"/api/assessment/session/{_SESSION_ID}/learner-context")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Session not found or access denied."


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — DNA block populated
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn())
@patch("app.modules.assessment.service.single_row")
def test_dna_block_populated_when_row_exists(mock_single_row, mock_to_thread):
    """AC3: When learner_dna row exists, dna block has badges, profile_text, session_count, dimension_labels."""
    mock_single_row.side_effect = lambda resp: resp.data[0] if resp.data else None

    from app.modules.assessment.service import get_learner_context

    import asyncio

    result = asyncio.get_event_loop().run_until_complete(
        get_learner_context(
            session_id=_SESSION_ID,
            user_id=_USER_ID,
            supabase=_mock_supabase(),
        )
    )

    assert result.dna is not None
    assert set(result.dna.badge_labels) == {"Pattern Thinker", "Curious Explorer"}
    assert result.dna.profile_text is not None
    assert "DPDP Act 2023" in result.dna.profile_text
    assert result.dna.session_count == 4
    # dimension_labels uses descriptive bands, not raw floats
    labels = result.dna.dimension_labels
    assert isinstance(labels, dict)
    assert set(labels.keys()) == {
        "pattern_recognition", "logical_deduction", "processing_speed",
        "frustration_tolerance", "persistence", "help_seeking",
        "goal_orientation", "curiosity_index", "study_independence",
    }
    for key, band in labels.items():
        assert band in ("strong", "developing", "building", "emerging"), (
            f"{key} has invalid band {band!r}"
        )
    # pattern_recognition=78.0 → "strong"; curiosity_index=88.0 → "strong"
    assert labels["pattern_recognition"] == "strong"
    assert labels["curiosity_index"] == "strong"
    # help_seeking=43.0 → "building" (35≤x<55)
    assert labels["help_seeking"] == "building"


# ══════════════════════════════════════════════════════════════════════════════
# AC4 — DNA block null when no row
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn())
@patch("app.modules.assessment.service.single_row")
def test_dna_block_null_when_no_onboarding(mock_single_row, mock_to_thread):
    """AC4: When no learner_dna row exists, dna is None and endpoint still returns 200."""
    mock_single_row.side_effect = lambda resp: resp.data[0] if resp.data else None

    client = TestClient(_make_app(), raise_server_exceptions=False)

    with patch("app.core.db.get_supabase", return_value=_mock_supabase(dna_row=None)):
        resp = client.get(f"/api/assessment/session/{_SESSION_ID}/learner-context")

    assert resp.status_code == 200
    body = resp.json()
    assert body["dna"] is None


# ══════════════════════════════════════════════════════════════════════════════
# AC5 — current_session block
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn())
@patch("app.modules.assessment.service.single_row")
def test_current_session_block_computed_correctly(mock_single_row, mock_to_thread):
    """AC5: quiz_accuracy, quiz_total, teachback_score, teachback_count, ces_score computed correctly."""
    mock_single_row.side_effect = lambda resp: resp.data[0] if resp.data else None

    from app.modules.assessment.service import get_learner_context
    import asyncio

    result = asyncio.get_event_loop().run_until_complete(
        get_learner_context(
            session_id=_SESSION_ID,
            user_id=_USER_ID,
            supabase=_mock_supabase(),
        )
    )

    cs = result.current_session
    assert cs.quiz_total == 4
    assert abs(cs.quiz_accuracy - 0.75) < 0.01  # 3/4
    assert cs.teachback_count == 2
    assert abs(cs.teachback_score - 70.0) < 0.01  # (80+60)/2
    assert abs(cs.ces_score - 71.50) < 0.01


@pytest.mark.unit
@patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn())
@patch("app.modules.assessment.service.single_row")
def test_current_session_none_when_no_attempts(mock_single_row, mock_to_thread):
    """AC5: When no quiz/teachback rows, accuracy and score are None; totals are 0."""
    mock_single_row.side_effect = lambda resp: resp.data[0] if resp.data else None

    session_no_ces = {**_SESSION_ROW, "ces_final": None}

    from app.modules.assessment.service import get_learner_context
    import asyncio

    result = asyncio.get_event_loop().run_until_complete(
        get_learner_context(
            session_id=_SESSION_ID,
            user_id=_USER_ID,
            supabase=_mock_supabase(
                session_row=session_no_ces,
                quiz_rows=[],
                teachback_rows=[],
            ),
        )
    )

    cs = result.current_session
    assert cs.quiz_accuracy is None
    assert cs.quiz_total == 0
    assert cs.teachback_score is None
    assert cs.teachback_count == 0
    assert cs.ces_score is None


# ══════════════════════════════════════════════════════════════════════════════
# AC6 — prompt_text is LLM-ready with no raw floats
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn())
@patch("app.modules.assessment.service.single_row")
def test_prompt_text_contains_no_raw_floats(mock_single_row, mock_to_thread):
    """AC6: prompt_text never contains bare float literals (e.g., '78.0', '62.5')."""
    mock_single_row.side_effect = lambda resp: resp.data[0] if resp.data else None

    from app.modules.assessment.service import get_learner_context
    import asyncio

    result = asyncio.get_event_loop().run_until_complete(
        get_learner_context(
            session_id=_SESSION_ID,
            user_id=_USER_ID,
            supabase=_mock_supabase(),
        )
    )

    # Raw dimension values from _DNA_ROW (e.g. 78.0, 62.5) must not appear
    raw_dim_values = [
        "78.0", "62.5", "55.0", "48.0", "80.0", "43.0", "70.0", "88.0", "66.0",
    ]
    for val in raw_dim_values:
        assert val not in result.prompt_text, (
            f"Raw numeric dimension value {val!r} found in prompt_text — "
            "use descriptive bands only (CLAUDE.md Learner DNA display rules)"
        )


@pytest.mark.unit
@patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn())
@patch("app.modules.assessment.service.single_row")
def test_prompt_text_is_non_empty_when_context_exists(mock_single_row, mock_to_thread):
    """AC6: prompt_text is a non-empty string when dna or session data is present."""
    mock_single_row.side_effect = lambda resp: resp.data[0] if resp.data else None

    from app.modules.assessment.service import get_learner_context
    import asyncio

    result = asyncio.get_event_loop().run_until_complete(
        get_learner_context(
            session_id=_SESSION_ID,
            user_id=_USER_ID,
            supabase=_mock_supabase(),
        )
    )

    assert isinstance(result.prompt_text, str)
    assert len(result.prompt_text) > 0


# ══════════════════════════════════════════════════════════════════════════════
# AC7 — prompt_text is "" when no context exists
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
@patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn())
@patch("app.modules.assessment.service.single_row")
def test_prompt_text_empty_string_when_no_context(mock_single_row, mock_to_thread):
    """AC7: prompt_text is '' (not null) when dna=null and no session signals."""
    mock_single_row.side_effect = lambda resp: resp.data[0] if resp.data else None

    session_no_ces = {**_SESSION_ROW, "ces_final": None}

    from app.modules.assessment.service import get_learner_context
    import asyncio

    result = asyncio.get_event_loop().run_until_complete(
        get_learner_context(
            session_id=_SESSION_ID,
            user_id=_USER_ID,
            supabase=_mock_supabase(
                session_row=session_no_ces,
                dna_row=None,
                quiz_rows=[],
                teachback_rows=[],
            ),
        )
    )

    assert result.prompt_text == ""


# ══════════════════════════════════════════════════════════════════════════════
# AC9 — no LLM calls (source scan)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_get_learner_context_makes_no_llm_calls():
    """AC9: get_learner_context function body contains no provider.complete or LLM calls."""
    source = _SERVICE_PATH.read_text(encoding="utf-8")
    fn_start = source.index("async def get_learner_context(")
    next_fn = source.find("\nasync def ", fn_start + 1)
    fn_body = source[fn_start:next_fn] if next_fn != -1 else source[fn_start:]

    assert "provider.complete" not in fn_body, (
        "get_learner_context must not call provider.complete — it is pure data aggregation (AC9)"
    )
    assert "llm_mini" not in fn_body, (
        "get_learner_context must not reference llm_mini — no LLM calls in this endpoint (AC9)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC11 — no banned fields / raw numeric student-visible scores
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_learner_context_schema_has_no_banned_fields():
    """AC11: LearnerContext schema has no transcript, duration_seconds, or iq/eq/sq fields."""
    from app.modules.assessment.schemas import LearnerContext, LearnerContextDNA, LearnerContextSession

    for model in (LearnerContext, LearnerContextDNA, LearnerContextSession):
        fields = model.model_fields
        assert "transcript" not in fields, f"{model.__name__} must not have 'transcript'"
        assert "duration_seconds" not in fields, f"{model.__name__} must not have 'duration_seconds'"
        for banned in ("iq_score", "eq_score", "sq_score"):
            assert banned not in fields, f"{model.__name__} must not have {banned!r}"


@pytest.mark.unit
def test_learner_context_dna_uses_no_raw_float_field():
    """AC11: LearnerContextDNA exposes only descriptive bands (dimension_labels: dict[str, str]), not raw floats."""
    from app.modules.assessment.schemas import LearnerContextDNA

    fields = LearnerContextDNA.model_fields
    # dimension_labels must exist (str values) — not a field called "dimensions" returning floats
    assert "dimension_labels" in fields, (
        "LearnerContextDNA must have 'dimension_labels' (descriptive bands), not raw floats"
    )
    assert "dimensions" not in fields, (
        "LearnerContextDNA must not expose 'dimensions' with raw float values to callers"
    )
