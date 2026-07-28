"""
Unit tests for Story 2-0 (Tier 1 pipeline integration fixes) — graph.py lane.

Covers:
- AC-4: structure_node data-loss guard (LLM output rejected when its section
  bodies cover < 90% of raw_text; adopted when faithful).
- AC-5: extract_node dynamic timeout formula + orphan-proof subprocess cleanup
  (child reaped on task cancellation, not just TimeoutError).
- AC-6: embed_node empty-chunk alignment, >1000-row pagination, and the
  completion check that refuses to checkpoint a half-embedded chapter.

All external services (Supabase, OpenAI providers) are mocked; patching targets
the SOURCE modules because graph.py uses lazy in-function imports.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Constants ─────────────────────────────────────────────────────────────────

FAKE_LESSON_ID = "20202020-2020-2020-2020-202020202020"
FAKE_BOOK_ID = "11111111-1111-1111-1111-111111111111"
FAKE_USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
FAKE_CHAPTER_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
FAKE_PDF_PATH = f"{FAKE_USER_ID}/{FAKE_BOOK_ID}/chapter1.pdf"
FAKE_PDF_BYTES = b"%PDF-1.4 minimal\n%%EOF"

_FAKE_EMBEDDING = [0.1] * 1536

# Plain lowercase prose — matches none of the heading regexes, so rule-based
# detection falls back to a single chapter-level section holding ALL raw_text.
LARGE_RAW_TEXT = "plain prose about spaced repetition and recall practice. " * 40


# ── Shared helpers ────────────────────────────────────────────────────────────


def _timeout_settings(arq_job_timeout_s: int = 1800) -> SimpleNamespace:
    return SimpleNamespace(
        extract_timeout_base_s=120,
        extract_timeout_per_page_s=1.3,
        extract_timeout_cap_s=1500,
        arq_job_timeout_s=arq_job_timeout_s,
    )


def _configure_extract_settings(mock_settings: MagicMock) -> None:
    cfg = mock_settings.return_value
    cfg.ocr_text_yield_threshold = 50
    cfg.extract_timeout_base_s = 120
    cfg.extract_timeout_per_page_s = 1.3
    cfg.extract_timeout_cap_s = 1500
    cfg.arq_job_timeout_s = 1800


def _configure_embed_settings(mock_settings: MagicMock) -> None:
    cfg = mock_settings.return_value
    cfg.embedding_model = "text-embedding-3-small"
    cfg.embedding_dimensions = 1536
    cfg.embed_batch_token_budget = 100_000


def _make_jobs_table(node_outputs: dict[str, Any]) -> MagicMock:
    t = MagicMock()
    t.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "node_outputs": node_outputs
    }
    t.update.return_value.eq.return_value.execute.return_value = MagicMock()
    return t


def _make_chunks_table(pages: list[list[dict[str, Any]]]) -> MagicMock:
    """Paginated IS-NULL select mock: each .execute() consumes the next entry
    of ``pages``, returning [] once exhausted (rows embedded by the writeback
    drop out of the IS-NULL filter in the real DB)."""
    t = MagicMock()
    queue: list[list[dict[str, Any]]] = [list(p) for p in pages]

    def _execute() -> MagicMock:
        resp = MagicMock()
        resp.data = queue.pop(0) if queue else []
        return resp

    (
        t.select.return_value.eq.return_value.is_.return_value.order.return_value.range.return_value.execute.side_effect
    ) = _execute
    t.upsert.return_value.execute.return_value = MagicMock()
    return t


def _make_embed_supabase(
    pages: list[list[dict[str, Any]]],
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Return (supabase, jobs_table, chunks_table) wired for embed_node."""
    jobs = _make_jobs_table({"chunk": {"chapter_id": FAKE_CHAPTER_ID, "chunks": []}})
    chk = _make_chunks_table(pages)
    books = MagicMock()
    books.update.return_value.eq.return_value.execute.return_value = MagicMock()

    sb = MagicMock()

    def _table(name: str) -> MagicMock:
        if name == "lesson_jobs":
            return jobs
        if name == "chunks":
            return chk
        if name == "books":
            return books
        return MagicMock()

    sb.table.side_effect = _table
    return sb, jobs, chk


def _make_extract_supabase() -> MagicMock:
    jobs = _make_jobs_table({})
    sb = MagicMock()
    sb.table.return_value = jobs
    sb.storage.from_.return_value.download.return_value = FAKE_PDF_BYTES
    return sb


def _embed_base_state() -> dict[str, Any]:
    return {
        "lesson_id": FAKE_LESSON_ID,
        "book_id": FAKE_BOOK_ID,
        "user_id": FAKE_USER_ID,
        "chunks": [],
        "embeddings_stored": False,
        "error": None,
        "progress_pct": 20.0,
    }


def _make_llm_sections(bodies: list[str]) -> Any:
    """Build a DocumentStructure whose sections carry the given bodies."""
    from app.schemas import DocumentStructure, SectionBoundary

    sections = [
        SectionBoundary(
            id=f"llm{i}",
            title=f"LLM Section {i}",
            level="chapter" if i == 0 else "section",
            body=body,
            page_start=1,
            page_end=2,
        )
        for i, body in enumerate(bodies)
    ]
    return DocumentStructure(sections=sections)


def _make_llm_provider_patch(result: Any) -> dict[str, Any]:
    """sys.modules patch dict routing the lazy OpenAILLMProvider import to a mock."""
    instance = MagicMock()
    instance.complete_structured = AsyncMock(return_value=result)
    fake_module = MagicMock()
    fake_module.OpenAILLMProvider = MagicMock(return_value=instance)
    return {"app.providers.llm.openai": fake_module}


# ── AC-4: structure data-loss guard ───────────────────────────────────────────


@pytest.mark.unit
async def test_structure_guard_rejects_llm_output_with_tiny_bodies() -> None:
    """LLM sections covering < 90% of raw_text are REJECTED — rule-based
    sections (which preserve all text) win."""
    from app.modules.content.pipeline.graph import structure_node

    state = {
        "lesson_id": FAKE_LESSON_ID,
        "book_id": FAKE_BOOK_ID,
        "raw_text": LARGE_RAW_TEXT,
        "font_blocks": [],
        "progress_pct": 7.0,
        "error": None,
    }
    sb = MagicMock()
    sb.table.return_value = _make_jobs_table({})
    # LLM silently dropped everything past the 6000-char prompt window
    llm_result = _make_llm_sections(["tiny body one.", "tiny body two."])

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", _make_llm_provider_patch(llm_result)),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        # Story 2-16 (RC-1): no-op coalesce bounds for these structure-guard
        # tests (they assert on the 90% adoption proxy, not on coalescing).
        mock_settings.return_value.structure_min_section_chars = 1
        mock_settings.return_value.structure_max_sections = 10_000
        result = await structure_node(state)

    sections = result["sections"]
    # Rule-based fallback for headingless prose = 1 section with the FULL text
    assert len(sections) == 1
    assert sections[0]["body"] == LARGE_RAW_TEXT
    assert not any(s["title"].startswith("LLM Section") for s in sections)


@pytest.mark.unit
async def test_structure_guard_adopts_faithful_llm_output() -> None:
    """LLM sections whose bodies cover ≥ 90% of raw_text ARE adopted."""
    from app.modules.content.pipeline.graph import structure_node

    state = {
        "lesson_id": FAKE_LESSON_ID,
        "book_id": FAKE_BOOK_ID,
        "raw_text": LARGE_RAW_TEXT,
        "font_blocks": [],
        "progress_pct": 7.0,
        "error": None,
    }
    sb = MagicMock()
    sb.table.return_value = _make_jobs_table({})
    half = len(LARGE_RAW_TEXT) // 2
    llm_result = _make_llm_sections([LARGE_RAW_TEXT[:half], LARGE_RAW_TEXT[half:]])

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", _make_llm_provider_patch(llm_result)),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        # Story 2-16 (RC-1): no-op coalesce bounds for these structure-guard
        # tests (they assert on the 90% adoption proxy, not on coalescing).
        mock_settings.return_value.structure_min_section_chars = 1
        mock_settings.return_value.structure_max_sections = 10_000
        result = await structure_node(state)

    sections = result["sections"]
    assert len(sections) == 2
    assert [s["title"] for s in sections] == ["LLM Section 0", "LLM Section 1"]
    assert sections[0]["body"] + sections[1]["body"] == LARGE_RAW_TEXT


@pytest.mark.unit
async def test_structure_guard_llm_raises_keeps_rule_based_sections() -> None:
    """2026-07-20 review finding (Test Coverage layer): the branch where the
    LLM provider RAISES mid-call (e.g. complete_structured throws) was
    untested — only the <90% reject / ≥90% adopt / empty-skip paths were. A
    provider exception with non-empty raw_text must be caught and the
    rule-based sections kept, never crash the node."""
    from app.modules.content.pipeline.graph import structure_node

    state = {
        "lesson_id": FAKE_LESSON_ID,
        "book_id": FAKE_BOOK_ID,
        "raw_text": LARGE_RAW_TEXT,
        "font_blocks": [],
        "progress_pct": 7.0,
        "error": None,
    }
    sb = MagicMock()
    sb.table.return_value = _make_jobs_table({})

    # Provider whose complete_structured RAISES rather than returns.
    instance = MagicMock()
    instance.complete_structured = AsyncMock(side_effect=RuntimeError("provider exploded"))
    fake_module = MagicMock()
    fake_module.OpenAILLMProvider = MagicMock(return_value=instance)

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", {"app.providers.llm.openai": fake_module}),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        # Story 2-16 (RC-1): no-op coalesce bounds for these structure-guard
        # tests (they assert on the 90% adoption proxy, not on coalescing).
        mock_settings.return_value.structure_min_section_chars = 1
        mock_settings.return_value.structure_max_sections = 10_000
        result = await structure_node(state)  # must NOT raise

    sections = result["sections"]
    # Rule-based fallback for headingless prose = 1 section with the FULL text.
    assert len(sections) == 1
    assert sections[0]["body"] == LARGE_RAW_TEXT


@pytest.mark.unit
@pytest.mark.parametrize("raw_text", ["", "   \n\t  "])
async def test_structure_guard_empty_raw_text_skips_llm_keeps_rule_based(
    raw_text: str,
) -> None:
    """Review hardening: with empty/whitespace raw_text the < 90% length proxy
    is vacuously false (llm_total < 0 never holds), so hallucinated LLM
    sections would be adopted. The node must skip the LLM ENTIRELY and keep
    the rule-based fallback section."""
    from app.modules.content.pipeline.graph import structure_node

    state = {
        "lesson_id": FAKE_LESSON_ID,
        "book_id": FAKE_BOOK_ID,
        "raw_text": raw_text,
        "font_blocks": [],
        "progress_pct": 7.0,
        "error": None,
    }
    sb = MagicMock()
    sb.table.return_value = _make_jobs_table({})
    # A hallucinating LLM would return non-empty sections for empty input
    llm_result = _make_llm_sections(["hallucinated body that came from nowhere."])
    instance = MagicMock()
    instance.complete_structured = AsyncMock(return_value=llm_result)
    fake_module = MagicMock()
    fake_module.OpenAILLMProvider = MagicMock(return_value=instance)

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", {"app.providers.llm.openai": fake_module}),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        # Story 2-16 (RC-1): no-op coalesce bounds for these structure-guard
        # tests (they assert on the 90% adoption proxy, not on coalescing).
        mock_settings.return_value.structure_min_section_chars = 1
        mock_settings.return_value.structure_max_sections = 10_000
        result = await structure_node(state)

    # LLM never called — no tokens burned, no hallucination window
    instance.complete_structured.assert_not_awaited()
    # Rule-based fallback for headingless input: 1 chapter-level "Document" section
    sections = result["sections"]
    assert len(sections) == 1
    assert sections[0]["title"] == "Document"
    assert not any(s["title"].startswith("LLM Section") for s in sections)


@pytest.mark.unit
async def test_structure_guard_adopts_llm_output_at_exact_90_percent_boundary() -> None:
    """Boundary pin: the guard rejects on STRICT less-than — LLM bodies
    totalling EXACTLY 0.9 × len(raw_text) are adopted."""
    from app.modules.content.pipeline.graph import structure_node

    state = {
        "lesson_id": FAKE_LESSON_ID,
        "book_id": FAKE_BOOK_ID,
        "raw_text": LARGE_RAW_TEXT,
        "font_blocks": [],
        "progress_pct": 7.0,
        "error": None,
    }
    sb = MagicMock()
    sb.table.return_value = _make_jobs_table({})
    boundary_len = int(0.9 * len(LARGE_RAW_TEXT))
    assert boundary_len == 0.9 * len(LARGE_RAW_TEXT), "fixture must hit the boundary exactly"
    llm_result = _make_llm_sections([LARGE_RAW_TEXT[:boundary_len]])

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", _make_llm_provider_patch(llm_result)),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        # Story 2-16 (RC-1): no-op coalesce bounds for these structure-guard
        # tests (they assert on the 90% adoption proxy, not on coalescing).
        mock_settings.return_value.structure_min_section_chars = 1
        mock_settings.return_value.structure_max_sections = 10_000
        result = await structure_node(state)

    sections = result["sections"]
    assert [s["title"] for s in sections] == ["LLM Section 0"]
    assert len(sections[0]["body"]) == boundary_len


@pytest.mark.unit
async def test_structure_guard_duplicated_bodies_pass_length_proxy() -> None:
    """Pinning test — KNOWN LIMITATION (Tier-3 #18): the AC-4 guard is a pure
    LENGTH proxy. LLM output that duplicates the first half of raw_text twice
    totals 100% of len(raw_text) while actually covering only 50% of the
    content, and IS adopted. Fixing this needs content-aware coverage
    (boundary-only structure LLM) — out of scope for Story 2-0."""
    from app.modules.content.pipeline.graph import structure_node

    state = {
        "lesson_id": FAKE_LESSON_ID,
        "book_id": FAKE_BOOK_ID,
        "raw_text": LARGE_RAW_TEXT,
        "font_blocks": [],
        "progress_pct": 7.0,
        "error": None,
    }
    sb = MagicMock()
    sb.table.return_value = _make_jobs_table({})
    half = len(LARGE_RAW_TEXT) // 2
    # Same first half twice: length sums to len(raw_text), content covers half.
    llm_result = _make_llm_sections([LARGE_RAW_TEXT[:half], LARGE_RAW_TEXT[:half]])

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", _make_llm_provider_patch(llm_result)),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        # Story 2-16 (RC-1): no-op coalesce bounds for these structure-guard
        # tests (they assert on the 90% adoption proxy, not on coalescing).
        mock_settings.return_value.structure_min_section_chars = 1
        mock_settings.return_value.structure_max_sections = 10_000
        result = await structure_node(state)

    # Documents (does not endorse) current behavior: duplicated bodies adopted.
    assert [s["title"] for s in result["sections"]] == ["LLM Section 0", "LLM Section 1"]


# ── AC-5: extract timeout formula ─────────────────────────────────────────────


@pytest.mark.unit
def test_extract_timeout_formula() -> None:
    """timeout = min(base + per_page × page_estimate, cap, arq_job_timeout − 300),
    page_estimate = max(1, pdf_bytes // 30_000)."""
    from app.modules.content.pipeline.graph import _compute_extract_timeout

    s = _timeout_settings()
    # Tiny PDF → page_estimate floors at 1
    assert _compute_extract_timeout(1_000, s) == pytest.approx(120 + 1.3)
    # 3 MB → ~100 pages
    assert _compute_extract_timeout(3_000_000, s) == pytest.approx(120 + 1.3 * 100)
    # Huge PDF → hard cap (1500) wins over arq−300 (1500) and the formula
    assert _compute_extract_timeout(10**9, s) == 1500
    # Short ARQ job timeout → arq_job_timeout − 300 dominates the cap
    assert _compute_extract_timeout(10**9, _timeout_settings(arq_job_timeout_s=1000)) == 700


@pytest.mark.unit
def test_extract_timeout_always_fires_before_arq_cancels() -> None:
    """Contract: with real defaults the subprocess timeout can never exceed
    arq_job_timeout_s − 300, so extract_node's own cleanup always runs first."""
    from app.modules.content.pipeline.graph import _compute_extract_timeout

    s = _timeout_settings()
    for size in (0, 1, 30_000, 10**6, 10**7, 10**9, 10**12):
        assert _compute_extract_timeout(size, s) <= s.arq_job_timeout_s - 300


@pytest.mark.unit
def test_extract_timeout_never_below_one_second() -> None:
    """Review hardening: a pathological env override (arq_job_timeout_s <= 300)
    used to yield a 0/negative wait_for timeout. The result is clamped to >= 1s
    for ANY input."""
    from app.modules.content.pipeline.graph import _compute_extract_timeout

    for arq_timeout in (300, 200, 100, 1):
        for size in (0, 1, 30_000, 10**9):
            timeout = _compute_extract_timeout(
                size, _timeout_settings(arq_job_timeout_s=arq_timeout)
            )
            assert timeout >= 1.0
    # And the clamp floors exactly at 1.0 when arq − 300 goes non-positive
    assert _compute_extract_timeout(10**9, _timeout_settings(arq_job_timeout_s=300)) == 1.0


@pytest.mark.unit
def test_settings_rejects_arq_timeout_below_extract_cap_plus_300() -> None:
    """Review hardening: the AC-5 invariant (arq_job_timeout_s >=
    extract_timeout_cap_s + 300) is now enforced at Settings construction —
    a misconfigured env fails fast instead of silently orphaning extract
    subprocesses. Required fields come from the conftest env stubs."""
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError, match="arq_job_timeout_s"):
        Settings(arq_job_timeout_s=600, extract_timeout_cap_s=1500)


@pytest.mark.unit
def test_settings_accepts_arq_timeout_at_exact_invariant_boundary() -> None:
    """arq_job_timeout_s == extract_timeout_cap_s + 300 exactly is valid
    (the invariant is >=, not >)."""
    from app.config import Settings

    s = Settings(arq_job_timeout_s=1800, extract_timeout_cap_s=1500)
    assert s.arq_job_timeout_s == 1800
    assert s.extract_timeout_cap_s == 1500


# ── AC-5: orphan-proof cleanup on cancellation ────────────────────────────────


@pytest.mark.unit
async def test_extract_node_cancellation_reaps_subprocess() -> None:
    """When ARQ cancels the node task mid-extraction (CancelledError, NOT
    TimeoutError), the finally block must still kill and await the child —
    this is the observed 4GB-orphan bug."""
    import asyncio
    import sys as _sys

    from app.modules.content.pipeline.graph import extract_node

    class FakeProc:
        def __init__(self) -> None:
            self.returncode: int | None = None
            self.pid = 4321
            self.kill_called = False
            self.waited = False

        async def communicate(self) -> tuple[bytes, bytes]:
            await asyncio.Event().wait()  # blocks forever — never returns
            raise AssertionError("unreachable")

        def kill(self) -> None:
            self.kill_called = True

        async def wait(self) -> int:
            self.waited = True
            return -9

    fake = FakeProc()
    exec_mock = AsyncMock(return_value=fake)
    sb = _make_extract_supabase()
    state = {
        "lesson_id": FAKE_LESSON_ID,
        "book_id": FAKE_BOOK_ID,
        "user_id": FAKE_USER_ID,
        "source_pdf_path": FAKE_PDF_PATH,
        "chapter_content": "",
        "progress_pct": 0.0,
        "error": None,
    }

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", exec_mock),
        # create=True: os.getpgid/os.killpg do not exist on Windows — without it
        # patch() raises AttributeError on the dev platform (win32).
        patch("os.getpgid", return_value=4321, create=True),
        patch("os.killpg", create=True) as mock_killpg,
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_extract_settings(mock_settings)

        task = asyncio.create_task(extract_node(state))
        # Wait until the node has actually spawned the subprocess and is
        # blocked inside wait_for(proc.communicate()).
        for _ in range(500):
            if exec_mock.await_count:
                break
            await asyncio.sleep(0.005)
        assert exec_mock.await_count == 1, "subprocess was never spawned"
        await asyncio.sleep(0.02)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    # The child was reaped despite CancelledError (no orphan left behind)
    if _sys.platform != "win32":
        mock_killpg.assert_called_once()
        assert not fake.kill_called  # posix path uses process-group kill
    else:
        assert fake.kill_called
    assert fake.waited, "proc.wait() must be awaited so the child is reaped"


# ── AC-6: embed_node alignment / pagination / completion check ────────────────


@pytest.mark.unit
async def test_embed_node_empty_chunk_does_not_misalign_vectors() -> None:
    """An empty-content chunk mid-batch must NOT shift later embeddings onto
    the wrong chunk_ids (the pre-fix bug zipped filtered texts against the
    unfiltered batch)."""
    from app.modules.content.pipeline.graph import embed_node

    e_first = [0.11] * 4
    e_third = [0.33] * 4
    pages = [
        [
            {"chunk_id": "chunk-a", "content": "first text", "chunk_index": 0, "token_count": 10},
            {
                "chunk_id": "chunk-b",
                "content": "   ",
                "chunk_index": 0,
                "token_count": 0,
            },  # empty → skipped
            {"chunk_id": "chunk-c", "content": "third text", "chunk_index": 0, "token_count": 10},
        ]
    ]
    sb, jobs, chk = _make_embed_supabase(pages)

    provider = AsyncMock()
    provider.embed_texts.return_value = ([e_first, e_third], 20)

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
        patch("app.providers.embeddings.openai.OpenAIEmbeddingsProvider", return_value=provider),
    ):
        _configure_embed_settings(mock_settings)
        result = await embed_node(_embed_base_state())

    assert result["embeddings_stored"] is True
    # Only the two non-empty texts were sent to OpenAI
    provider.embed_texts.assert_awaited_once_with(["first text", "third text"])

    # Every vector landed on the RIGHT chunk_id; the empty chunk got no row
    chk.upsert.assert_called_once()
    rows = {r["chunk_id"]: r["embedding"] for r in chk.upsert.call_args.args[0]}
    assert rows == {"chunk-a": e_first, "chunk-c": e_third}
    assert "chunk-b" not in rows


@pytest.mark.unit
async def test_embed_node_paginates_past_1000_row_cap() -> None:
    """1001 unembedded chunks arrive as two PostgREST pages (1000 + 1); ALL
    of them must be embedded — the pre-fix single select silently dropped
    everything past row 1000."""
    from app.modules.content.pipeline.graph import embed_node

    page1 = [
        {"chunk_id": f"c{i}", "content": f"text {i}", "chunk_index": 0, "token_count": 10}
        for i in range(1000)
    ]
    page2 = [{"chunk_id": "c1000", "content": "text 1000", "chunk_index": 0, "token_count": 10}]
    sb, jobs, chk = _make_embed_supabase([page1, page2])

    embedded_counts: list[int] = []

    async def embed_side_effect(texts: list[str]) -> tuple[list[list[float]], int]:
        embedded_counts.append(len(texts))
        return ([_FAKE_EMBEDDING] * len(texts), len(texts) * 10)

    provider = AsyncMock()
    provider.embed_texts.side_effect = embed_side_effect

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
        patch("app.providers.embeddings.openai.OpenAIEmbeddingsProvider", return_value=provider),
    ):
        _configure_embed_settings(mock_settings)
        result = await embed_node(_embed_base_state())

    assert result["embeddings_stored"] is True
    assert sum(embedded_counts) == 1001, "all 1001 chunks must be embedded"

    # The select walked consecutive .range() windows
    range_mock = chk.select.return_value.eq.return_value.is_.return_value.order.return_value.range
    range_windows = [c.args for c in range_mock.call_args_list]
    assert range_windows[0] == (0, 999)
    assert range_windows[1] == (1000, 1999)

    # All 1001 rows written back
    total_rows = sum(len(c.args[0]) for c in chk.upsert.call_args_list)
    assert total_rows == 1001

    # Checkpoint reflects completion
    payload = jobs.update.call_args[0][0]
    assert payload["node_outputs"]["embed"]["chunk_count"] == 1001


@pytest.mark.unit
async def test_embed_node_completion_check_blocks_checkpoint() -> None:
    """If the post-writeback IS-NULL re-query still finds a non-empty chunk,
    embed_node must raise and must NOT write its checkpoint."""
    from app.modules.content.pipeline.graph import embed_node

    stubborn = {
        "chunk_id": "stuck",
        "content": "never got embedded",
        "chunk_index": 0,
        "token_count": 10,
    }
    # Page sequence: initial fetch finds it; completion re-query finds it AGAIN
    # (simulating a silently failed writeback).
    sb, jobs, chk = _make_embed_supabase([[stubborn], [stubborn]])

    provider = AsyncMock()
    provider.embed_texts.return_value = ([_FAKE_EMBEDDING], 10)

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
        patch("app.providers.embeddings.openai.OpenAIEmbeddingsProvider", return_value=provider),
    ):
        _configure_embed_settings(mock_settings)
        with pytest.raises(RuntimeError, match="still unembedded"):
            await embed_node(_embed_base_state())

    # No checkpoint was written — the retry will re-run embed for the leftovers
    jobs.update.assert_not_called()


@pytest.mark.unit
async def test_embed_node_leftover_empty_chunks_do_not_block_completion() -> None:
    """Empty-content chunks legitimately keep embedding NULL — the completion
    check must ignore them instead of failing the node forever."""
    from app.modules.content.pipeline.graph import embed_node

    empty = {"chunk_id": "empty", "content": "", "chunk_index": 0, "token_count": 0}
    good = {"chunk_id": "good", "content": "real text", "chunk_index": 0, "token_count": 10}
    # Initial fetch: both rows; completion re-query: only the empty one remains NULL.
    sb, jobs, chk = _make_embed_supabase([[empty, good], [empty]])

    provider = AsyncMock()
    provider.embed_texts.return_value = ([_FAKE_EMBEDDING], 10)

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
        patch("app.providers.embeddings.openai.OpenAIEmbeddingsProvider", return_value=provider),
    ):
        _configure_embed_settings(mock_settings)
        result = await embed_node(_embed_base_state())

    assert result["embeddings_stored"] is True
    provider.embed_texts.assert_awaited_once_with(["real text"])
    # Checkpoint written despite the (legitimately) NULL empty chunk
    payload = jobs.update.call_args[0][0]
    assert payload["node_outputs"]["embed"]["chunk_count"] == 1
