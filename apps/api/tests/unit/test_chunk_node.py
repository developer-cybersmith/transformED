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
from unittest.mock import AsyncMock, MagicMock, call, patch

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
    chapter_id: str = FAKE_CHAPTER_ID,
) -> MagicMock:
    """Build a Supabase mock that covers lesson_jobs reads, chapters insert,
    chunks upsert, and lesson_jobs update (checkpoint write)."""
    jobs_data = {"node_outputs": node_outputs or {}}

    jobs_table = MagicMock()
    (
        jobs_table.select.return_value
        .eq.return_value
        .single.return_value
        .execute.return_value
        .data
    ) = jobs_data

    chapter_table = MagicMock()
    chapter_table.insert.return_value.execute.return_value.data = [
        {"chapter_id": chapter_id}
    ]

    chunks_table = MagicMock()

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

    # No chapters.insert or chunks.upsert on cache hit
    chapters_table = sb.table("chapters")
    chapters_table.insert.assert_not_called()
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
async def test_chunk_node_writes_chapter_row() -> None:
    """chunk_node inserts one chapter row with lesson_id, book_id, chapter_index=1."""
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

    chapters_table = sb.table("chapters")
    chapters_table.insert.assert_called_once()
    insert_payload = chapters_table.insert.call_args.args[0]
    assert insert_payload["lesson_id"] == FAKE_LESSON_ID
    assert insert_payload["book_id"] == FAKE_BOOK_ID
    assert insert_payload["chapter_index"] == 1


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
    """Empty sections list → empty chunks; chapters.insert still called; chunks.upsert NOT called."""
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
    sb.table("chapters").insert.assert_called_once()
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
        first = [c["id"] for c in chunk_sections(sections, target=512, overlap=64, tokenizer_name="cl100k_base")]
        second = [c["id"] for c in chunk_sections(sections, target=512, overlap=64, tokenizer_name="cl100k_base")]

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

    section = {"id": "s0", "title": "Pure", "body": "pure function test", "page_start": 1, "page_end": 1}
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
def test_chunk_sections_multiple_sections_produce_chunks_for_each() -> None:
    """10 sections each produce at least one chunk — minimum 10 total."""
    _, _, tiktoken_patch = _make_tiktoken_mock()

    sections = [
        {"id": f"s{i}", "title": f"Section {i}", "body": f"body text for section {i}", "page_start": i + 1, "page_end": i + 1}
        for i in range(10)
    ]

    with patch.dict("sys.modules", tiktoken_patch):
        from app.modules.content.pipeline.nodes.chunking import chunk_sections
        chunks = chunk_sections(sections, target=512, overlap=64, tokenizer_name="cl100k_base")

    assert len(chunks) >= 10
    section_ids_in_chunks = {c["section_id"] for c in chunks}
    assert section_ids_in_chunks == {f"s{i}" for i in range(10)}
