"""Guards for D97 and D98 (renumbered from D79/D80) — assessment schema validation fixes.

D97 (was D79): SessionCreate.lesson_id now has min_length=1 — empty string returns 422
     instead of reaching the Supabase lessons table and producing a 500.

D98 (was D80): TeachbackSubmission.response_text now has a @field_validator that strips
     and rejects whitespace-only content — "   " returns 422 instead of
     silently triggering a real GPT-4o-mini call.

These tests pin the CORRECT behaviour — if either schema fix is reverted,
these tests fail CI immediately.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.dependencies import get_current_user, get_settings
from app.modules.assessment.router import router


async def _fake_user() -> dict:
    return {"sub": "user-001", "email": "test@example.com"}


def _approved_settings() -> MagicMock:
    s = MagicMock()
    s.approved_emails = ["test@example.com"]
    return s


_app = FastAPI()
_app.dependency_overrides[get_current_user] = _fake_user
_app.dependency_overrides[get_settings] = _approved_settings
_app.include_router(router, prefix="/api/assessment")
_client = TestClient(_app, raise_server_exceptions=False)

_VALID_TEACHBACK_PAYLOAD = {
    "session_id": "sess-001",
    "lesson_id": "lesson-001",
    "segment_id": "seg-001",
    "response_text": "The mitochondria is the powerhouse of the cell.",
}


# ── D97 (was D79) guards ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_sessions_empty_lesson_id_returns_422() -> None:
    """D97 (was D79): lesson_id='' must return 422, not reach the DB and produce 500.

    Before the fix: empty string satisfied `str` type, passed Pydantic, reached
    Supabase with a UUID-type column, raised a cast error → HTTP 500.
    After the fix: min_length=1 rejects it at the Pydantic layer → HTTP 422.
    """
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/sessions", json={"lesson_id": ""})
    assert resp.status_code == 422, (
        f"D97 (was D79): empty lesson_id must return 422 (min_length=1 enforced at schema layer). "
        f"Got {resp.status_code}: {resp.text}"
    )


@pytest.mark.unit
def test_sessions_null_lesson_id_returns_422() -> None:
    """D97 (was D79): lesson_id=null must return 422 (Pydantic rejects None for str field)."""
    with patch("app.core.db.get_supabase", return_value=MagicMock()):
        resp = _client.post("/api/assessment/sessions", json={"lesson_id": None})
    assert resp.status_code == 422, (
        f"D97 (was D79): null lesson_id must return 422. Got {resp.status_code}: {resp.text}"
    )


# ── D98 (was D80) guards ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_teachback_whitespace_only_response_text_returns_422() -> None:
    """D98 (was D80): response_text='   ' (whitespace only) must return 422, not trigger LLM.

    Before the fix: min_length=1 counted characters — a single space satisfied it,
    the request reached grade_teachback, and a real GPT-4o-mini call was made.
    After the fix: @field_validator strips and rejects blank content → HTTP 422.
    """
    for whitespace_variant in ["   ", " ", "\t", "\n", "  \t  \n  "]:
        payload = {**_VALID_TEACHBACK_PAYLOAD, "response_text": whitespace_variant}
        with patch("app.core.db.get_supabase", return_value=MagicMock()):
            resp = _client.post("/api/assessment/teachback", json=payload)
        assert resp.status_code == 422, (
            f"D98 (was D80): whitespace-only response_text {whitespace_variant!r} must return 422. "
            f"Got {resp.status_code}: {resp.text}"
        )


@pytest.mark.unit
def test_teachback_single_char_response_text_accepted() -> None:
    """D98 (was D80): response_text='A' (single non-whitespace char) must still be accepted.

    The validator must reject only whitespace — any real content, even 1 character,
    must pass. This test guards against over-eager validation.
    """
    from unittest.mock import AsyncMock

    from app.modules.assessment.schemas import TeachbackResult

    fake_result = TeachbackResult(
        session_id="sess-001",
        rubric_scores={"accuracy": "Good", "completeness": "Fair", "clarity": "Fair"},
        overall_score=50.0,
        ces_contribution=12.5,
        feedback="Brief but present.",
    )

    with patch(
        "app.modules.assessment.service.grade_teachback",
        new=AsyncMock(return_value=fake_result),
    ):
        payload = {**_VALID_TEACHBACK_PAYLOAD, "response_text": "A"}
        with patch("app.core.db.get_supabase", return_value=MagicMock()):
            resp = _client.post("/api/assessment/teachback", json=payload)

    assert resp.status_code == 200, (
        f"D98 (was D80): single non-whitespace char must be accepted "
        f"(validator only rejects blank). Got {resp.status_code}: {resp.text}"
    )
