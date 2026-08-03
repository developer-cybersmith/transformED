"""book_ingest_job — Story 1-10 T5 (book-scale Phase 3).

The job itself is thin: download, extract in a subprocess, run the pure detection
ladder, write rows, set status. What these tests protect is the part that is not
obvious — the retry behaviour, the status transitions, and the promise that this
path costs nothing an LLM or a renderer would charge for.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.content.chapter_detection.types import DetectedChapter

BOOK_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
STORAGE_PATH = f"uuuuuuuu-uuuu-uuuu-uuuu-uuuuuuuuuuuu/{BOOK_ID}/book.pdf"
USER_ID = "uuuuuuuu-uuuu-uuuu-uuuu-uuuuuuuuuuuu"


class FakeTable:
    """Records what the job asked the database to do."""

    def __init__(self, name: str, store: dict[str, Any]) -> None:
        self.name, self.store = name, store
        self.store.setdefault(name, {"upserts": [], "updates": [], "deletes": []})

    def select(self, *_a: Any, **_k: Any) -> FakeTable:
        return self

    def eq(self, *_a: Any, **_k: Any) -> FakeTable:
        return self

    def gte(self, col: str, value: Any) -> FakeTable:
        self.store[self.name]["deletes"].append({col: value})
        return self

    def single(self) -> FakeTable:
        return self

    def upsert(self, payload: Any, **kwargs: Any) -> FakeTable:
        self.store[self.name]["upserts"].append({"payload": payload, "kwargs": kwargs})
        return self

    def update(self, payload: Any) -> FakeTable:
        self.store[self.name]["updates"].append(payload)
        return self

    def delete(self) -> FakeTable:
        return self

    def execute(self) -> Any:
        if self.name == "books" and not self.store[self.name]["updates"]:
            return MagicMock(data={"book_id": BOOK_ID, "filename": "b.pdf", "user_id": USER_ID})
        return MagicMock(data=[])


def make_supabase(store: dict[str, Any]) -> MagicMock:
    sb = MagicMock()
    sb.table.side_effect = lambda name: FakeTable(name, store)
    sb.storage.from_.return_value.download.return_value = b"%PDF-1.7 fake"
    return sb


def extracted(page_count: int = 300) -> dict[str, Any]:
    return {"page_count": page_count, "page_texts": [""] * page_count, "toc": []}


def chapters(n: int) -> list[DetectedChapter]:
    return [DetectedChapter(f"Chapter {i}", i * 10, i * 10 + 9, i, "toc") for i in range(n)]


async def run_job(store: dict[str, Any], detected: list[DetectedChapter], **kw: Any) -> Any:
    from app.modules.content.chapter_detection.types import DetectionResult
    from app.workers.jobs.book_ingest import book_ingest_job

    with (
        patch("app.core.db.get_supabase", return_value=make_supabase(store)),
        patch(
            "app.workers.jobs.book_ingest._extract_text_only",
            new_callable=AsyncMock,
            return_value=kw.get("extract", extracted()),
        ),
        patch(
            "app.modules.content.chapter_detection.detect_chapters",
            return_value=DetectionResult(
                chapters=detected, rung=kw.get("rung", "toc"), raw_chapters=detected
            ),
        ),
    ):
        return await book_ingest_job({}, BOOK_ID, STORAGE_PATH)


@pytest.mark.unit
def test_job_is_registered_with_the_arq_worker() -> None:
    """AC11 — an unregistered job is enqueued and never runs."""
    from app.workers.main import WorkerSettings

    assert "book_ingest_job" in [f.__name__ for f in WorkerSettings.functions]


@pytest.mark.unit
async def test_writes_one_row_per_chapter_with_null_lesson_id() -> None:
    """AC12, and the Phase 2 capability being used for the first time: chapters
    that belong to a book, with no lesson."""
    store: dict[str, Any] = {}
    out = await run_job(store, chapters(27))

    payload = store["chapters"]["upserts"][0]["payload"]
    assert len(payload) == 27
    assert all(r["lesson_id"] is None for r in payload)
    assert [r["chapter_index"] for r in payload] == list(range(27))
    assert all(r["boundary_confidence"] == "toc" for r in payload)
    assert out["chapters"] == 27


@pytest.mark.unit
async def test_chapter_write_is_retry_safe() -> None:
    """AC19 — mandatory, not optional.

    WorkerSettings sets retry_jobs=True / max_tries=3, and Phase 2 added
    UNIQUE (book_id, chapter_index). A plain insert would raise 23505 on the
    second attempt and strand the book on every remaining try — the exact defect
    the Phase 2 review found in chunk_node.

    # MOCK-CONTRACT: asserts the call shape. That Postgres actually accepts this
    # conflict target is proven against a real database by
    # tests/integration/test_migration_chapters_book_scoped.py::
    # test_unique_constraint_supports_the_pipelines_upsert_conflict_target
    """
    store: dict[str, Any] = {}
    await run_job(store, chapters(5))

    call = store["chapters"]["upserts"][0]
    assert call["kwargs"].get("on_conflict") == "book_id,chapter_index", (
        "the chapter write must target the UNIQUE constraint, or an ARQ retry "
        "permanently fails the book"
    )


@pytest.mark.unit
async def test_a_rerun_that_finds_fewer_chapters_removes_the_surplus() -> None:
    """Upsert alone cannot shrink a chapter list. Without the trim, a book that
    once detected 27 chapters and now detects 8 keeps 19 stale rows that no longer
    correspond to anything in the PDF."""
    store: dict[str, Any] = {}
    await run_job(store, chapters(8))
    assert store["chapters"]["deletes"] == [{"chapter_index": 8}]


@pytest.mark.unit
async def test_marks_the_book_ready_and_records_its_page_count() -> None:
    store: dict[str, Any] = {}
    await run_job(store, chapters(3), extract=extracted(1151))
    update = store["books"]["updates"][-1]
    assert update["status"] == "ready"
    assert update["page_count"] == 1151


@pytest.mark.unit
async def test_marks_the_book_failed_when_extraction_fails() -> None:
    """AC18/AC13. 'failed' was previously written nowhere in the codebase, so a
    stuck book was indistinguishable from a slow one."""
    from app.workers.jobs.book_ingest import BookIngestError, book_ingest_job

    store: dict[str, Any] = {}
    with (
        patch("app.core.db.get_supabase", return_value=make_supabase(store)),
        patch(
            "app.workers.jobs.book_ingest._extract_text_only",
            new_callable=AsyncMock,
            side_effect=RuntimeError("corrupt pdf"),
        ),
        pytest.raises(BookIngestError),
    ):
        await book_ingest_job({}, BOOK_ID, STORAGE_PATH)

    assert {"status": "failed"} in store["books"]["updates"]


@pytest.mark.unit
async def test_failure_is_reraised_so_arq_can_retry() -> None:
    """Marking failed must not swallow the error — ARQ decides about retries."""
    from app.workers.jobs.book_ingest import BookIngestError, book_ingest_job

    store: dict[str, Any] = {}
    with (
        patch("app.core.db.get_supabase", return_value=make_supabase(store)),
        patch(
            "app.workers.jobs.book_ingest._extract_text_only",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(BookIngestError),
    ):
        await book_ingest_job({}, BOOK_ID, STORAGE_PATH)


def _executable_source(path: str) -> str:
    """Source with docstrings and comments removed.

    A plain substring scan over the raw file matches the prose that EXPLAINS what
    the code avoids — this module's own docstring says "no image rendering", which
    made the scan fail on the word it was looking for. Scanning what actually
    executes is the assertion that was meant.
    """
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            body.pop(0)
    return ast.unparse(tree)  # unparse drops comments


@pytest.mark.unit
def test_the_job_uses_no_langgraph_no_llm_and_no_renderer() -> None:
    """AC11 asserted rather than assumed. This is the cost promise: detection runs
    for the price of a text sweep, not a generation pipeline."""
    code = _executable_source("app/workers/jobs/book_ingest.py")
    for forbidden in (
        "run_pipeline",
        "StateGraph",
        "langgraph",
        "get_llm",
        "openai",
        "render",
        "pdfplumber",
        "docling",
        "embed",
    ):
        assert forbidden not in code, f"{forbidden!r} is executed in the book-ingest path"


@pytest.mark.unit
def test_pdf_parsing_happens_in_a_subprocess() -> None:
    """CLAUDE.md §18. The job must never open the PDF in the worker process —
    including get_toc(), which parses the document just as much as text does."""
    code = _executable_source("app/workers/jobs/book_ingest.py")
    assert "create_subprocess_exec" in code
    assert "--text-only" in code
    assert "pdfium" not in code, "the job opened the PDF itself instead of delegating"
