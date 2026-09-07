"""Story 4-28 (Phase 2 P2-1) — real backend for POST /assessment/session/{id}/questions.

Closes D149: `AskTutorPanel.tsx`/`submitTutorQuestion()` are real, shipped, and
100% mocked. `answer_tutor_question()` (service.py) is the real orchestration:
ownership check -> rate limit -> retrieval scope -> embed -> pgvector search ->
relevance gate -> LLM_TUTOR call -> session_events log.

All external dependencies (Supabase, Redis, embeddings provider, LLM provider)
are mocked — no real network/DB call anywhere in this file. `asyncio.to_thread`
is shimmed to run synchronously, matching test_quiz_endpoint.py's established
pattern for this module.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.core.redis import get_redis
from app.dependencies import get_current_user
from app.modules.assessment.router import router
from app.modules.assessment.schemas import TutorQuestionSubmission
from app.modules.assessment.service import answer_tutor_question

pytestmark = pytest.mark.unit

_SESSION_ROW = {"session_id": "sess-001", "user_id": "user-001", "lesson_id": "lesson-001"}
_LESSON_ROW = {"chapter_id": "chapter-001", "book_id": "book-001"}
_MATCHED_CHUNKS = [
    {"chunk_id": "chunk-1", "content": "Mitochondria produce ATP.", "similarity": 0.91},
    {"chunk_id": "chunk-2", "content": "ATP is the energy currency.", "similarity": 0.83},
]
_PAYLOAD = TutorQuestionSubmission(
    segment_id="seg-001", question_text="What is ATP?", audio_position_ms=12_000
)


@pytest.fixture(autouse=True)
def _mock_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace asyncio.to_thread with a synchronous shim (matches
    test_quiz_endpoint.py's established pattern for this module)."""

    async def _sync_shim(func, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return func(*args, **kwargs)

    monkeypatch.setattr("app.modules.assessment.service.asyncio.to_thread", _sync_shim)


@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_settings = MagicMock()
    mock_settings.tutor_qa_max_questions_per_session = 10
    mock_settings.tutor_qa_top_k = 5
    mock_settings.tutor_qa_relevance_threshold = 0.75
    mock_settings.tutor_qa_max_answer_tokens = 300
    mock_settings.llm_tutor = "gpt-4o"
    monkeypatch.setattr("app.modules.assessment.service.get_settings", lambda: mock_settings)


def _supabase_mock(
    *, session_row=_SESSION_ROW, lesson_row=_LESSON_ROW, matched_chunks=_MATCHED_CHUNKS
) -> MagicMock:
    """Route by table/rpc name rather than a positional side_effect list —
    robust across this function's several conditional branches (rate-limited
    and low-relevance paths call fewer tables than the happy path)."""
    mock = MagicMock()

    sessions_table = MagicMock()
    sess_chain = sessions_table.select.return_value.eq.return_value.maybe_single
    sess_chain.return_value.execute.return_value.data = session_row
    lessons_table = MagicMock()
    less_chain = lessons_table.select.return_value.eq.return_value.maybe_single
    less_chain.return_value.execute.return_value.data = lesson_row
    # ONE session_events mock, reused across every `.table("session_events")`
    # call — the real code and the test's own assertions both call it, and
    # must see the SAME instance's call history, not a fresh MagicMock each
    # time (which would silently show zero calls on the copy the test reads
    # back).
    events_table = MagicMock()
    events_table.insert.return_value.execute.return_value.data = [{"id": "evt-1"}]
    events_table.insert.return_value.execute.return_value.error = None

    def table_side_effect(name: str) -> MagicMock:
        if name == "sessions":
            return sessions_table
        if name == "lessons":
            return lessons_table
        if name == "session_events":
            return events_table
        raise AssertionError(f"unexpected table: {name!r}")

    mock.table.side_effect = table_side_effect
    mock.rpc.return_value.execute.return_value.data = matched_chunks
    return mock


def _redis_mock(*, question_number: int = 1) -> AsyncMock:
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=question_number)
    redis.expire = AsyncMock(return_value=True)
    return redis


def _patch_embeddings_and_llm(*, answer: str = "ATP is adenosine triphosphate."):
    """Returns a context manager patching both external AI providers."""
    embed_mock = AsyncMock(return_value=([[0.1, 0.2, 0.3]], 5))
    complete_mock = AsyncMock(return_value=(answer, "stop", 0.0021))
    return (
        patch.multiple(
            "app.providers.embeddings.openai.OpenAIEmbeddingsProvider",
            embed_texts=embed_mock,
        ),
        patch(
            "app.providers.llm.factory.get_llm_provider",
            return_value=MagicMock(complete_with_meta=complete_mock),
        ),
        embed_mock,
        complete_mock,
    )


# ── Session ownership (SEC-006 pattern, mirrors grade_quiz exactly) ────────────


async def test_missing_session_returns_404() -> None:
    supabase = _supabase_mock(session_row=None)
    redis = _redis_mock()

    with pytest.raises(Exception) as exc_info:  # noqa: PT011 — HTTPException, checked below
        await answer_tutor_question(
            session_id="sess-missing",
            payload=_PAYLOAD,
            user_id="user-001",
            supabase=supabase,
            redis=redis,
        )
    assert exc_info.value.status_code == 404  # type: ignore[attr-defined]


async def test_foreign_session_returns_404_not_403_no_enumeration_oracle() -> None:
    """SEC-006: a session belonging to a different user returns the SAME 404
    as a missing session — never 403 — so a caller can't distinguish 'wrong
    owner' from 'doesn't exist'."""
    supabase = _supabase_mock(session_row={**_SESSION_ROW, "user_id": "someone-else"})
    redis = _redis_mock()

    with pytest.raises(Exception) as exc_info:  # noqa: PT011
        await answer_tutor_question(
            session_id="sess-001",
            payload=_PAYLOAD,
            user_id="user-001",
            supabase=supabase,
            redis=redis,
        )
    assert exc_info.value.status_code == 404  # type: ignore[attr-defined]
    assert "access denied" in exc_info.value.detail.lower()  # type: ignore[attr-defined]


# ── Rate limit (AC2) ────────────────────────────────────────────────────────────


async def test_over_cap_declines_with_no_embedding_or_llm_call() -> None:
    supabase = _supabase_mock()
    redis = _redis_mock(question_number=11)  # cap is 10 (mocked settings)

    (embed_patch, llm_patch, embed_mock, complete_mock) = _patch_embeddings_and_llm()
    with embed_patch, llm_patch:
        result = await answer_tutor_question(
            session_id="sess-001",
            payload=_PAYLOAD,
            user_id="user-001",
            supabase=supabase,
            redis=redis,
        )

    assert result.declined is True
    assert result.answer is None
    embed_mock.assert_not_called()
    complete_mock.assert_not_called()


async def test_at_exactly_the_cap_still_answers_one_over_declines() -> None:
    """Boundary: question_number == cap answers; cap + 1 declines."""
    supabase = _supabase_mock()
    redis = _redis_mock(question_number=10)  # == cap

    (embed_patch, llm_patch, _embed_mock, complete_mock) = _patch_embeddings_and_llm()
    with embed_patch, llm_patch:
        result = await answer_tutor_question(
            session_id="sess-001",
            payload=_PAYLOAD,
            user_id="user-001",
            supabase=supabase,
            redis=redis,
        )

    assert result.declined is False
    complete_mock.assert_called_once()


async def test_rate_limit_check_uses_atomic_incr_return_value_not_a_separate_read() -> None:
    """Scale & Load Q6: the comparison must use redis.incr's own returned
    (atomically post-incremented) value — never a separate get() read that
    could be stale under concurrent requests."""
    supabase = _supabase_mock()
    redis = _redis_mock(question_number=3)

    (embed_patch, llm_patch, _embed_mock, _complete_mock) = _patch_embeddings_and_llm()
    with embed_patch, llm_patch:
        await answer_tutor_question(
            session_id="sess-001",
            payload=_PAYLOAD,
            user_id="user-001",
            supabase=supabase,
            redis=redis,
        )

    redis.incr.assert_awaited_once_with("session:sess-001:tutor_question_count")
    redis.get.assert_not_called()


async def test_first_question_sets_expire_ttl() -> None:
    supabase = _supabase_mock()
    redis = _redis_mock(question_number=1)

    (embed_patch, llm_patch, _e, _c) = _patch_embeddings_and_llm()
    with embed_patch, llm_patch:
        await answer_tutor_question(
            session_id="sess-001",
            payload=_PAYLOAD,
            user_id="user-001",
            supabase=supabase,
            redis=redis,
        )

    redis.expire.assert_awaited_once_with("session:sess-001:tutor_question_count", 86_400)


# ── Relevance gate (AC4) ─────────────────────────────────────────────────────────


async def test_no_matched_chunks_declines_with_no_llm_call() -> None:
    supabase = _supabase_mock(matched_chunks=[])
    redis = _redis_mock()

    (embed_patch, llm_patch, _e, complete_mock) = _patch_embeddings_and_llm()
    with embed_patch, llm_patch:
        result = await answer_tutor_question(
            session_id="sess-001",
            payload=_PAYLOAD,
            user_id="user-001",
            supabase=supabase,
            redis=redis,
        )

    assert result.declined is True
    complete_mock.assert_not_called()


async def test_below_relevance_threshold_declines_with_no_llm_call() -> None:
    low_relevance_chunks = [{"chunk_id": "c1", "content": "unrelated", "similarity": 0.40}]
    supabase = _supabase_mock(matched_chunks=low_relevance_chunks)
    redis = _redis_mock()

    (embed_patch, llm_patch, _e, complete_mock) = _patch_embeddings_and_llm()
    with embed_patch, llm_patch:
        result = await answer_tutor_question(
            session_id="sess-001",
            payload=_PAYLOAD,
            user_id="user-001",
            supabase=supabase,
            redis=redis,
        )

    assert result.declined is True
    assert result.answer is None
    complete_mock.assert_not_called()


async def test_at_exactly_the_relevance_threshold_answers() -> None:
    """Boundary: similarity == threshold answers (>= threshold), not <."""
    at_threshold_chunks = [{"chunk_id": "c1", "content": "content", "similarity": 0.75}]
    supabase = _supabase_mock(matched_chunks=at_threshold_chunks)
    redis = _redis_mock()

    (embed_patch, llm_patch, _e, complete_mock) = _patch_embeddings_and_llm()
    with embed_patch, llm_patch:
        result = await answer_tutor_question(
            session_id="sess-001",
            payload=_PAYLOAD,
            user_id="user-001",
            supabase=supabase,
            redis=redis,
        )

    assert result.declined is False
    complete_mock.assert_called_once()


# ── Happy path (AC3, AC5) ────────────────────────────────────────────────────────


async def test_happy_path_returns_real_answer() -> None:
    supabase = _supabase_mock()
    redis = _redis_mock()

    (embed_patch, llm_patch, embed_mock, complete_mock) = _patch_embeddings_and_llm(
        answer="ATP is the cell's energy currency."
    )
    with embed_patch, llm_patch:
        result = await answer_tutor_question(
            session_id="sess-001",
            payload=_PAYLOAD,
            user_id="user-001",
            supabase=supabase,
            redis=redis,
        )

    assert result.received is True
    assert result.declined is False
    assert result.answer == "ATP is the cell's energy currency."
    embed_mock.assert_awaited_once_with(["What is ATP?"])
    complete_mock.assert_called_once()


async def test_retrieval_scoped_to_chapter_id_not_corpus_wide() -> None:
    supabase = _supabase_mock()
    redis = _redis_mock()

    (embed_patch, llm_patch, _e, _c) = _patch_embeddings_and_llm()
    with embed_patch, llm_patch:
        await answer_tutor_question(
            session_id="sess-001",
            payload=_PAYLOAD,
            user_id="user-001",
            supabase=supabase,
            redis=redis,
        )

    supabase.rpc.assert_called_once()
    rpc_name, rpc_params = supabase.rpc.call_args.args
    assert rpc_name == "match_tutor_chunks"
    assert rpc_params["p_chapter_id"] == "chapter-001"
    assert rpc_params["p_match_count"] == 5


async def test_retrieval_falls_back_to_book_id_when_chapter_id_is_null() -> None:
    supabase = _supabase_mock(lesson_row={"chapter_id": None, "book_id": "book-001"})
    redis = _redis_mock()

    (embed_patch, llm_patch, _e, _c) = _patch_embeddings_and_llm()
    with embed_patch, llm_patch:
        await answer_tutor_question(
            session_id="sess-001",
            payload=_PAYLOAD,
            user_id="user-001",
            supabase=supabase,
            redis=redis,
        )

    _rpc_name, rpc_params = supabase.rpc.call_args.args
    assert rpc_params["p_chapter_id"] is None
    assert rpc_params["p_book_id"] == "book-001"


# ── session_events logging (AC6) ─────────────────────────────────────────────────


async def test_answered_question_logs_full_session_event_shape() -> None:
    supabase = _supabase_mock()
    redis = _redis_mock()

    (embed_patch, llm_patch, _e, _c) = _patch_embeddings_and_llm(answer="the answer")
    with embed_patch, llm_patch:
        await answer_tutor_question(
            session_id="sess-001",
            payload=_PAYLOAD,
            user_id="user-001",
            supabase=supabase,
            redis=redis,
        )

    events_table = supabase.table("session_events")
    inserted = events_table.insert.call_args.args[0]
    assert inserted["session_id"] == "sess-001"
    assert inserted["event_type"] == "tutor_question"
    payload = inserted["payload"]
    assert payload["segment_id"] == "seg-001"
    assert payload["question_text"] == "What is ATP?"
    assert payload["audio_position_ms"] == 12_000
    assert payload["answer"] == "the answer"
    assert payload["declined"] is False
    assert payload["retrieved_chunk_ids"] == ["chunk-1", "chunk-2"]
    assert payload["model"] == "gpt-4o"
    assert payload["finish_reason"] == "stop"


async def test_truncated_answer_finish_reason_is_logged_not_hidden() -> None:
    """Scale & Load Q2's exact concern: a max_tokens-truncated answer must be
    visible on the record, not indistinguishable from a complete one."""
    supabase = _supabase_mock()
    redis = _redis_mock()

    complete_mock = AsyncMock(return_value=("truncated answer...", "length", 0.003))
    with (
        patch.multiple(
            "app.providers.embeddings.openai.OpenAIEmbeddingsProvider",
            embed_texts=AsyncMock(return_value=([[0.1, 0.2, 0.3]], 5)),
        ),
        patch(
            "app.providers.llm.factory.get_llm_provider",
            return_value=MagicMock(complete_with_meta=complete_mock),
        ),
    ):
        await answer_tutor_question(
            session_id="sess-001",
            payload=_PAYLOAD,
            user_id="user-001",
            supabase=supabase,
            redis=redis,
        )

    inserted = supabase.table("session_events").insert.call_args.args[0]
    assert inserted["payload"]["finish_reason"] == "length"


async def test_declined_question_still_logs_an_event() -> None:
    """AC6: every question — answered or declined — writes exactly one row."""
    supabase = _supabase_mock(matched_chunks=[])
    redis = _redis_mock()

    (embed_patch, llm_patch, _e, _c) = _patch_embeddings_and_llm()
    with embed_patch, llm_patch:
        await answer_tutor_question(
            session_id="sess-001",
            payload=_PAYLOAD,
            user_id="user-001",
            supabase=supabase,
            redis=redis,
        )

    events_table = supabase.table("session_events")
    events_table.insert.assert_called_once()
    inserted = events_table.insert.call_args.args[0]
    assert inserted["payload"]["declined"] is True
    assert inserted["payload"]["answer"] is None


async def test_session_events_logging_failure_does_not_fail_the_request() -> None:
    """A logging failure must never turn a successfully-computed answer into
    a 500 for the student."""
    supabase = _supabase_mock()
    supabase.table("session_events").insert.side_effect = RuntimeError("db unavailable")
    # Rebuild the routing since the above call consumed one MagicMock instance
    # from the side_effect function's closure state — re-point it explicitly.
    original_side_effect = supabase.table.side_effect

    def _table_with_failing_events(name: str) -> MagicMock:
        if name == "session_events":
            m = MagicMock()
            m.insert.side_effect = RuntimeError("db unavailable")
            return m
        return original_side_effect(name)

    supabase.table.side_effect = _table_with_failing_events
    redis = _redis_mock()

    (embed_patch, llm_patch, _e, _c) = _patch_embeddings_and_llm(answer="a real answer")
    with embed_patch, llm_patch:
        result = await answer_tutor_question(
            session_id="sess-001",
            payload=_PAYLOAD,
            user_id="user-001",
            supabase=supabase,
            redis=redis,
        )

    assert result.answer == "a real answer"
    assert result.declined is False


# ── HTTP-layer wiring (router -> service, matches test_quiz_endpoint.py's
# own HTTP-layer coverage for this module) ──────────────────────────────────────


async def _fake_user() -> dict:
    return {"sub": "user-001", "email": "test@example.com"}


def test_router_wires_to_answer_tutor_question_with_correct_args() -> None:
    """HTTP-layer smoke test: the route exists at the expected path, DI
    (CurrentUser, Redis) resolves, and the real service function is called
    with the path/body/user/redis it should be — business logic itself is
    already covered service-level above, not re-tested here."""
    app = FastAPI()
    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[get_redis] = lambda: AsyncMock()
    app.include_router(router, prefix="/api/assessment")
    client = TestClient(app, raise_server_exceptions=False)

    from app.modules.assessment.schemas import TutorQuestionResult

    fake_result = TutorQuestionResult(received=True, answer="hi", declined=False)
    with patch(
        "app.modules.assessment.service.answer_tutor_question",
        new=AsyncMock(return_value=fake_result),
    ) as mock_answer:
        response = client.post(
            "/api/assessment/session/sess-001/questions",
            json={
                "segment_id": "seg-001",
                "question_text": "What is ATP?",
                "audio_position_ms": 1000,
            },
        )

    assert response.status_code == 200
    mock_answer.assert_called_once()
    _args, kwargs = mock_answer.call_args
    assert kwargs["session_id"] == "sess-001"
    assert kwargs["user_id"] == "user-001"
    assert kwargs["payload"].question_text == "What is ATP?"
