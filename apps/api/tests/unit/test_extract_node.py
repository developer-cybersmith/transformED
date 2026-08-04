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

SUBPROCESS_STDOUT = json.dumps(
    {
        "raw_text": "Chapter 1: Introduction\n\nThis is the text.",
        "page_count": 3,
        "image_files": [],
        "font_blocks": [],
    }
).encode()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_supabase_mock(node_outputs: dict | None = None) -> MagicMock:
    """Return a Supabase client mock whose table() side_effect distinguishes tables."""
    jobs_mock = MagicMock()
    jobs_data = {"node_outputs": node_outputs or {}}
    (
        jobs_mock.select.return_value.eq.return_value.single.return_value.execute.return_value.data
    ) = jobs_data

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


def _configure_settings(mock_settings: MagicMock) -> None:
    """Real numeric values for every settings field extract_node touches.

    The AC-5 dynamic timeout does arithmetic + min() on these — MagicMock
    attributes would produce garbage timeouts, so they must be real numbers.
    """
    cfg = mock_settings.return_value
    cfg.ocr_text_yield_threshold = 50
    cfg.extract_timeout_base_s = 120
    cfg.extract_timeout_per_page_s = 1.3
    cfg.extract_timeout_cap_s = 1500
    cfg.arq_job_timeout_s = 1800


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

    mock_redis = AsyncMock()
    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.modules.content.pipeline.graph.run_pipeline", side_effect=mock_run_pipeline),
        patch("app.core.websocket.manager.send", new_callable=AsyncMock),
        patch("app.core.cost_tracker.clear_lesson_cost", new_callable=AsyncMock),
        patch("app.core.redis.get_redis", return_value=mock_redis),
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
        _configure_settings(mock_settings)
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
        _configure_settings(mock_settings)
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
        _configure_settings(mock_settings)
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
        "font_blocks": [
            {
                "text": "Chapter 1",
                "bbox": [0, 0, 100, 20],
                "font": {"name": "Arial-Bold", "size": 18.0, "bold": True},
            }
        ],
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
        _configure_settings(mock_settings)
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
        stdout_with_img = json.dumps(
            {
                "raw_text": "Chapter 1: Introduction",
                "page_count": 1,
                "image_files": [{"page": 1, "local_path": img_path}],
            }
        ).encode()
        exec_mock = _make_subprocess_mock(stdout=stdout_with_img)

        with (
            patch("app.core.db.get_supabase", return_value=sb),
            patch("app.config.get_settings") as mock_settings,
            patch("asyncio.create_subprocess_exec", exec_mock),
            patch(
                "app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock
            ),
        ):
            _configure_settings(mock_settings)
            result = await extract_node(state)

        upload_calls = sb.storage.from_.return_value.upload.call_args_list
        assert len(upload_calls) >= 1, "Expected upload call to lesson-images bucket"
        assert len(result["extracted_images"]) == 1
        assert result["extracted_images"][0]["page"] == 1
        assert result["extracted_images"][0]["path"] == f"{FAKE_LESSON_ID}/p1_0.png"
    finally:
        os.unlink(img_path)


# ── Tests: AC-5 (Story 2-0b) parallel image uploads ──────────────────────────


def _write_fake_images(dir_path: str, n: int) -> list[dict[str, Any]]:
    """Create n minimal PNG files on disk and return subprocess-style image_files."""
    import os

    image_files: list[dict[str, Any]] = []
    for i in range(n):
        path = os.path.join(dir_path, f"img_{i}.png")
        with open(path, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n")
        image_files.append({"page": i + 1, "local_path": path})
    return image_files


def _stdout_with_images(image_files: list[dict[str, Any]], **extra: Any) -> bytes:
    return json.dumps(
        {
            "raw_text": "Chapter 1: Introduction",
            "page_count": len(image_files) or 1,
            "image_files": image_files,
            "font_blocks": [],
            **extra,
        }
    ).encode()


@pytest.mark.unit
async def test_extract_node_uploads_run_concurrently_bounded_by_semaphore(
    tmp_path: Any,
) -> None:
    """AC-5: uploads overlap (not serial) but never exceed _IMAGE_UPLOAD_CONCURRENCY.

    The instrumented upload sleeps briefly inside its worker thread and tracks
    an active-concurrency high-water mark: serial execution would peg it at 1;
    an unbounded gather with 12 images would exceed the semaphore cap.
    (Bound tuned 8→4 after the 1120-page live run rate-limited a 545-image
    storm — assert the range, not a magic number.)
    """
    import threading
    import time

    from app.modules.content.pipeline.graph import (
        _IMAGE_UPLOAD_CONCURRENCY,
        extract_node,
    )

    assert 2 <= _IMAGE_UPLOAD_CONCURRENCY <= 8

    state = _base_state()
    sb = _make_supabase_mock(node_outputs={})
    image_files = _write_fake_images(str(tmp_path), 12)
    exec_mock = _make_subprocess_mock(stdout=_stdout_with_images(image_files))

    lock = threading.Lock()
    active = 0
    high_water = 0

    def _slow_upload(*args: Any, **kwargs: Any) -> None:
        nonlocal active, high_water
        with lock:
            active += 1
            high_water = max(high_water, active)
        time.sleep(0.05)  # hold the slot so overlapping uploads are observable
        with lock:
            active -= 1

    sb.storage.from_.return_value.upload.side_effect = _slow_upload

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", exec_mock),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        result = await extract_node(state)

    assert len(result["extracted_images"]) == 12
    assert high_water > 1, "uploads ran strictly serially — AC-5 requires overlap"
    assert high_water <= _IMAGE_UPLOAD_CONCURRENCY, (
        f"semaphore bound violated: {high_water} concurrent uploads > {_IMAGE_UPLOAD_CONCURRENCY}"
    )


@pytest.mark.unit
async def test_extract_node_upload_failure_fails_node(tmp_path: Any) -> None:
    """AC-5: a PERSISTENTLY failing upload is retried 3x with backoff, then
    propagates out of gather and fails the node (no return_exceptions — no
    silent image loss). Retry added after the 2026-07-10 live run where one of
    20 concurrent uploads got a transient non-JSON storage response."""
    from app.modules.content.pipeline.graph import extract_node

    state = _base_state()
    sb = _make_supabase_mock(node_outputs={})
    image_files = _write_fake_images(str(tmp_path), 5)
    exec_mock = _make_subprocess_mock(stdout=_stdout_with_images(image_files))

    failing_attempts = {"count": 0}

    def _failing_upload(*args: Any, **kwargs: Any) -> None:
        if kwargs.get("path", "").endswith("p3_2.png"):
            failing_attempts["count"] += 1
            raise RuntimeError("storage 503: upload failed")

    sb.storage.from_.return_value.upload.side_effect = _failing_upload

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", exec_mock),
        patch("time.sleep"),
        patch("random.random", return_value=0.0),  # skip retry backoff in tests
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        with pytest.raises(RuntimeError, match="failed after 5 attempts"):
            await extract_node(state)

    # All 5 retry attempts were made against the persistently failing image.
    assert failing_attempts["count"] == 5

    # The node failed before writing its checkpoint.
    jobs_mock = sb.table("lesson_jobs")
    assert not jobs_mock.update.call_args_list, "checkpoint must not be written on upload failure"


@pytest.mark.unit
async def test_extract_node_upload_transient_blip_recovers(tmp_path: Any) -> None:
    """AC-5 retry: an upload that fails once then succeeds must NOT fail the
    node — the retry absorbs transient storage blips."""
    from app.modules.content.pipeline.graph import extract_node

    state = _base_state()
    sb = _make_supabase_mock(node_outputs={})
    image_files = _write_fake_images(str(tmp_path), 3)
    exec_mock = _make_subprocess_mock(stdout=_stdout_with_images(image_files))

    blip = {"fired": False}

    def _blip_once(*args: Any, **kwargs: Any) -> None:
        if kwargs.get("path", "").endswith("_0.png") and not blip["fired"]:
            blip["fired"] = True
            raise RuntimeError("storage transient: empty response")

    sb.storage.from_.return_value.upload.side_effect = _blip_once

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", exec_mock),
        patch("time.sleep"),
        patch("random.random", return_value=0.0),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        result = await extract_node(state)

    assert blip["fired"], "the transient failure path was never exercised"
    assert result["progress_pct"] == 7.0  # node completed normally


@pytest.mark.unit
async def test_extract_node_storage_images_order_is_deterministic(tmp_path: Any) -> None:
    """AC-5: storage_images preserves subprocess input (idx) order even when
    upload completion order is scrambled by concurrency."""
    import time

    from app.modules.content.pipeline.graph import extract_node

    state = _base_state()
    sb = _make_supabase_mock(node_outputs={})
    image_files = _write_fake_images(str(tmp_path), 6)
    exec_mock = _make_subprocess_mock(stdout=_stdout_with_images(image_files))

    completion_order: list[str] = []

    def _scrambling_upload(*args: Any, **kwargs: Any) -> None:
        path: str = kwargs["path"]
        idx = int(path.rsplit("_", 1)[1].removesuffix(".png"))
        time.sleep(0.05 * (6 - idx))  # earlier images finish LAST
        completion_order.append(path)

    sb.storage.from_.return_value.upload.side_effect = _scrambling_upload

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", exec_mock),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        result = await extract_node(state)

    expected_paths = [f"{FAKE_LESSON_ID}/p{i + 1}_{i}.png" for i in range(6)]
    assert [img["path"] for img in result["extracted_images"]] == expected_paths
    assert completion_order != expected_paths, (
        "uploads completed in input order — sleep scrambling did not exercise concurrency"
    )


@pytest.mark.unit
async def test_extract_node_checkpoints_new_additive_keys_when_present() -> None:
    """Story 2-0b: tables_detected/docling_pages from the new subprocess JSON
    shape are plumbed into the extract checkpoint (additive — old shape has
    neither, covered by test_extract_node_writes_checkpoint)."""
    from app.modules.content.pipeline.graph import extract_node

    state = _base_state()
    sb = _make_supabase_mock(node_outputs={})
    exec_mock = _make_subprocess_mock(
        stdout=_stdout_with_images([], tables_detected=2, docling_pages=[4, 5, 6])
    )

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", exec_mock),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        await extract_node(state)

    jobs_mock = sb.table("lesson_jobs")
    payload = jobs_mock.update.call_args_list[0].args[0]
    cache = payload["node_outputs"]["extract"]
    assert cache["tables_detected"] == 2
    assert cache["docling_pages"] == [4, 5, 6]
    # Existing contract keys untouched.
    assert set(cache) >= {"raw_text", "extracted_images", "page_count", "font_blocks"}


@pytest.mark.unit
async def test_extract_node_old_subprocess_json_shape_still_checkpoints() -> None:
    """Old-shape subprocess JSON (no tables_detected/docling_pages) must keep
    working — the subprocess change lands in a concurrent lane."""
    from app.modules.content.pipeline.graph import extract_node

    state = _base_state()
    sb = _make_supabase_mock(node_outputs={})
    exec_mock = _make_subprocess_mock()  # canned SUBPROCESS_STDOUT lacks new keys

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", exec_mock),
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        result = await extract_node(state)

    assert result["raw_text"] == "Chapter 1: Introduction\n\nThis is the text."
    jobs_mock = sb.table("lesson_jobs")
    cache = jobs_mock.update.call_args_list[0].args[0]["node_outputs"]["extract"]
    assert "tables_detected" not in cache
    assert "docling_pages" not in cache


@pytest.mark.unit
async def test_extract_node_subprocess_timeout_raises() -> None:
    """extract_node raises RuntimeError and reaps the child when the dynamic
    (settings-driven) timeout fires — cleanup now lives in try/finally (AC-5)."""
    import sys as _sys

    from app.modules.content.pipeline.graph import extract_node

    state = _base_state()
    sb = _make_supabase_mock(node_outputs={})

    timeout_proc = MagicMock()
    timeout_proc.returncode = None
    timeout_proc.pid = 4242
    timeout_proc.kill = MagicMock()
    # Plain MagicMock (not AsyncMock) — wait_for is patched to raise before awaiting communicate().
    timeout_proc.communicate = MagicMock()
    # wait() IS awaited (in finally, after the kill) so it must be an AsyncMock.
    timeout_proc.wait = AsyncMock(return_value=None)
    timeout_exec_mock = AsyncMock(return_value=timeout_proc)

    async def _raise_timeout(coro: object, timeout: float) -> tuple[bytes, bytes]:
        raise TimeoutError

    with (
        patch("app.core.db.get_supabase", return_value=sb),
        patch("app.config.get_settings") as mock_settings,
        patch("asyncio.create_subprocess_exec", timeout_exec_mock),
        patch("asyncio.wait_for", side_effect=_raise_timeout),
        # create=True: os.getpgid/os.killpg do not exist on Windows — without it
        # patch() raises AttributeError on the dev platform (win32).
        patch("os.getpgid", return_value=4242, create=True),
        patch("os.killpg", create=True) as mock_killpg,
        patch("app.modules.content.pipeline.graph._update_job_progress", new_callable=AsyncMock),
    ):
        _configure_settings(mock_settings)
        with pytest.raises(RuntimeError, match="PDF extraction timed out after"):
            await extract_node(state)

    # Child reaped: process-group SIGKILL on posix, proc.kill() on Windows.
    if _sys.platform != "win32":
        mock_killpg.assert_called_once()
        timeout_proc.kill.assert_not_called()
    else:
        timeout_proc.kill.assert_called_once()
    timeout_proc.wait.assert_awaited_once()


@pytest.mark.unit
async def test_extract_node_spawns_child_in_new_session_on_posix() -> None:
    """AC-5: on posix the subprocess is spawned with start_new_session=True so
    a single killpg can reap the whole process group (tesseract/docling children)."""
    import sys as _sys

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
        _configure_settings(mock_settings)
        await extract_node(state)

    exec_mock.assert_awaited_once()
    spawn_kwargs = exec_mock.await_args.kwargs
    if _sys.platform != "win32":
        assert spawn_kwargs.get("start_new_session") is True
    else:
        assert "start_new_session" not in spawn_kwargs
