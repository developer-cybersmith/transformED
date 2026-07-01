"""
Unit tests for Story 1.2: PDF extraction node + content_pipeline_job fix.

Patch note: graph.py and content_pipeline.py use lazy imports inside functions,
so we patch the ORIGINAL module (e.g. "app.core.db.get_supabase"), not the
consumer.  asyncio.create_subprocess_exec is an async function, so its mock
must be AsyncMock(return_value=proc) — NOT a plain MagicMock.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Constants ─────────────────────────────────────────────────────────────────

FAKE_LESSON_ID = "22222222-2222-2222-2222-222222222222"
FAKE_BOOK_ID = "11111111-1111-1111-1111-111111111111"
FAKE_USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
FAKE_PDF_PATH = f"{FAKE_USER_ID}/{FAKE_BOOK_ID}/chapter1.pdf"
FAKE_PDF_BYTES = b"%PDF-1.4 minimal\n%%EOF"

SUBPROCESS_STDOUT = json.dumps({
    "raw_text": "Chapter 1: Introduction\n\nThis is the text.",
    "page_count": 3,
    "image_files": [],
    "font_blocks": [],
}).encode()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_supabase_mock(node_outputs: dict | None = None) -> MagicMock:
    """Return a Supabase client mock whose table() side_effect distinguishes tables."""
    jobs_mock = MagicMock()
    jobs_data = {"node_outputs": node_outputs or {}}
    (jobs_mock.select.return_value
               .eq.return_value
               .single.return_value
               .execute.return_value
               .data) = jobs_data

    books_mock = MagicMock()

    def _table(name: str) -> MagicMock:
        if name == "lesson_jobs":
            return jobs_mock
        if name == "books":
            return books_mock
        return MagicMock()

    sb = MagicMock()
    sb.table.side_effect = _table
    sb.storage.from_.return_value.download.return_value = FAKE_PDF_BYTES
    return sb


def _make_subprocess_mock(stdout: bytes | None = None, returncode: int = 0) -> AsyncMock:
    """Return an AsyncMock for asyncio.create_subprocess_exec.

    Usage: ``patch("asyncio.create_subprocess_exec", _make_subprocess_mock())``
    Awaiting the mock returns the process object with .returncode and .communicate().
    """
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout or SUBPROCESS_STDOUT, b""))
    return AsyncMock(return_value=proc)


def _base_state() -> dict[str, Any]:
    return {
        "lesson_id": FAKE_LESSON_ID,
        "book_id": FAKE_BOOK_ID,
        "user_id": FAKE_USER_ID,
        "source_pdf_path": FAKE_PDF_PATH,
        "chapter_content": "",
        "progress_pct": 0.0,
        "error": None,
    }


# ── Tests: content_pipeline_job DB query fix ─────────────────────────────────


@pytest.mark.unit
async def test_content_pipeline_job_queries_lessons_not_lesson_jobs() -> None:
    """content_pipeline_job must query `lessons` for user_id/source_file_path/book_id,
    NOT lesson_jobs (which has none of those columns).
    """
    from app.workers.jobs.content_pipeline import content_pipeline_job

    table_calls: list[str] = []
    run_pipeline_kwargs: dict[str, Any] = {}

    def table_side_effect(name: str) -> MagicMock:
        table_calls.append(name)
        t = MagicMock()
        if name == "lessons":
            t.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
                "user_id": FAKE_USER_ID,
                "source_file_path": FAKE_PDF_PATH,
                "book_id": FAKE_BOOK_ID,
            }
        elif name == "lesson_jobs":
            t.update.return_value.eq.return_value.execute.return_value = MagicMock()
        return t

    sb = MagicMock()
    sb.table.side_effect = table_side_effect

    async def mock_run_pipeline(**kwargs: Any) -> dict:
        run_pipeline_kwargs.update(kwargs)
        return {
            "lesson_plan": {"title": "Test"},
            "slides": [],
            "audio_assets": [],
            "quiz_questions": [],
            "slide_images": [],
            "glossary": [],
            "intervention_prompts": [],
            "segment_summaries": [],
        }

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.modules.content.pipeline.graph.run_pipeline", side_effect=mock_run_pipeline),
        patch("app.core.websocket.manager.send", new_callable=AsyncMock),
        patch("app.core.cost_tracker.clear_lesson_cost", new_callable=AsyncMock),
    ):
        await content_pipeline_job({}, FAKE_LESSON_ID)

    assert "lessons" in table_calls, f"Must query 'lessons' table; got: {table_calls}"
    assert run_pipeline_kwargs.get("source_pdf_path") == FAKE_PDF_PATH, (
        f"run_pipeline must receive source_pdf_path={FAKE_PDF_PATH!r}; got {run_pipeline_kwargs}"
    )
    assert run_pipeline_kwargs.get("book_id") == FAKE_BOOK_ID


# ── Tests: extract_node ───────────────────────────────────────────────────────


@pytest.mark.unit
async def test_extract_node_happy_path() -> None:
    """extract_node downloads PDF, runs subprocess, returns raw_text + extracted_images."""
    from app.modules.content.pipeline.graph import extract_node

    state = _base_state()
    sb = _make_supabase_mock(node_outputs={})
    exec_mock = _make_subprocess_mock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", exec_mock),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        mock_settings.return_value.ocr_text_yield_threshold = 50
        result = await extract_node(state)

    assert result["raw_text"] == "Chapter 1: Introduction\n\nThis is the text."
    assert isinstance(result.get("extracted_images"), list)
    assert isinstance(result.get("font_blocks"), list)
    assert result["progress_pct"] == 7.0


@pytest.mark.unit
async def test_extract_node_writes_page_count() -> None:
    """extract_node must write page_count to the books table."""
    from app.modules.content.pipeline.graph import extract_node

    state = _base_state()
    sb = _make_supabase_mock(node_outputs={})
    exec_mock = _make_subprocess_mock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", exec_mock),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        mock_settings.return_value.ocr_text_yield_threshold = 50
        await extract_node(state)

    # books_mock captured via sb.table.side_effect
    books_mock = sb.table("books")
    books_update_calls = books_mock.update.call_args_list
    assert books_update_calls, "books.update was not called"
    payload = books_update_calls[0].args[0]
    assert payload.get("page_count") == 3


@pytest.mark.unit
async def test_extract_node_writes_checkpoint() -> None:
    """extract_node must write last_node='extract' and node_outputs to lesson_jobs."""
    from app.modules.content.pipeline.graph import extract_node

    state = _base_state()
    sb = _make_supabase_mock(node_outputs={})
    exec_mock = _make_subprocess_mock()

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", exec_mock),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        mock_settings.return_value.ocr_text_yield_threshold = 50
        await extract_node(state)

    jobs_mock = sb.table("lesson_jobs")
    jobs_update_calls = jobs_mock.update.call_args_list
    assert jobs_update_calls, "lesson_jobs.update was not called for checkpoint"
    payload = jobs_update_calls[0].args[0]
    assert payload.get("last_node") == "extract", f"last_node should be 'extract', got {payload}"
    assert "node_outputs" in payload
    assert "extract" in payload["node_outputs"]
    assert "font_blocks" in payload["node_outputs"]["extract"]


@pytest.mark.unit
async def test_extract_node_idempotent() -> None:
    """extract_node returns cached output without calling subprocess when already done."""
    from app.modules.content.pipeline.graph import extract_node

    cached = {
        "raw_text": "Cached text from previous run",
        "extracted_images": [{"page": 1, "path": "lesson-images/foo.png", "caption": ""}],
        "page_count": 5,
        "font_blocks": [{"text": "Chapter 1", "bbox": [0, 0, 100, 20], "font": {"name": "Arial-Bold", "size": 18.0, "bold": True}}],
    }

    state = _base_state()
    sb = _make_supabase_mock(node_outputs={"extract": cached})

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings"),
        patch("asyncio.create_subprocess_exec") as mock_exec,
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        result = await extract_node(state)

    mock_exec.assert_not_called()
    assert result["raw_text"] == "Cached text from previous run"
    assert result["extracted_images"] == cached["extracted_images"]
    assert result["font_blocks"] == cached["font_blocks"]


@pytest.mark.unit
async def test_extract_node_subprocess_failure_raises() -> None:
    """extract_node raises RuntimeError when subprocess exits non-zero."""
    from app.modules.content.pipeline.graph import extract_node

    state = _base_state()
    sb = _make_supabase_mock(node_outputs={})

    failing_proc = MagicMock()
    failing_proc.returncode = 1
    failing_proc.communicate = AsyncMock(return_value=(b"", b"pdfplumber: corrupted PDF"))
    failing_exec_mock = AsyncMock(return_value=failing_proc)

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", failing_exec_mock),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        mock_settings.return_value.ocr_text_yield_threshold = 50
        with pytest.raises(RuntimeError, match="PDF extraction subprocess failed"):
            await extract_node(state)


@pytest.mark.unit
async def test_extract_node_uploads_images() -> None:
    """extract_node uploads images returned by subprocess to the lesson-images bucket."""
    import os
    import tempfile

    from app.modules.content.pipeline.graph import extract_node

    state = _base_state()
    sb = _make_supabase_mock(node_outputs={})

    # Write a real temp file to simulate an image extracted by the subprocess
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")  # minimal PNG header
        img_path = fh.name

    try:
        stdout_with_img = json.dumps({
            "raw_text": "Chapter 1: Introduction",
            "page_count": 1,
            "image_files": [{"page": 1, "local_path": img_path}],
        }).encode()
        exec_mock = _make_subprocess_mock(stdout=stdout_with_img)

        with (
            patch("app.core.db.get_supabase", return_value=sb),
            patch("app.config.get_settings") as mock_settings,
            patch("asyncio.create_subprocess_exec", exec_mock),
            patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
        ):
            mock_settings.return_value.ocr_text_yield_threshold = 50
            result = await extract_node(state)

        upload_calls = sb.storage.from_.return_value.upload.call_args_list
        assert len(upload_calls) >= 1, "Expected upload call to lesson-images bucket"
        assert len(result["extracted_images"]) == 1
        assert result["extracted_images"][0]["page"] == 1
        assert result["extracted_images"][0]["path"] == f"{FAKE_LESSON_ID}/p1_0.png"
    finally:
        os.unlink(img_path)


@pytest.mark.unit
async def test_extract_node_subprocess_timeout_raises() -> None:
    """extract_node raises RuntimeError when subprocess exceeds 600-second timeout."""
    import asyncio as _asyncio

    from app.modules.content.pipeline.graph import extract_node

    state = _base_state()
    sb = _make_supabase_mock(node_outputs={})

    timeout_proc = MagicMock()
    timeout_proc.returncode = None
    timeout_proc.kill = MagicMock()
    # Plain MagicMock (not AsyncMock) — wait_for is patched to raise before awaiting communicate().
    timeout_proc.communicate = MagicMock()
    # wait() IS awaited (after kill) so it must be an AsyncMock.
    timeout_proc.wait = AsyncMock(return_value=None)
    timeout_exec_mock = AsyncMock(return_value=timeout_proc)

    async def _raise_timeout(coro: object, timeout: float) -> tuple[bytes, bytes]:
        raise _asyncio.TimeoutError

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", timeout_exec_mock),
        patch("asyncio.wait_for", side_effect=_raise_timeout),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        mock_settings.return_value.ocr_text_yield_threshold = 50
        with pytest.raises(RuntimeError, match="timed out after 600s"):
            await extract_node(state)

    timeout_proc.kill.assert_called_once()
