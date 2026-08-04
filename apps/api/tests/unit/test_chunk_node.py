"""
Unit tests for Story 1.4: Semantic chunking node + chunking helper functions.

tiktoken is NOT installed in the test environment. It is injected via
patch.dict("sys.modules", {"tiktoken": fake_tiktoken_module}) — the same
pattern established in Story 1.3 for the unavailable openai package.

The fake encoding treats each whitespace-separated word as one token, giving
deterministic and easy-to-reason-about token counts in tests.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Constants ─────────────────────────────────────────────────────────────────

FAKE_LESSON_ID = "44444444-4444-4444-4444-444444444444"
FAKE_BOOK_ID = "11111111-1111-1111-1111-111111111111"
FAKE_CHAPTER_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"

_SECTION_A = {
    "id": "s0",
    "title": "Introduction",
    "level": "chapter",
    "body": "This is the introduction body text.",
    "page_start": 1,
    "page_end": 2,
}
_SECTION_B = {
    "id": "s1",
    "title": "Background",
    "level": "section",
    "body": "This is the background section body.",
    "page_start": 3,
    "page_end": 4,
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_tiktoken_mock() -> tuple[MagicMock, MagicMock, dict[str, Any]]:
    """Fake tiktoken where each word == one token.

    Returns (fake_enc, fake_tiktoken_module, sys_modules_patch).
    """
    fake_enc = MagicMock()
    fake_enc.encode.side_effect = lambda text: text.split()
    fake_enc.decode.side_effect = lambda tokens: " ".join(tokens)

    fake_tiktoken = MagicMock()
    fake_tiktoken.get_encoding.return_value = fake_enc

    return fake_enc, fake_tiktoken, {"tiktoken": fake_tiktoken}


def _make_supabase_mock(
    node_outputs: dict[str, Any] | None = None,
    existing_chunks: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Build a Supabase mock that covers lesson_jobs reads, the chunk-reuse
    probe on `chunks`, the chunks upsert, and lesson_jobs update (checkpoint).

    Story 1-13: `chunk_node` no longer writes `chapters` at all — the `chapters`
    table mock is kept solely so tests can assert that no write reaches it.

    `existing_chunks` seeds the reuse probe
    (`chunks.select().eq(chapter_id).order().range().execute()`); the default of
    `[]` means "this chapter has never been chunked", i.e. the fresh path.
    """
    jobs_data = {"node_outputs": node_outputs or {}}

    jobs_table = MagicMock()
    (
        jobs_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data
    ) = jobs_data

    # chunk_node is a strict non-writer of `chapters` — no return values needed.
    chapter_table = MagicMock()

    chunks_table = MagicMock()
    (
        chunks_table.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value.data
    ) = list(existing_chunks or [])

    def _table_router(name: str) -> MagicMock:
        if name == "lesson_jobs":
            return jobs_table
        if name == "chapters":
            return chapter_table
        if name == "chunks":
            return chunks_table
        return MagicMock()

    sb = MagicMock()
    sb.table.side_effect = _table_router
    return sb


def _base_state(**overrides: Any) -> dict[str, Any]:
    base = {
        "lesson_id": FAKE_LESSON_ID,
        "book_id": FAKE_BOOK_ID,
        # Story 1-13 AC4/AC5: chapter_id arrives on PipelineState (from
        # `lessons.chapter_id`). chunk_node no longer manufactures one.
        "chapter_id": FAKE_CHAPTER_ID,
        "sections": [_SECTION_A, _SECTION_B],
        "progress_pct": 14.0,
        "error": None,
    }
    base.update(overrides)
    return base


# ── Tests: chunk_node ─────────────────────────────────────────────────────────


@pytest.mark.unit
async def test_chunk_node_happy_path() -> None:
    """chunk_node returns non-empty chunks; each chunk has all required fields."""
    from app.modules.content.pipeline.graph import chunk_node

    state = _base_state()
    sb = _make_supabase_mock()
    _, fake_tiktoken, tiktoken_patch = _make_tiktoken_mock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", tiktoken_patch),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        mock_settings.return_value.chunk_target_tokens = 512
        mock_settings.return_value.chunk_overlap_tokens = 64
        mock_settings.return_value.embedding_tokenizer = "cl100k_base"
        result = await chunk_node(state)

    chunks = result.get("chunks", [])
    assert len(chunks) >= 1
    assert result["progress_pct"] == 20.0

    for chunk in chunks:
        assert "id" in chunk
        assert "section_id" in chunk
        assert "text" in chunk
        assert "token_count" in chunk
        assert "section_title" in chunk
        assert "page_start" in chunk
        assert "page_end" in chunk


@pytest.mark.unit
async def test_chunk_node_idempotent() -> None:
    """If node_outputs already has 'chunk', skip all work and return cached data."""
    from app.modules.content.pipeline.graph import chunk_node

    cached_chunks = [
        {
            "id": "s0_c0",
            "section_id": "s0",
            "text": "Cached chunk text.",
            "token_count": 3,
            "section_title": "Introduction",
            "page_start": 1,
            "page_end": 2,
        }
    ]
    sb = _make_supabase_mock(
        node_outputs={"chunk": {"chunks": cached_chunks, "chapter_id": FAKE_CHAPTER_ID}}
    )
    state = _base_state()
    _, fake_tiktoken, tiktoken_patch = _make_tiktoken_mock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings"),
        patch.dict("sys.modules", tiktoken_patch),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        result = await chunk_node(state)

    assert result["chunks"] == cached_chunks
    assert result["progress_pct"] == 20.0

    # tiktoken must not be called — get_encoding is never invoked on cache hit
    fake_tiktoken.get_encoding.assert_not_called()

    # No chapters write or chunks.upsert on cache hit
    chapters_table = sb.table("chapters")
    chapters_table.insert.assert_not_called()
    chapters_table.upsert.assert_not_called()
    chunks_table = sb.table("chunks")
    chunks_table.upsert.assert_not_called()


@pytest.mark.unit
async def test_chunk_node_writes_checkpoint() -> None:
    """Checkpoint written to lesson_jobs with last_node='chunk' + chunk cache."""
    from app.modules.content.pipeline.graph import chunk_node

    state = _base_state()
    sb = _make_supabase_mock()
    _, _, tiktoken_patch = _make_tiktoken_mock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", tiktoken_patch),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        mock_settings.return_value.chunk_target_tokens = 512
        mock_settings.return_value.chunk_overlap_tokens = 64
        mock_settings.return_value.embedding_tokenizer = "cl100k_base"
        await chunk_node(state)

    jobs_table = sb.table("lesson_jobs")
    update_calls = jobs_table.update.call_args_list
    assert update_calls, "lesson_jobs.update must be called (checkpoint)"

    payload = update_calls[0].args[0]
    assert payload.get("last_node") == "chunk"
    assert "node_outputs" in payload
    assert "chunk" in payload["node_outputs"]
    chunk_cache = payload["node_outputs"]["chunk"]
    assert "chunks" in chunk_cache
    assert "chapter_id" in chunk_cache
    assert chunk_cache["chapter_id"] == FAKE_CHAPTER_ID


@pytest.mark.unit
async def test_chunk_node_writes_no_chapter_row_and_uses_state_chapter_id() -> None:
    """Story 1-13 AC4/AC5 — the INVERSE of the pre-1-13 assertion.

    This test used to assert that chunk_node upserted a hardcoded
    `chapters` row (`chapter_index=1`) so `chunks.chapter_id` had something to
    point at. That block is deleted: it was the reason the pipeline could only
    ever produce "chapter 1 of this upload". The coverage is kept, pointed at
    the new invariant — the pipeline is a strict NON-writer of `chapters`
    (AC8), and the chapter_id on the chunk rows is the one from state.
    """
    from app.modules.content.pipeline.graph import chunk_node

    state = _base_state()
    sb = _make_supabase_mock()
    _, _, tiktoken_patch = _make_tiktoken_mock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", tiktoken_patch),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        mock_settings.return_value.chunk_target_tokens = 512
        mock_settings.return_value.chunk_overlap_tokens = 64
        mock_settings.return_value.embedding_tokenizer = "cl100k_base"
        await chunk_node(state)

    # No write of ANY kind reaches `chapters`.
    assert "chapters" not in [call.args[0] for call in sb.table.call_args_list], (
        "chunk_node touched the `chapters` table at all; Story 1-13 AC8 makes "
        "the pipeline a strict non-writer of `chapters` as well as `books`"
    )
    chapters_table = sb.table("chapters")
    chapters_table.insert.assert_not_called()
    chapters_table.upsert.assert_not_called()
    chapters_table.update.assert_not_called()

    # …and the chapter_id the chunk rows carry is the one supplied on state,
    # not one this node invented.
    rows_written = sb.table("chunks").upsert.call_args.args[0]
    assert rows_written, "expected chunk rows to be written"
    assert {row["chapter_id"] for row in rows_written} == {FAKE_CHAPTER_ID}


@pytest.mark.unit
async def test_chunk_node_writes_chunk_rows() -> None:
    """chunk_node upserts chunk rows with chapter_id, book_id, content, chunk_index."""
    from app.modules.content.pipeline.graph import chunk_node

    state = _base_state()
    sb = _make_supabase_mock()
    _, _, tiktoken_patch = _make_tiktoken_mock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", tiktoken_patch),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        mock_settings.return_value.chunk_target_tokens = 512
        mock_settings.return_value.chunk_overlap_tokens = 64
        mock_settings.return_value.embedding_tokenizer = "cl100k_base"
        await chunk_node(state)

    chunks_table = sb.table("chunks")
    chunks_table.upsert.assert_called_once()
    rows = chunks_table.upsert.call_args.args[0]
    assert len(rows) >= 1
    for i, row in enumerate(rows):
        assert row["chapter_id"] == FAKE_CHAPTER_ID
        assert row["book_id"] == FAKE_BOOK_ID
        assert "content" in row
        assert "chunk_index" in row
        assert row["chunk_index"] == i
        assert "token_count" in row
        assert "section" in row
        assert "page_start" in row
        assert "page_end" in row


@pytest.mark.unit
async def test_chunk_node_empty_sections() -> None:
    """Empty sections → empty chunks; chunks.upsert NOT called.

    Story 1-13: the "…and the chapter row is still written" half of this
    assertion is inverted, not dropped — there is no chapter row to write.
    """
    from app.modules.content.pipeline.graph import chunk_node

    state = _base_state(sections=[])
    sb = _make_supabase_mock()
    _, _, tiktoken_patch = _make_tiktoken_mock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", tiktoken_patch),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        mock_settings.return_value.chunk_target_tokens = 512
        mock_settings.return_value.chunk_overlap_tokens = 64
        mock_settings.return_value.embedding_tokenizer = "cl100k_base"
        result = await chunk_node(state)

    assert result["chunks"] == []
    sb.table("chapters").insert.assert_not_called()
    sb.table("chapters").upsert.assert_not_called()
    sb.table("chunks").upsert.assert_not_called()


# ── Tests: chunking helpers ───────────────────────────────────────────────────


@pytest.mark.unit
def test_chunk_sections_splits_long_section() -> None:
    """A section with multiple paragraphs exceeding target produces multiple chunks.

    The fake tokenizer counts words as tokens. 600 words split into 6 paragraphs
    of 100 words each: with target=200 words-as-tokens each pair of paragraphs
    fills one chunk, producing >= 2 chunks.
    """
    _, _, tiktoken_patch = _make_tiktoken_mock()

    # 6 paragraphs × 100 words each = 600 total; target=200 → >= 2 chunks
    paragraphs = [" ".join(f"w{i}_{j}" for j in range(100)) for i in range(6)]
    long_body = "\n\n".join(paragraphs)
    section = {
        "id": "s0",
        "title": "Long Section",
        "body": long_body,
        "page_start": 1,
        "page_end": 5,
    }

    with patch.dict("sys.modules", tiktoken_patch):
        from app.modules.content.pipeline.nodes.chunking import chunk_sections

        chunks = chunk_sections([section], target=200, overlap=10, tokenizer_name="cl100k_base")

    assert len(chunks) >= 2, f"Expected >= 2 chunks for multi-paragraph section, got {len(chunks)}"


@pytest.mark.unit
def test_chunk_sections_short_section() -> None:
    """A 10-word section produces exactly 1 chunk with the full text preserved."""
    _, _, tiktoken_patch = _make_tiktoken_mock()

    body = "one two three four five six seven eight nine ten"
    section = {"id": "s0", "title": "Short", "body": body, "page_start": 1, "page_end": 1}

    with patch.dict("sys.modules", tiktoken_patch):
        from app.modules.content.pipeline.nodes.chunking import chunk_sections

        chunks = chunk_sections([section], target=512, overlap=64, tokenizer_name="cl100k_base")

    assert len(chunks) == 1
    assert "one" in chunks[0]["text"]
    assert "ten" in chunks[0]["text"]


@pytest.mark.unit
def test_chunk_sections_overlap_appears_in_next_chunk() -> None:
    """The last N tokens of chunk N should appear at the start of chunk N+1.

    Body has 4 paragraphs of 60 words each (240 words total). With target=100
    and overlap=10, at least 2 chunks are produced and chunk 1's text contains
    words that appeared at the end of chunk 0.
    """
    _, _, tiktoken_patch = _make_tiktoken_mock()

    paragraphs = [" ".join(f"w{i}_{j}" for j in range(60)) for i in range(4)]
    body = "\n\n".join(paragraphs)
    section = {"id": "s0", "title": "S", "body": body, "page_start": 1, "page_end": 2}

    with patch.dict("sys.modules", tiktoken_patch):
        from app.modules.content.pipeline.nodes.chunking import chunk_sections

        chunks = chunk_sections([section], target=100, overlap=10, tokenizer_name="cl100k_base")

    assert len(chunks) >= 2
    tail_words = chunks[0]["text"].split()[-5:]  # last 5 words of chunk 0
    next_text = chunks[1]["text"]
    assert any(w in next_text for w in tail_words), (
        "Overlap: some tail words of chunk 0 should appear in chunk 1"
    )


@pytest.mark.unit
def test_chunk_section_ids_are_deterministic() -> None:
    """Same sections input → same chunk IDs on every call."""
    _, _, tiktoken_patch = _make_tiktoken_mock()

    sections = [
        {"id": "s0", "title": "A", "body": "hello world foo bar", "page_start": 1, "page_end": 1},
        {"id": "s1", "title": "B", "body": "alpha beta gamma", "page_start": 2, "page_end": 2},
    ]

    with patch.dict("sys.modules", tiktoken_patch):
        from app.modules.content.pipeline.nodes.chunking import chunk_sections

        first = [
            c["id"]
            for c in chunk_sections(sections, target=512, overlap=64, tokenizer_name="cl100k_base")
        ]
        second = [
            c["id"]
            for c in chunk_sections(sections, target=512, overlap=64, tokenizer_name="cl100k_base")
        ]

    assert first == second


@pytest.mark.unit
def test_chunk_sections_chunk_id_format() -> None:
    """Chunk IDs follow the pattern '{section_id}_c{index}' (e.g. s0_c0, s0_c1)."""
    _, _, tiktoken_patch = _make_tiktoken_mock()

    section = {"id": "s0", "title": "X", "body": "a b c", "page_start": 1, "page_end": 1}

    with patch.dict("sys.modules", tiktoken_patch):
        from app.modules.content.pipeline.nodes.chunking import chunk_sections

        chunks = chunk_sections([section], target=512, overlap=64, tokenizer_name="cl100k_base")

    for i, chunk in enumerate(chunks):
        assert chunk["id"] == f"s0_c{i}", f"Expected s0_c{i}, got {chunk['id']}"


@pytest.mark.unit
def test_chunk_sections_is_pure() -> None:
    """chunk_sections contains no Supabase calls — it is a pure function."""
    _, _, tiktoken_patch = _make_tiktoken_mock()

    section = {
        "id": "s0",
        "title": "Pure",
        "body": "pure function test",
        "page_start": 1,
        "page_end": 1,
    }
    mock_supabase = MagicMock()

    with (
        patch("app.core.db.get_supabase", return_value=mock_supabase),
        patch.dict("sys.modules", tiktoken_patch),
    ):
        from app.modules.content.pipeline.nodes.chunking import chunk_sections

        chunk_sections([section], target=512, overlap=64, tokenizer_name="cl100k_base")

    mock_supabase.table.assert_not_called()


@pytest.mark.unit
def test_chunk_sections_empty_body_returns_single_empty_chunk() -> None:
    """A section with an empty body produces exactly one empty chunk — no crash."""
    _, _, tiktoken_patch = _make_tiktoken_mock()

    section = {"id": "s0", "title": "Empty", "body": "", "page_start": 1, "page_end": 1}

    with patch.dict("sys.modules", tiktoken_patch):
        from app.modules.content.pipeline.nodes.chunking import chunk_sections

        chunks = chunk_sections([section], target=512, overlap=64, tokenizer_name="cl100k_base")

    assert len(chunks) == 1
    assert chunks[0]["id"] == "s0_c0"
    assert chunks[0]["text"] == ""
    assert chunks[0]["token_count"] == 0


@pytest.mark.unit
def test_ac7_large_section_produces_at_least_eight_chunks() -> None:
    """AC 7: a ~5000-word section with target=512 produces ≥8 chunks.

    The fake tokenizer counts words as tokens, so a 5000-word body produces
    roughly 5000/512 ≈ 9.7 chunks before overlap.  Even after overlap shrinks
    effective capacity each chunk still yields at least 8 distinct chunks.
    """
    _, _, tiktoken_patch = _make_tiktoken_mock()

    # Build a 5000-word body: 500 sentences of 10 words each separated by ". "
    sentence = "alpha bravo charlie delta echo foxtrot golf hotel india juliet"
    body = ". ".join([sentence] * 500) + "."

    section = {"id": "s0", "title": "Large Section", "body": body, "page_start": 1, "page_end": 50}

    with patch.dict("sys.modules", tiktoken_patch):
        from app.modules.content.pipeline.nodes.chunking import chunk_sections

        chunks = chunk_sections([section], target=512, overlap=64, tokenizer_name="cl100k_base")

    assert len(chunks) >= 8, (
        f"Expected ≥8 chunks for a ~5000-word section with target=512; got {len(chunks)}"
    )
    assert all(c["token_count"] > 0 for c in chunks), "All chunks must have token_count > 0"


@pytest.mark.unit
def test_chunk_sections_multiple_sections_produce_chunks_for_each() -> None:
    """10 sections each produce at least one chunk — minimum 10 total."""
    _, _, tiktoken_patch = _make_tiktoken_mock()

    sections = [
        {
            "id": f"s{i}",
            "title": f"Section {i}",
            "body": f"body text for section {i}",
            "page_start": i + 1,
            "page_end": i + 1,
        }
        for i in range(10)
    ]

    with patch.dict("sys.modules", tiktoken_patch):
        from app.modules.content.pipeline.nodes.chunking import chunk_sections

        chunks = chunk_sections(sections, target=512, overlap=64, tokenizer_name="cl100k_base")

    assert len(chunks) >= 10
    section_ids_in_chunks = {c["section_id"] for c in chunks}
    assert section_ids_in_chunks == {f"s{i}" for i in range(10)}


@pytest.mark.unit
async def test_chunk_node_retry_cannot_collide_on_the_chapters_constraint() -> None:
    """Story 1-13 AC4 — the INVERSE of the pre-1-13 assertion, same concern.

    The original question was: an ARQ retry re-enters chunk_node (its checkpoint
    is written at the END of the node, so a failure after the chunks upsert
    leaves node_outputs["chunk"] unset), and `20260803000000_chapters_book_scoped.sql`
    adds UNIQUE (book_id, chapter_index) — so a plain INSERT of the hardcoded
    chapter row would 23505 on all of max_tries=3 and permanently stick the
    lesson. The old answer was "use an upsert with on_conflict".

    The Story 1-13 answer is stronger and is what this test now asserts: there
    is NO chapter write left to collide. The node re-entered a second time must
    still touch `chapters` zero times, and must produce the same chunk rows
    against the same state-supplied chapter_id.
    """
    from app.modules.content.pipeline.graph import chunk_node

    sb = _make_supabase_mock()
    _, _fake_tiktoken, tiktoken_patch = _make_tiktoken_mock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", tiktoken_patch),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        mock_settings.return_value.chunk_target_tokens = 512
        mock_settings.return_value.chunk_overlap_tokens = 64
        mock_settings.return_value.embedding_tokenizer = "cl100k_base"
        first = await chunk_node(_base_state())
        # Second entry = the ARQ retry. The reuse probe is still empty (the mock
        # models the crash-before-commit window), so this takes the same path.
        second = await chunk_node(_base_state())

    assert "chapters" not in [call.args[0] for call in sb.table.call_args_list], (
        "chunk_node wrote to `chapters`; after Story 1-13 there must be no "
        "chapter write for an ARQ retry to collide with"
    )
    chapters = sb.table("chapters")
    assert not chapters.insert.called
    assert not chapters.upsert.called

    assert first["chunks"] == second["chunks"], "retry must reproduce identical chunks"
    for call in sb.table("chunks").upsert.call_args_list:
        assert {row["chapter_id"] for row in call.args[0]} == {FAKE_CHAPTER_ID}
