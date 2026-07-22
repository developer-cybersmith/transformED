"""
Unit tests for Story 1.3: Structure detection node + rule-based detection helpers.

The `openai` package is NOT installed in the test environment (only used at
runtime). The OpenAILLMProvider module is therefore stubbed by injecting a fake
module into sys.modules via patch.dict — the same technique used anywhere a lazy
import inside a function body references an unavailable top-level package.

Patching strategy:
- `patch.dict("sys.modules", {"app.providers.llm.openai": <fake_module>})`
  intercepts the lazy `from app.providers.llm.openai import OpenAILLMProvider`
  executed inside structure_node and returns our mock class instead.
- All other lazy imports (app.core.db, app.config, app.schemas, structure_detection)
  are importable without external packages; they are patched at their definition sites.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Constants ─────────────────────────────────────────────────────────────────

FAKE_LESSON_ID = "33333333-3333-3333-3333-333333333333"
FAKE_BOOK_ID = "11111111-1111-1111-1111-111111111111"

RAW_TEXT_WITH_HEADINGS = (
    "1. Introduction\n\nThis is body text for the introduction.\n\n"
    "1.1 Background\n\nMore background text here.\n\n"
    "1.2 Motivation\n\nMotivation text goes here.\n"
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_supabase_mock(node_outputs: dict | None = None) -> MagicMock:
    jobs_mock = MagicMock()
    jobs_data = {"node_outputs": node_outputs or {}}
    (
        jobs_mock.select.return_value.eq.return_value.single.return_value.execute.return_value.data
    ) = jobs_data

    sb = MagicMock()
    sb.table.return_value = jobs_mock
    return sb


def _make_document_structure(n_sections: int = 2, body: str | None = None) -> Any:
    """Return a DocumentStructure Pydantic instance for LLM mock responses.

    ``body`` (when given) is used verbatim for EVERY section so the mock
    satisfies the AC-4 data-loss guard (total body chars ≥ 90% of raw_text) —
    tests exercising LLM-adoption paths must pass the raw text here.
    """
    from app.schemas import DocumentStructure, SectionBoundary

    sections = [
        SectionBoundary(
            id=f"s{i}",
            title=f"Section {i}",
            level="section" if i > 0 else "chapter",
            body=body if body is not None else f"Body text for section {i}.",
            page_start=max(1, i + 1),
            page_end=max(1, i + 2),
        )
        for i in range(n_sections)
    ]
    return DocumentStructure(sections=sections)


def _make_provider_mock(
    complete_result: Any = None,
    side_effect: Exception | None = None,
) -> tuple[MagicMock, MagicMock, dict]:
    """Return (mock_class, mock_instance, sys_modules_patch_dict).

    The returned sys_modules_patch_dict should be passed to
    patch.dict("sys.modules", ...) so that the lazy import inside structure_node
    picks up the mock class instead of the real (unavailable) openai module.
    """
    mock_instance = MagicMock()
    if side_effect:
        mock_instance.complete_structured = AsyncMock(side_effect=side_effect)
    else:
        mock_instance.complete_structured = AsyncMock(return_value=complete_result)

    mock_class = MagicMock(return_value=mock_instance)

    fake_module = MagicMock()
    fake_module.OpenAILLMProvider = mock_class

    return mock_class, mock_instance, {"app.providers.llm.openai": fake_module}


def _base_state() -> dict[str, Any]:
    return {
        "lesson_id": FAKE_LESSON_ID,
        "book_id": FAKE_BOOK_ID,
        "raw_text": RAW_TEXT_WITH_HEADINGS,
        "font_blocks": [],
        "progress_pct": 7.0,
        "error": None,
    }


# ── Tests: structure_node ─────────────────────────────────────────────────────


@pytest.mark.unit
async def test_structure_node_happy_path() -> None:
    """LLM returns valid DocumentStructure → sections list populated correctly."""
    from app.modules.content.pipeline.graph import structure_node

    state = _base_state()
    sb = _make_supabase_mock(node_outputs={})
    # Faithful bodies (full raw_text) so the AC-4 data-loss guard adopts the LLM output.
    mock_doc_structure = _make_document_structure(2, body=RAW_TEXT_WITH_HEADINGS)
    mock_class, mock_instance, modules_patch = _make_provider_mock(
        complete_result=mock_doc_structure
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", modules_patch),
        patch(
            "app.modules.content.pipeline.graph._update_job_progress",
            new_callable=AsyncMock,
        ),
    ):
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        # Story 2-16 (RC-1): structure_node now coalesces sections. These
        # adoption tests use a no-op floor (bodies are small synthetic docs);
        # coalesce behaviour is covered directly in test_coalesce_sections.py and
        # the node-level wiring is covered by test_structure_node_coalesces_*.
        mock_settings.return_value.structure_min_section_chars = 10
        mock_settings.return_value.structure_max_sections = 60
        result = await structure_node(state)

    sections = result.get("sections", [])
    assert len(sections) == 2
    assert result["progress_pct"] == 14.0
    # Each section must have the fields chunk_node depends on
    for s in sections:
        assert "id" in s
        assert "title" in s
        assert "level" in s
        assert "body" in s
        assert "page_start" in s
        assert "page_end" in s


@pytest.mark.unit
async def test_structure_node_idempotent() -> None:
    """structure_node returns cached sections without calling LLM when already done."""
    from app.modules.content.pipeline.graph import structure_node

    cached_sections = [
        {
            "id": "s0",
            "title": "Cached Chapter",
            "level": "chapter",
            "body": "Cached body text.",
            "page_start": 1,
            "page_end": 5,
        }
    ]
    sb = _make_supabase_mock(node_outputs={"structure": {"sections": cached_sections}})
    state = _base_state()
    mock_class, mock_instance, modules_patch = _make_provider_mock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings"),
        patch.dict("sys.modules", modules_patch),
        patch(
            "app.modules.content.pipeline.graph._update_job_progress",
            new_callable=AsyncMock,
        ),
    ):
        result = await structure_node(state)

    mock_instance.complete_structured.assert_not_called()
    assert result["sections"] == cached_sections
    assert result["progress_pct"] == 14.0


@pytest.mark.unit
async def test_structure_node_llm_failure_falls_back() -> None:
    """When LLM raises, structure_node falls back to rule-based sections (no re-raise)."""
    from app.modules.content.pipeline.graph import structure_node

    state = _base_state()
    sb = _make_supabase_mock(node_outputs={})
    mock_class, mock_instance, modules_patch = _make_provider_mock(
        side_effect=RuntimeError("LLM timeout")
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", modules_patch),
        patch(
            "app.modules.content.pipeline.graph._update_job_progress",
            new_callable=AsyncMock,
        ),
    ):
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        # Story 2-16 (RC-1): structure_node now coalesces sections. These
        # adoption tests use a no-op floor (bodies are small synthetic docs);
        # coalesce behaviour is covered directly in test_coalesce_sections.py and
        # the node-level wiring is covered by test_structure_node_coalesces_*.
        mock_settings.return_value.structure_min_section_chars = 10
        mock_settings.return_value.structure_max_sections = 60
        # Must not raise even though LLM failed
        result = await structure_node(state)

    assert isinstance(result.get("sections"), list)
    assert len(result["sections"]) >= 1, "Fallback must produce at least one section"


@pytest.mark.unit
async def test_structure_node_empty_input_fallback() -> None:
    """Empty raw_text + no font_blocks → single fallback section returned, no crash."""
    from app.modules.content.pipeline.graph import structure_node

    state = {**_base_state(), "raw_text": "", "font_blocks": []}
    sb = _make_supabase_mock(node_outputs={})
    mock_class, mock_instance, modules_patch = _make_provider_mock(
        side_effect=RuntimeError("LLM error")
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", modules_patch),
        patch(
            "app.modules.content.pipeline.graph._update_job_progress",
            new_callable=AsyncMock,
        ),
    ):
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        # Story 2-16 (RC-1): structure_node now coalesces sections. These
        # adoption tests use a no-op floor (bodies are small synthetic docs);
        # coalesce behaviour is covered directly in test_coalesce_sections.py and
        # the node-level wiring is covered by test_structure_node_coalesces_*.
        mock_settings.return_value.structure_min_section_chars = 10
        mock_settings.return_value.structure_max_sections = 60
        result = await structure_node(state)

    sections = result.get("sections", [])
    assert len(sections) == 1
    assert sections[0]["id"] == "s0"
    assert sections[0]["level"] == "chapter"


@pytest.mark.unit
async def test_structure_node_writes_checkpoint() -> None:
    """structure_node writes last_node='structure' + node_outputs to lesson_jobs."""
    from app.modules.content.pipeline.graph import structure_node

    state = _base_state()
    sb = _make_supabase_mock(node_outputs={})
    # Faithful body so the AC-4 guard adopts the LLM output before checkpointing.
    mock_doc_structure = _make_document_structure(1, body=RAW_TEXT_WITH_HEADINGS)
    mock_class, mock_instance, modules_patch = _make_provider_mock(
        complete_result=mock_doc_structure
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", modules_patch),
        patch(
            "app.modules.content.pipeline.graph._update_job_progress",
            new_callable=AsyncMock,
        ),
    ):
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        # Story 2-16 (RC-1): structure_node now coalesces sections. These
        # adoption tests use a no-op floor (bodies are small synthetic docs);
        # coalesce behaviour is covered directly in test_coalesce_sections.py and
        # the node-level wiring is covered by test_structure_node_coalesces_*.
        mock_settings.return_value.structure_min_section_chars = 10
        mock_settings.return_value.structure_max_sections = 60
        await structure_node(state)

    jobs_mock = sb.table("lesson_jobs")
    update_calls = jobs_mock.update.call_args_list
    assert update_calls, "lesson_jobs.update must be called for checkpoint"
    # First update call is the checkpoint write
    payload = update_calls[0].args[0]
    assert payload.get("last_node") == "structure"
    assert "node_outputs" in payload
    assert "structure" in payload["node_outputs"]
    assert "sections" in payload["node_outputs"]["structure"]


# ── Tests: detect_headings ────────────────────────────────────────────────────


@pytest.mark.unit
def test_detect_headings_numbered_returns_candidates() -> None:
    """Numbered headings like '1. Introduction' produce at least one candidate."""
    from app.modules.content.pipeline.nodes.structure_detection import detect_headings

    raw_text = "1. Introduction\n\nBody text.\n\n1.1 Background\n\nMore text."
    candidates = detect_headings(raw_text, font_blocks=[])

    assert len(candidates) >= 1
    texts = [c["text"] for c in candidates]
    assert any("Introduction" in t for t in texts)


@pytest.mark.unit
def test_detect_headings_font_size_bold() -> None:
    """A large bold font block found in raw_text is detected as a heading candidate."""
    from app.modules.content.pipeline.nodes.structure_detection import detect_headings

    raw_text = "Chapter One: Fundamentals\n\nBody text here."
    font_blocks = [
        {
            "text": "Chapter One: Fundamentals",
            "bbox": [0, 0, 200, 20],
            "font": {"name": "Arial-Bold", "size": 24.0, "bold": True},
            "page": 0,
        },
        {
            "text": "Body text here.",
            "bbox": [0, 30, 200, 45],
            "font": {"name": "Arial", "size": 12.0, "bold": False},
            "page": 0,
        },
    ]
    candidates = detect_headings(raw_text, font_blocks=font_blocks)

    assert len(candidates) >= 1
    assert any("Chapter One" in c["text"] for c in candidates)


@pytest.mark.unit
def test_detect_headings_deduplicates() -> None:
    """Same heading detected by both font and regex appears only once."""
    from app.modules.content.pipeline.nodes.structure_detection import detect_headings

    raw_text = "1. Introduction\n\nBody text."
    font_blocks = [
        {
            "text": "1. Introduction",
            "bbox": [0, 0, 150, 20],
            "font": {"name": "Arial-Bold", "size": 20.0, "bold": True},
            "page": 0,
        },
        {
            "text": "Body text.",
            "bbox": [0, 30, 150, 45],
            "font": {"name": "Arial", "size": 12.0, "bold": False},
            "page": 0,
        },
    ]
    candidates = detect_headings(raw_text, font_blocks=font_blocks)

    heading_texts = [c["text"] for c in candidates]
    assert heading_texts.count("1. Introduction") <= 1, "Dedup must prevent duplicate headings"


@pytest.mark.unit
def test_detect_headings_empty_inputs() -> None:
    """Empty raw_text and empty font_blocks returns empty list — no crash."""
    from app.modules.content.pipeline.nodes.structure_detection import detect_headings

    candidates = detect_headings("", font_blocks=[])
    assert candidates == []


# ── Tests: build_section_bodies ───────────────────────────────────────────────


@pytest.mark.unit
def test_build_section_bodies_fallback_when_no_candidates() -> None:
    """No candidates → single fallback section with full raw_text."""
    from app.modules.content.pipeline.nodes.structure_detection import build_section_bodies

    sections = build_section_bodies("Some text.", candidates=[], total_pages=3)
    assert len(sections) == 1
    assert sections[0]["id"] == "s0"
    assert sections[0]["level"] == "chapter"
    assert sections[0]["body"] == "Some text."
    assert sections[0]["page_start"] == 1
    assert sections[0]["page_end"] == 3


@pytest.mark.unit
def test_build_section_bodies_assigns_ids_sequentially() -> None:
    """Section ids are s0, s1, … in order."""
    from app.modules.content.pipeline.nodes.structure_detection import build_section_bodies

    raw_text = "Chapter 1\n\nBody A.\n\nChapter 2\n\nBody B."
    candidates = [
        {"text": "Chapter 1", "level": "chapter", "char_offset": 0},
        {"text": "Chapter 2", "level": "chapter", "char_offset": raw_text.index("Chapter 2")},
    ]
    sections = build_section_bodies(raw_text, candidates, total_pages=5)

    assert [s["id"] for s in sections] == ["s0", "s1"]


# ── Tests: workers TLS fix ────────────────────────────────────────────────────


@pytest.mark.unit
def test_workers_build_redis_settings_tls() -> None:
    """_build_redis_settings sets ssl=True for rediss:// URLs (Railway TLS)."""
    from app.workers.main import _build_redis_settings

    with patch("app.workers.main.get_settings") as mock_settings:
        mock_settings.return_value.redis_url = "rediss://user:pass@host.railway.app:6380/0"
        settings = _build_redis_settings()

    assert settings.ssl is True


@pytest.mark.unit
def test_workers_build_redis_settings_no_tls() -> None:
    """_build_redis_settings sets ssl=False for plain redis:// URLs."""
    from app.workers.main import _build_redis_settings

    with patch("app.workers.main.get_settings") as mock_settings:
        mock_settings.return_value.redis_url = "redis://localhost:6379/0"
        settings = _build_redis_settings()

    assert settings.ssl is False


# ── Tests: AC 11 — multi-heading document produces ≥ 3 sections ──────────────


@pytest.mark.unit
def test_ac11_multi_heading_chapter_produces_three_or_more_sections() -> None:
    """AC 11: a chapter with numbered headings produces at least 3 sections."""
    from app.modules.content.pipeline.nodes.structure_detection import (
        build_section_bodies,
        detect_headings,
    )

    raw_text = (
        "1. Introduction\n\n"
        "This is introductory body text covering the basics of the topic.\n\n"
        "1.1 Background\n\n"
        "Background material for the chapter, covering prior work and context.\n\n"
        "1.2 Scope and Objectives\n\n"
        "This section defines the scope of the chapter and its learning objectives.\n\n"
        "1.3 Organisation\n\n"
        "An overview of how the remaining sections are organised.\n\n"
        "1.4 Summary\n\n"
        "Key points from the chapter are collected here for revision.\n"
    )
    candidates = detect_headings(raw_text, font_blocks=[])
    sections = build_section_bodies(raw_text, candidates, total_pages=20)

    assert len(sections) >= 3, (
        f"Expected ≥ 3 sections for a 20-page chapter with numbered headings; got {len(sections)}"
    )


@pytest.mark.unit
async def test_structure_node_coalesces_oversegmented_rule_based() -> None:
    """Story 2-16 (RC-1) wiring: a how-to doc whose rule-based detection yields
    many step-sections is coalesced to <= structure_max_sections by the node,
    losing no text (this is the exact production blocker shape)."""
    from app.modules.content.pipeline.graph import structure_node

    body_pad = "Follow the detailed on-screen instruction carefully here. " * 6  # ~348 chars
    steps = "\n\n".join(f"{i}. Click Button Number {i}\n{body_pad}marker{i}" for i in range(1, 31))
    state = {**_base_state(), "raw_text": steps}
    sb = _make_supabase_mock(node_outputs={})
    # LLM validation raises -> deterministic rule-based path, then coalesce.
    _mock_class, _mock_instance, modules_patch = _make_provider_mock(
        side_effect=RuntimeError("llm unavailable")
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch.dict("sys.modules", modules_patch),
        patch(
            "app.modules.content.pipeline.graph._update_job_progress",
            new_callable=AsyncMock,
        ),
    ):
        mock_settings.return_value.llm_mini = "gpt-4o-mini"
        mock_settings.return_value.structure_min_section_chars = 200
        mock_settings.return_value.structure_max_sections = 8
        result = await structure_node(state)

    sections = result["sections"]
    assert len(sections) == 8, f"must be capped at max_sections=8; got {len(sections)}"
    joined = " ".join(s["body"] for s in sections) + " " + " ".join(s["title"] for s in sections)
    for i in range(1, 31):
        assert f"marker{i}" in joined, f"step {i} body was dropped — text loss!"
