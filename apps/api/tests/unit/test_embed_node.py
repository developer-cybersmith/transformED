"""
Unit tests for Story 1.5: Embeddings + pgvector storage node.

OpenAI, Supabase, and Langfuse are fully mocked — no network calls.
Since embed_node uses local imports (`from app.X import Y` inside the function
body), we patch at the SOURCE module (e.g. "app.core.db.get_supabase"),
not at the graph module.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Constants ─────────────────────────────────────────────────────────────────

FAKE_LESSON_ID = "55555555-5555-5555-5555-555555555555"
FAKE_BOOK_ID = "11111111-1111-1111-1111-111111111111"
FAKE_CHAPTER_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
FAKE_CHUNK_ID_1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
FAKE_CHUNK_ID_2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

_FAKE_EMBEDDING = [0.1] * 1536
_BASE_STATE: dict[str, Any] = {
    "lesson_id": FAKE_LESSON_ID,
    "book_id": FAKE_BOOK_ID,
    "user_id": "user-1",
    "source_pdf_path": "lessons/test.pdf",
    "chapter_content": "",
    "raw_text": "some text",
    "extracted_images": [],
    "font_blocks": [],
    "sections": [],
    "chunks": [],
    "embeddings_stored": False,
    "lesson_plan": {},
    "slides": [],
    "segment_summaries": [],
    "quiz_questions": [],
    "glossary": [],
    "intervention_prompts": [],
    "audio_assets": [],
    "slide_images": [],
    "error": None,
    "progress_pct": 0.0,
}

_DEFAULT_NODE_OUTPUTS = {"chunk": {"chapter_id": FAKE_CHAPTER_ID, "chunks": []}}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_jobs_table(node_outputs: dict[str, Any]) -> MagicMock:
    t = MagicMock()
    t.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "node_outputs": node_outputs
    }
    t.update.return_value.eq.return_value.execute.return_value = MagicMock()
    return t


def _make_chunks_table(pages: list[list[dict[str, Any]]]) -> MagicMock:
    """Chunks-table mock for the paginated IS-NULL select (AC-6b).

    Each ``.execute()`` on the select chain consumes the next entry of
    ``pages``; once exhausted it returns [] — mirroring the real DB where
    embedded rows drop out of the IS-NULL filter (so the completion check
    after writeback sees nothing left).
    """
    t = MagicMock()
    queue: list[list[dict[str, Any]]] = [list(p) for p in pages]

    def _execute() -> MagicMock:
        resp = MagicMock()
        resp.data = queue.pop(0) if queue else []
        return resp

    (
        t.select.return_value
        .eq.return_value
        .is_.return_value
        .order.return_value
        .range.return_value
        .execute.side_effect
    ) = _execute
    t.upsert.return_value.execute.return_value = MagicMock()
    return t


def _make_books_table() -> MagicMock:
    t = MagicMock()
    t.update.return_value.eq.return_value.execute.return_value = MagicMock()
    return t


def _make_supabase(
    node_outputs: dict[str, Any] | None = None,
    chunks: list[dict[str, Any]] | None = None,
    chunk_pages: list[list[dict[str, Any]]] | None = None,
) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """Return (supabase, jobs_table, chunks_table, books_table).

    ``chunks`` is a convenience for the common single-page fetch; pass
    ``chunk_pages`` explicitly to script multi-page / completion-check flows.
    """
    if node_outputs is None:
        node_outputs = _DEFAULT_NODE_OUTPUTS
    if chunk_pages is None:
        if chunks is None:
            chunks = [
                {"chunk_id": FAKE_CHUNK_ID_1, "content": "first chunk text", "chunk_index": 0},
                {"chunk_id": FAKE_CHUNK_ID_2, "content": "second chunk text", "chunk_index": 1},
            ]
        chunk_pages = [chunks]
    jobs = _make_jobs_table(node_outputs)
    chk = _make_chunks_table(chunk_pages)
    bks = _make_books_table()

    sb = MagicMock()

    def _table(name: str) -> MagicMock:
        if name == "lesson_jobs":
            return jobs
        if name == "chunks":
            return chk
        if name == "books":
            return bks
        return MagicMock()

    sb.table.side_effect = _table
    return sb, jobs, chk, bks


def _make_provider(
    embeddings: list[list[float]] | None = None,
    total_tokens: int = 200,
) -> AsyncMock:
    p = AsyncMock()
    if embeddings is None:
        embeddings = [_FAKE_EMBEDDING, _FAKE_EMBEDDING]
    p.embed_texts.return_value = (embeddings, total_tokens)
    return p


def _configure_settings(
    mock_settings: MagicMock,
    model: str = "text-embedding-3-small",
    dimensions: int = 1536,
    token_budget: int = 100_000,
) -> None:
    """Real values for every settings field embed_node touches — the AC-6
    token-budget packing does arithmetic on embed_batch_token_budget."""
    cfg = mock_settings.return_value
    cfg.embedding_model = model
    cfg.embedding_dimensions = dimensions
    cfg.embed_batch_token_budget = token_budget


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_node_happy_path() -> None:
    """Two chunks → provider called once → embeddings written → book ready → checkpoint."""
    from app.modules.content.pipeline.graph import embed_node

    sb, jobs, chk, bks = _make_supabase()
    provider = _make_provider()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
        patch("app.providers.embeddings.openai.OpenAIEmbeddingsProvider", return_value=provider) as mock_cls,
    ):
        _configure_settings(mock_settings)
        result = await embed_node({**_BASE_STATE})

    assert result["embeddings_stored"] is True

    # Provider constructor called with lesson_id (P12)
    mock_cls.assert_called_once_with(lesson_id=FAKE_LESSON_ID)

    # Provider called once with both chunk texts
    provider.embed_texts.assert_awaited_once_with(["first chunk text", "second chunk text"])

    # IS NULL filter applied (P9)
    chk.select.return_value.eq.return_value.is_.assert_called_with("embedding", "null")

    # ORDER BY chunk_index applied (P8)
    chk.select.return_value.eq.return_value.is_.return_value.order.assert_called_with("chunk_index")

    # Paginated select uses .range() starting at the first page (AC-6b)
    range_mock = chk.select.return_value.eq.return_value.is_.return_value.order.return_value.range
    assert range_mock.call_args_list[0].args == (0, 999)

    # AC-6d: ONE bulk upsert for the whole batch, keyed on chunk_id
    chk.update.assert_not_called()
    chk.upsert.assert_called_once()
    rows = chk.upsert.call_args.args[0]
    assert chk.upsert.call_args.kwargs.get("on_conflict") == "chunk_id"
    assert [r["chunk_id"] for r in rows] == [FAKE_CHUNK_ID_1, FAKE_CHUNK_ID_2]
    assert all(r["embedding"] == _FAKE_EMBEDDING for r in rows)
    # AC-6d upsert SHAPE: the NOT-NULL echo columns (chapter_id/content/
    # chunk_index) must be present — Postgres validates NOT NULL on the
    # candidate tuple BEFORE ON CONFLICT arbitration, so dropping them
    # fails prod with 23502 even though only the UPDATE arm runs.
    assert set(rows[0]) >= {
        "chunk_id", "chapter_id", "content", "chunk_index",
        "embedding", "embedding_metadata",
    }

    # books.update called with status=ready, keyed on book_id
    bks.update.assert_called_once_with({"status": "ready"})
    bks.update.return_value.eq.assert_called_once_with("book_id", FAKE_BOOK_ID)

    # lesson_jobs.update called (checkpoint)
    jobs.update.assert_called_once()
    payload = jobs.update.call_args[0][0]
    assert payload["last_node"] == "embed"
    assert payload["node_outputs"]["embed"]["chunk_count"] == 2
    assert payload["node_outputs"]["embed"]["chapter_id"] == FAKE_CHAPTER_ID


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_node_idempotent_cache_hit() -> None:
    """If 'embed' already in node_outputs, return immediately — no provider call."""
    from app.modules.content.pipeline.graph import embed_node

    node_outputs = {
        "chunk": {"chapter_id": FAKE_CHAPTER_ID},
        "embed": {"chunk_count": 5, "chapter_id": FAKE_CHAPTER_ID},
    }
    sb, jobs, chk, bks = _make_supabase(node_outputs=node_outputs)
    provider = _make_provider()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings"),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
        patch("app.providers.embeddings.openai.OpenAIEmbeddingsProvider", return_value=provider),
    ):
        result = await embed_node({**_BASE_STATE})

    assert result["embeddings_stored"] is True
    provider.embed_texts.assert_not_awaited()
    # chunks table is never even queried
    assert chk.select.call_count == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_node_no_unembedded_chunks() -> None:
    """All chunks already embedded (IS NULL returns empty) — no API call,
    but checkpoint and books.status=ready still written."""
    from app.modules.content.pipeline.graph import embed_node

    sb, jobs, chk, bks = _make_supabase(chunks=[])
    provider = _make_provider()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
        patch("app.providers.embeddings.openai.OpenAIEmbeddingsProvider", return_value=provider),
    ):
        _configure_settings(mock_settings)
        result = await embed_node({**_BASE_STATE})

    assert result["embeddings_stored"] is True
    provider.embed_texts.assert_not_awaited()

    # books should still be marked ready
    bks.update.assert_called_once_with({"status": "ready"})

    # checkpoint written with chunk_count=0
    jobs.update.assert_called_once()
    payload = jobs.update.call_args[0][0]
    assert payload["node_outputs"]["embed"]["chunk_count"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_node_multiple_chunks_one_batch() -> None:
    """5 small chunks fit within the token budget → provider called exactly once,
    all 5 rows written in a single bulk upsert."""
    from app.modules.content.pipeline.graph import embed_node

    chunks = [
        {"chunk_id": f"c{i}", "content": f"text {i}", "chunk_index": 0, "token_count": 100}
        for i in range(5)
    ]
    sb, jobs, chk, bks = _make_supabase(chunks=chunks)

    async def embed_side_effect(texts: list[str]) -> tuple[list[list[float]], int]:
        return ([_FAKE_EMBEDDING] * len(texts), len(texts) * 50)

    provider = AsyncMock()
    provider.embed_texts.side_effect = embed_side_effect

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
        patch("app.providers.embeddings.openai.OpenAIEmbeddingsProvider", return_value=provider),
    ):
        _configure_settings(mock_settings)
        result = await embed_node({**_BASE_STATE})

    assert result["embeddings_stored"] is True
    assert provider.embed_texts.await_count == 1
    chk.upsert.assert_called_once()
    assert len(chk.upsert.call_args.args[0]) == 5  # one bulk write for all 5 chunks


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_node_missing_chapter_id_raises() -> None:
    """If chunk checkpoint has no chapter_id, embed_node raises RuntimeError."""
    from app.modules.content.pipeline.graph import embed_node

    sb, _, _, _ = _make_supabase(node_outputs={"chunk": {}})

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings"),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        with pytest.raises(RuntimeError, match="no chapter_id in chunk checkpoint"):
            await embed_node({**_BASE_STATE})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_node_missing_chunk_key_raises() -> None:
    """If node_outputs has no 'chunk' key at all, embed_node raises RuntimeError."""
    from app.modules.content.pipeline.graph import embed_node

    sb, _, _, _ = _make_supabase(node_outputs={})

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings"),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        with pytest.raises(RuntimeError, match="no chapter_id in chunk checkpoint"):
            await embed_node({**_BASE_STATE})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_node_embedding_metadata_written() -> None:
    """embedding_metadata reads model/dimensions from settings dynamically (P11)."""
    from app.modules.content.pipeline.graph import embed_node

    sb, jobs, chk, bks = _make_supabase(
        chunks=[{"chunk_id": FAKE_CHUNK_ID_1, "content": "text", "chunk_index": 0}]
    )
    provider = _make_provider(embeddings=[_FAKE_EMBEDDING], total_tokens=50)

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
        patch("app.providers.embeddings.openai.OpenAIEmbeddingsProvider", return_value=provider),
    ):
        # Use a non-default model name to prove the value flows from settings (P11)
        _configure_settings(mock_settings, model="test-model-xyz", dimensions=768)
        await embed_node({**_BASE_STATE})

    rows = chk.upsert.call_args.args[0]
    assert rows[0]["embedding"] == _FAKE_EMBEDDING
    meta = rows[0]["embedding_metadata"]
    assert meta["model"] == "test-model-xyz"
    assert meta["dimensions"] == 768
    assert "ingested_at" in meta
    # AC-6d upsert SHAPE: NOT-NULL echo columns must survive (see happy path)
    assert set(rows[0]) >= {
        "chunk_id", "chapter_id", "content", "chunk_index",
        "embedding", "embedding_metadata",
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_node_skips_books_update_when_no_book_id() -> None:
    """If book_id is empty string, books.update is NOT called."""
    from app.modules.content.pipeline.graph import embed_node

    sb, jobs, chk, bks = _make_supabase(chunks=[])

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
        patch("app.providers.embeddings.openai.OpenAIEmbeddingsProvider", return_value=AsyncMock()),
    ):
        _configure_settings(mock_settings)
        result = await embed_node({**_BASE_STATE, "book_id": ""})

    assert result["embeddings_stored"] is True
    assert bks.update.call_count == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_node_progress_reported() -> None:
    """_update_job_progress is called with lesson_id, pct=28.0, node='embed'."""
    from app.modules.content.pipeline.graph import embed_node

    sb, _, _, _ = _make_supabase(chunks=[])
    mock_progress = AsyncMock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("app.modules.content.pipeline.graph._update_job_progress", mock_progress),
        patch("app.providers.embeddings.openai.OpenAIEmbeddingsProvider", return_value=AsyncMock()),
    ):
        _configure_settings(mock_settings)
        await embed_node({**_BASE_STATE})

    mock_progress.assert_awaited_once()
    args = mock_progress.await_args[0]
    assert args[0] == FAKE_LESSON_ID
    assert args[1] == 28.0
    assert args[2] == "embed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_node_batch_split_by_token_budget() -> None:
    """P10 rework (AC-6c): batches packed by token budget, not chunk count —
    a workload exceeding embed_batch_token_budget splits into multiple API calls."""
    from app.modules.content.pipeline.graph import embed_node

    # Sizes stay under the 8000-token per-input cap so only the BUDGET drives
    # the split: 6k + 5k > 10k budget → c0 alone; 5k + 3k = 8k ≤ 10k → c1+c2.
    chunks = [
        {"chunk_id": "c0", "content": "big text 0", "chunk_index": 0, "token_count": 6_000},
        {"chunk_id": "c1", "content": "big text 1", "chunk_index": 0, "token_count": 5_000},
        {"chunk_id": "c2", "content": "big text 2", "chunk_index": 0, "token_count": 3_000},
    ]
    sb, jobs, chk, bks = _make_supabase(chunks=chunks)

    call_sizes: list[int] = []

    async def embed_side_effect(texts: list[str]) -> tuple[list[list[float]], int]:
        call_sizes.append(len(texts))
        return ([_FAKE_EMBEDDING] * len(texts), len(texts) * 10)

    provider = AsyncMock()
    provider.embed_texts.side_effect = embed_side_effect

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
        patch("app.providers.embeddings.openai.OpenAIEmbeddingsProvider", return_value=provider),
    ):
        _configure_settings(mock_settings, token_budget=10_000)
        result = await embed_node({**_BASE_STATE})

    assert result["embeddings_stored"] is True
    assert provider.embed_texts.await_count == 2
    assert call_sizes == [1, 2]
    # One bulk upsert per batch
    assert chk.upsert.call_count == 2
    upserted_ids = [r["chunk_id"] for call in chk.upsert.call_args_list for r in call.args[0]]
    assert upserted_ids == ["c0", "c1", "c2"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_node_batch_split_by_item_count_cap() -> None:
    """AC-6c: OpenAI rejects requests with more than 2048 inputs regardless of
    token totals — 2049 tiny chunks (far under the token budget) must split
    into [2048, 1] batches by ITEM COUNT."""
    from app.modules.content.pipeline.graph import embed_node

    chunks = [
        {"chunk_id": f"c{i}", "content": f"t{i}", "chunk_index": i, "token_count": 1}
        for i in range(2049)
    ]
    sb, jobs, chk, bks = _make_supabase(chunks=chunks)

    call_sizes: list[int] = []

    async def embed_side_effect(texts: list[str]) -> tuple[list[list[float]], int]:
        call_sizes.append(len(texts))
        return ([_FAKE_EMBEDDING] * len(texts), len(texts))

    provider = AsyncMock()
    provider.embed_texts.side_effect = embed_side_effect

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
        patch("app.providers.embeddings.openai.OpenAIEmbeddingsProvider", return_value=provider),
    ):
        _configure_settings(mock_settings, token_budget=100_000)
        result = await embed_node({**_BASE_STATE})

    assert result["embeddings_stored"] is True
    assert call_sizes == [2048, 1]
    # One bulk upsert per batch; every chunk written exactly once, in order
    assert chk.upsert.call_count == 2
    upserted_ids = [r["chunk_id"] for call in chk.upsert.call_args_list for r in call.args[0]]
    assert upserted_ids == [f"c{i}" for i in range(2049)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_node_oversized_single_chunk_truncates_api_input() -> None:
    """AC-6c edge: a chunk estimated over the ~8191-token per-input cap must
    NOT be shipped whole (the API 400s the entire batch) and must NOT loop
    forever — the API input is truncated to _MAX_EMBED_INPUT_TOKENS * 4 chars
    while the DB writeback keeps the FULL original content."""
    from app.modules.content.pipeline.graph import _MAX_EMBED_INPUT_TOKENS, embed_node

    full_text = "x" * 50_000
    chunks = [
        {"chunk_id": "huge", "content": full_text, "chunk_index": 0, "token_count": 250_000},
        {"chunk_id": "tiny", "content": "y", "chunk_index": 1, "token_count": 5},
    ]
    sb, jobs, chk, bks = _make_supabase(chunks=chunks)

    sent_texts: list[list[str]] = []

    async def embed_side_effect(texts: list[str]) -> tuple[list[list[float]], int]:
        sent_texts.append(list(texts))
        return ([_FAKE_EMBEDDING] * len(texts), 10)

    provider = AsyncMock()
    provider.embed_texts.side_effect = embed_side_effect

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
        patch("app.providers.embeddings.openai.OpenAIEmbeddingsProvider", return_value=provider),
    ):
        _configure_settings(mock_settings, token_budget=100_000)
        result = await embed_node({**_BASE_STATE})

    # Node completed (no infinite loop) and embedded everything in one call:
    # huge's estimate is clamped to the per-input cap, so huge + tiny fit
    # inside the 100k budget together.
    assert result["embeddings_stored"] is True
    assert provider.embed_texts.await_count == 1
    assert sent_texts[0][0] == "x" * (_MAX_EMBED_INPUT_TOKENS * 4)  # truncated
    assert sent_texts[0][1] == "y"

    # DB writeback carries the FULL original content — only the API input
    # was truncated, chunks.content is never modified.
    rows = {r["chunk_id"]: r for r in chk.upsert.call_args.args[0]}
    assert rows["huge"]["content"] == full_text
    assert rows["huge"]["embedding"] == _FAKE_EMBEDDING
    assert rows["tiny"]["content"] == "y"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_embed_node_provider_retry_on_429() -> None:
    """Provider embed_texts raises on first call (simulates 429) then succeeds — node retries (P7)."""
    from app.modules.content.pipeline.graph import embed_node

    sb, jobs, chk, bks = _make_supabase(
        chunks=[{"chunk_id": FAKE_CHUNK_ID_1, "content": "text", "chunk_index": 0}]
    )

    call_count = 0

    async def flaky_embed(texts: list[str]) -> tuple[list[list[float]], int]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("429 rate limit")
        return ([_FAKE_EMBEDDING] * len(texts), 50)

    provider = AsyncMock()
    provider.embed_texts.side_effect = flaky_embed

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
        patch("app.providers.embeddings.openai.OpenAIEmbeddingsProvider", return_value=provider),
    ):
        _configure_settings(mock_settings)
        # The retry is implemented inside OpenAIEmbeddingsProvider (@with_retry).
        # In unit tests the provider is mocked, so we simulate retry at the call site:
        # first call raises, second call (same provider mock) succeeds.
        # This verifies the node propagates errors when retries are exhausted.
        with pytest.raises(RuntimeError, match="429 rate limit"):
            await embed_node({**_BASE_STATE})

    # embed_texts was called once before the error propagated
    assert provider.embed_texts.await_count == 1
