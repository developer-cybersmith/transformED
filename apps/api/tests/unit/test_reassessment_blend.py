"""Unit tests for reassessment behavior in process_onboarding() (Story 235 rewrite).

Story 235 removed the D137 EMA-blend-with-existing-scores logic for the 9
behavioral dimensions (that scoring path was removed from onboarding entirely —
see the story's Design section 1). The 5 new Penta-Intelligence scores are a
direct overwrite on every submission (initial or reassessment), not blended —
they're single-question measurements re-taken fresh each time, unlike the old
9 dimensions which each blended multiple questions across sessions.

What's still preserved from D137: session_count is never reset to 0 on a
reassessment resubmission — only on a genuine first-time onboarding.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.assessment.onboarding_questions import (
    ALL_NINE_DIMENSIONS,
    MCQ_OPTION_COUNTS,
    PENTA_BADGE_THRESHOLD,
    PENTA_DIMENSIONS,
    Q_SPEC,
)
from app.modules.assessment.schemas import OnboardingAnswer

# ── helpers ──────────────────────────────────────────────────────────────────

_VALID_USER_ID = "11111111-1111-1111-1111-111111111111"

_PENTA_TOP_INDEX = {"q16": 1, "q17": 1, "q18": 2, "q19": 2, "q20": 3}  # all -> 100.0
_PENTA_LOW_INDEX = {"q16": 0, "q17": 0, "q18": 0, "q19": 0, "q20": 0}  # all below threshold


def _all_responses(penta_indices: dict[str, int]) -> list[OnboardingAnswer]:
    """30 onboarding answers, with Q16-Q20 set via penta_indices."""
    answers: list[OnboardingAnswer] = []
    for qid, fmt in Q_SPEC.items():
        if fmt == "mcq":
            index = penta_indices.get(qid, min(1, MCQ_OPTION_COUNTS[qid] - 1))
            answers.append(
                OnboardingAnswer(
                    question_id=qid,
                    format="mcq",
                    selected_index=index,
                    response_text=f"Option {index}",
                    response_time_ms=1000,
                )
            )
        elif fmt == "one_liner":
            answers.append(
                OnboardingAnswer(
                    question_id=qid,
                    format="one_liner",
                    response_text=f"Answer for {qid}.",
                    response_time_ms=1000,
                )
            )
        else:
            answers.append(
                OnboardingAnswer(
                    question_id=qid, format="true_false", response_bool=True, response_time_ms=1000
                )
            )
    return answers


def _make_supabase_mock(
    *,
    existing_dna_row: dict[str, Any] | None,
    insert_ok: bool = True,
    upsert_ok: bool = True,
) -> MagicMock:
    """Build a mock Supabase client for process_onboarding tests.

    Uses side_effect on table() to return table-specific mocks so that
    learner_dna SELECT, onboarding_answers_v2 UPSERT (D173: was INSERT — see
    service.py Step 5), and learner_dna UPSERT can be independently configured.
    """
    mock = MagicMock()

    dna_table = MagicMock()
    maybe_single_resp = MagicMock()
    maybe_single_resp.error = None
    maybe_single_resp.data = existing_dna_row
    (
        dna_table.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value
    ) = maybe_single_resp
    upsert_resp = MagicMock()
    upsert_resp.error = None if upsert_ok else MagicMock()
    dna_table.upsert.return_value.execute.return_value = upsert_resp

    ob_table = MagicMock()
    insert_resp = MagicMock()
    insert_resp.error = None if insert_ok else MagicMock()
    ob_table.upsert.return_value.execute.return_value = insert_resp

    users_table = MagicMock()
    consent_resp = MagicMock()
    consent_resp.error = None
    consent_resp.data = None
    _chain = users_table.select.return_value.eq.return_value.maybe_single.return_value
    _chain.execute.return_value = consent_resp

    def _table_side_effect(name: str) -> MagicMock:
        if name == "learner_dna":
            return dna_table
        if name == "onboarding_answers_v2":
            return ob_table
        return users_table

    mock.table.side_effect = _table_side_effect
    return mock


class _FakeOnboardingAnswersTable:
    """In-memory fake that actually enforces UNIQUE(user_id, question_id) semantics,
    unlike a MagicMock configured to unconditionally succeed. Used by
    test_reassessment_resubmission_succeeds_against_the_actual_unique_constraint
    below to prove the D173 fix (upsert, not insert) works against real
    conflict behavior — a plain .insert() call here on a colliding key produces
    the same "duplicate key value violates unique constraint" error Postgres
    would, so a regression back to .insert() fails this test for a real reason,
    not because a mock was told what to return.
    """

    def __init__(self, store: dict[tuple[str, str], dict[str, Any]]) -> None:
        self._store = store
        self._op: str | None = None
        self._rows: list[dict[str, Any]] | None = None

    def insert(self, rows: list[dict[str, Any]]) -> _FakeOnboardingAnswersTable:
        self._op = "insert"
        self._rows = rows
        return self

    def upsert(
        self, rows: list[dict[str, Any]], on_conflict: str | None = None
    ) -> _FakeOnboardingAnswersTable:
        self._op = "upsert"
        self._rows = rows
        return self

    def execute(self) -> MagicMock:
        resp = MagicMock()
        rows = self._rows or []
        if self._op == "insert":
            for row in rows:
                key = (row["user_id"], row["question_id"])
                if key in self._store:
                    err = MagicMock()
                    err.__str__ = lambda s: "duplicate key value violates unique constraint"
                    resp.error = err
                    resp.data = None
                    return resp
        for row in rows:
            self._store[(row["user_id"], row["question_id"])] = row
        resp.error = None
        resp.data = rows
        return resp


def _existing_row(*, session_count: int, penta_scores: dict[str, float] | None = None) -> dict[str, Any]:
    """A learner_dna DB row — session_count + optional prior penta scores.

    The 9 behavioral dimension columns are deliberately absent (they're never
    read by _fetch_existing_dna anymore — only session_count is).
    """
    row: dict[str, Any] = {"user_id": _VALID_USER_ID, "session_count": session_count}
    if penta_scores:
        row.update(penta_scores)
    return row


# ── AC1 — first-time path writes raw penta scores, session_count=0 ───────────


@pytest.mark.asyncio
async def test_first_time_writes_raw_penta_scores_and_zero_session_count() -> None:
    """AC1: no existing row -> penta scores written raw, session_count=0."""
    supabase = _make_supabase_mock(existing_dna_row=None)
    responses = _all_responses(_PENTA_TOP_INDEX)

    with patch(
        "app.modules.assessment.service.generate_onboarding_profile",
        new=AsyncMock(return_value="Profile text. HIE disclaimer."),
    ):
        from app.modules.assessment.service import process_onboarding

        result = await process_onboarding(
            responses=responses, user_id=_VALID_USER_ID, supabase=supabase
        )

    assert result.session_count == 0

    dna_table = supabase.table("learner_dna")
    upsert_calls = dna_table.upsert.call_args_list
    assert upsert_calls, "upsert was never called"
    payload = upsert_calls[0].args[0]
    assert payload["session_count"] == 0
    for dim in PENTA_DIMENSIONS:
        assert abs(payload[dim] - 100.0) < 0.01, f"{dim}: expected 100.0, got {payload[dim]}"
    for dim in ALL_NINE_DIMENSIONS:
        assert dim not in payload


# ── AC2 — reassessment OVERWRITES penta scores, does not blend ───────────────


@pytest.mark.asyncio
async def test_reassessment_overwrites_penta_scores_no_blending() -> None:
    """AC2 (revised from D137): a reassessment resubmission's fresh Penta answers
    completely replace the prior scores — no EMA blend. Prior penta_iq=20 (low),
    new submission answers Q16 at the top-scoring index -> upserted value is
    exactly 100.0, not some blend of 20 and 100."""
    existing = _existing_row(session_count=5, penta_scores={"penta_iq": 20.0})
    supabase = _make_supabase_mock(existing_dna_row=existing)
    responses = _all_responses(_PENTA_TOP_INDEX)

    with patch(
        "app.modules.assessment.service.generate_onboarding_profile",
        new=AsyncMock(return_value="Profile. HIE."),
    ):
        from app.modules.assessment.service import process_onboarding

        await process_onboarding(responses=responses, user_id=_VALID_USER_ID, supabase=supabase)

    dna_table = supabase.table("learner_dna")
    payload = dna_table.upsert.call_args_list[0].args[0]
    assert payload["penta_iq"] == pytest.approx(100.0), (
        f"Expected a fresh overwrite to 100.0, not a blend with the prior 20.0; "
        f"got {payload['penta_iq']}"
    )


# ── AC3 — session_count preserved on reassessment ─────────────────────────────


@pytest.mark.asyncio
async def test_reassessment_preserves_existing_session_count() -> None:
    """AC3: existing session_count is never reset to 0 on reassessment."""
    existing = _existing_row(session_count=17)
    supabase = _make_supabase_mock(existing_dna_row=existing)
    responses = _all_responses(_PENTA_TOP_INDEX)

    with patch(
        "app.modules.assessment.service.generate_onboarding_profile",
        new=AsyncMock(return_value="Profile. HIE."),
    ):
        from app.modules.assessment.service import process_onboarding

        result = await process_onboarding(
            responses=responses, user_id=_VALID_USER_ID, supabase=supabase
        )

    assert result.session_count == 17

    dna_table = supabase.table("learner_dna")
    payload = dna_table.upsert.call_args_list[0].args[0]
    assert payload["session_count"] == 17


# ── AC7 — DB error on existing row SELECT falls back to first-time write ─────


@pytest.mark.asyncio
async def test_existing_row_fetch_error_falls_back_to_first_time_write(caplog: Any) -> None:
    """AC7: if _fetch_existing_dna raises, fallback to session_count=0 + log WARNING."""
    supabase = _make_supabase_mock(existing_dna_row=None)
    dna_table = supabase.table("learner_dna")
    dna_table.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = (
        Exception("DB connection lost")
    )
    responses = _all_responses(_PENTA_TOP_INDEX)

    import logging

    with (
        patch(
            "app.modules.assessment.service.generate_onboarding_profile",
            new=AsyncMock(return_value="Profile. HIE."),
        ),
        caplog.at_level(logging.WARNING, logger="app.modules.assessment.service"),
    ):
        from app.modules.assessment.service import process_onboarding

        result = await process_onboarding(
            responses=responses, user_id=_VALID_USER_ID, supabase=supabase
        )

    assert result.session_count == 0
    assert any(
        "onboarding" in r.message.lower() or "existing" in r.message.lower() for r in caplog.records
    )


# ── AC9 — onboarding_answers_v2 rows still written on reassessment ───────────


@pytest.mark.asyncio
async def test_onboarding_answers_written_on_reassessment() -> None:
    """AC9: UPSERT to onboarding_answers_v2 runs on both first-time and reassessment
    (D173: a plain INSERT here is exactly what dead-ends a legitimate reassessment
    resubmission against the table's own UNIQUE(user_id, question_id) constraint —
    see test_reassessment_resubmission_succeeds_against_the_actual_unique_constraint
    below for a test that enforces that constraint itself rather than mocking around it)."""
    existing = _existing_row(session_count=8)
    supabase = _make_supabase_mock(existing_dna_row=existing)
    responses = _all_responses(_PENTA_LOW_INDEX)

    with patch(
        "app.modules.assessment.service.generate_onboarding_profile",
        new=AsyncMock(return_value="Profile. HIE."),
    ):
        from app.modules.assessment.service import process_onboarding

        await process_onboarding(responses=responses, user_id=_VALID_USER_ID, supabase=supabase)

    ob_table = supabase.table("onboarding_answers_v2")
    upsert_calls = ob_table.upsert.call_args_list
    assert upsert_calls, "onboarding_answers_v2 UPSERT was never called on reassessment"
    upserted_rows = upsert_calls[0].args[0]
    assert len(upserted_rows) == 30
    assert upsert_calls[0].kwargs.get("on_conflict") == "user_id,question_id"


# ── AC4 — badge_labels driven by the fresh submission, not stale history ─────


@pytest.mark.asyncio
async def test_reassessment_badge_labels_reflect_fresh_submission_only() -> None:
    """AC4: badge_labels come purely from THIS submission's Penta scores — a
    student who previously earned a badge but answers low this time gets no
    badge (no blending keeps a stale badge alive)."""
    existing = _existing_row(session_count=5, penta_scores={"penta_iq": 95.0})  # was high
    supabase = _make_supabase_mock(existing_dna_row=existing)
    responses = _all_responses(_PENTA_LOW_INDEX)  # this time, all low

    with patch(
        "app.modules.assessment.service.generate_onboarding_profile",
        new=AsyncMock(return_value="Profile. HIE."),
    ):
        from app.modules.assessment.service import process_onboarding

        result = await process_onboarding(
            responses=responses, user_id=_VALID_USER_ID, supabase=supabase
        )

    assert result.badge_labels == [], (
        f"Expected no badges (fresh submission scored below "
        f"{PENTA_BADGE_THRESHOLD}), got {result.badge_labels}"
    )


# ── D173 regression guard — enforces the real constraint, doesn't mock around it ──


@pytest.mark.asyncio
async def test_reassessment_resubmission_succeeds_against_the_actual_unique_constraint() -> None:
    """D173: a genuine reassessment resubmission must not dead-end on
    onboarding_answers_v2's own UNIQUE(user_id, question_id) constraint. Every
    other test in this file mocks the table's write to unconditionally succeed,
    which would pass identically whether process_onboarding used insert or
    upsert — this test uses _FakeOnboardingAnswersTable, which actually raises
    a duplicate-key error on a colliding .insert() the way Postgres would, so it
    fails for a real reason if Step 5 ever regresses from upsert back to insert."""
    store: dict[tuple[str, str], dict[str, Any]] = {}

    def _build_supabase(existing_dna_row: dict[str, Any] | None) -> MagicMock:
        mock = MagicMock()

        dna_table = MagicMock()
        maybe_single_resp = MagicMock()
        maybe_single_resp.error = None
        maybe_single_resp.data = existing_dna_row
        (
            dna_table.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value
        ) = maybe_single_resp
        upsert_resp = MagicMock()
        upsert_resp.error = None
        dna_table.upsert.return_value.execute.return_value = upsert_resp

        ob_table = _FakeOnboardingAnswersTable(store)

        users_table = MagicMock()
        consent_resp = MagicMock()
        consent_resp.error = None
        consent_resp.data = None
        _chain = users_table.select.return_value.eq.return_value.maybe_single.return_value
        _chain.execute.return_value = consent_resp

        def _table_side_effect(name: str) -> MagicMock:
            if name == "learner_dna":
                return dna_table
            if name == "onboarding_answers_v2":
                return ob_table
            return users_table

        mock.table.side_effect = _table_side_effect
        return mock

    with patch(
        "app.modules.assessment.service.generate_onboarding_profile",
        new=AsyncMock(return_value="Profile. HIE."),
    ):
        from app.modules.assessment.service import process_onboarding

        # First-time onboarding: 30 rows land in the fake store, keyed by
        # (user_id, question_id).
        first = await process_onboarding(
            responses=_all_responses(_PENTA_TOP_INDEX),
            user_id=_VALID_USER_ID,
            supabase=_build_supabase(existing_dna_row=None),
        )
        assert first.session_count == 0
        assert len(store) == 30

        # Reassessment resubmission: identical 30 (user_id, question_id) keys.
        # Pre-D173-fix (a plain .insert()), this raises the same duplicate-key
        # error Postgres's real UNIQUE constraint would, which process_onboarding
        # would surface as an HTTPException — the resubmission would never reach
        # this assertion. Post-fix (.upsert()), it must succeed and overwrite.
        second = await process_onboarding(
            responses=_all_responses(_PENTA_LOW_INDEX),
            user_id=_VALID_USER_ID,
            supabase=_build_supabase(existing_dna_row=_existing_row(session_count=5)),
        )

    assert second.session_count == 5
    assert len(store) == 30, "reassessment must overwrite the 30 existing rows, not duplicate them"
    overwritten_q16 = store[(_VALID_USER_ID, "q16")]
    assert overwritten_q16["selected_index"] == _PENTA_LOW_INDEX["q16"]
