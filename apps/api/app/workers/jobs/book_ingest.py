"""
ARQ job: book_ingest_job

Detects a book's chapters at upload time and writes one row per chapter.

This is Phase A of the spec (CLAUDE.md §9) — "upload a book once, ~2-5 min" —
finally doing what it always said. It deliberately does NOT use the LangGraph
content pipeline: chapter detection needs no LLM, no image rendering, no table
scanning and no embeddings, so running it through the graph would pay the whole
generation cost to read a table of contents.

Budget (measured in Phase 1, docs/reports/PHASE-1-TOC-SPIKE.md):
    get_toc()             0.03-1.76 s
    text-only page sweep  2.8-7.9 ms/page  ->  5.53 s at 1,671 pages
    detection             pure string work, negligible
    total target          <= 15 s for a 1,000-page book

Celery is BANNED per PRD §24 — this job uses ARQ exclusively.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SUBPROCESS_MODULE = "app.modules.content.pipeline.nodes.extract_subprocess"
_SOURCE_BUCKET = "source-pdfs"
_EXTRACT_TIMEOUT_S = 900


class BookIngestError(RuntimeError):
    """Raised when a book cannot be ingested. Carries the reason to books.status."""


async def _extract_text_only(pdf_bytes: bytes) -> dict[str, Any]:
    """Run the text-only extractor in an ISOLATED SUBPROCESS.

    CLAUDE.md §18: user-uploaded PDFs are parsed in a subprocess, never in the
    worker process. That applies to `get_toc()` too, which is why the outline is
    read out here rather than in this module.
    """
    with tempfile.TemporaryDirectory(prefix="book-ingest-") as tmp:
        pdf_path = Path(tmp) / "source.pdf"
        pdf_path.write_bytes(pdf_bytes)

        proc = await asyncio.create_subprocess_exec(  # noqa: S603
            sys.executable,
            "-m",
            _SUBPROCESS_MODULE,
            "--text-only",
            str(pdf_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_EXTRACT_TIMEOUT_S)
        finally:
            # Reap on EVERY exit path — success, timeout and ARQ cancellation.
            # An except-TimeoutError block never runs on CancelledError, which is
            # how 4 GB tesseract orphans survived in Story 2-0.
            if proc.returncode is None:
                proc.kill()
                await proc.wait()

        if proc.returncode != 0:
            tail = (stderr or b"").decode("utf-8", "replace")[-2000:]
            raise BookIngestError(f"text extraction failed (exit {proc.returncode}): {tail}")
        try:
            parsed: dict[str, Any] = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise BookIngestError("text extraction returned unparseable output") from exc
        return parsed


def _rows_for(book_id: str, chapters: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "book_id": book_id,
            "lesson_id": None,  # Phase 2 made this nullable — the whole point
            "title": c.title[:500],
            "page_start": c.page_start,
            "page_end": c.page_end,
            "chapter_index": c.chapter_index,
            "boundary_confidence": c.boundary_confidence,
        }
        for c in chapters
    ]


async def book_ingest_job(ctx: dict[str, Any], book_id: str) -> dict[str, Any]:
    """Detect and store the chapters of *book_id*.

    Lifecycle
    ---------
    1. Read the books row, download the source PDF from Storage
    2. Extract per-page text + outline in an isolated subprocess
    3. Run the detection ladder (pure, no I/O)
    4. Upsert one chapter row per detected chapter
    5. books.status -> 'ready'; on any failure -> 'failed', then re-raise

    Idempotency
    -----------
    `WorkerSettings` sets ``retry_jobs=True`` and ``max_tries=3``, and Phase 2
    added ``UNIQUE (book_id, chapter_index)``. A retry that re-inserted would hit
    23505 and strand the book permanently — the exact regression the Phase 2
    review caught in `chunk_node`. So the write is an upsert on that conflict
    target, and stale rows beyond the new chapter count are removed.

    Args:
        ctx:     ARQ worker context (redis, settings).
        book_id: UUID string of the book to ingest.

    Returns:
        ``{"book_id", "chapters", "boundary_confidence", "page_count"}``.

    Raises:
        BookIngestError: the book could not be ingested. `books.status` is set to
            'failed' before this propagates, so the state is visible even after
            ARQ exhausts its retries.
    """
    from app.core.db import get_supabase, rows, single_row
    from app.modules.content.chapter_detection import detect_chapters

    logger.info("book_ingest_job START book_id=%s", book_id)
    supabase = get_supabase()

    try:
        book_resp = (
            supabase.table("books")
            .select("book_id, filename, user_id")
            .eq("book_id", book_id)
            .single()
            .execute()
        )
        book = single_row(book_resp)
        if not book:
            raise BookIngestError(f"no books row for book_id={book_id}")

        storage_path = f"{book['user_id']}/{book_id}.pdf"
        try:
            pdf_bytes = supabase.storage.from_(_SOURCE_BUCKET).download(storage_path)
        except Exception as exc:
            raise BookIngestError(f"could not download {storage_path}") from exc

        extracted = await _extract_text_only(pdf_bytes)

        result = detect_chapters(
            page_count=int(extracted["page_count"]),
            toc=extracted["toc"],
            page_texts=extracted["page_texts"],
            fallback_title=str(book.get("filename") or "Full document"),
        )
        if not result.chapters:
            raise BookIngestError("detection produced no chapters")

        payload = _rows_for(book_id, result.chapters)
        supabase.table("chapters").upsert(payload, on_conflict="book_id,chapter_index").execute()

        # A re-run over a book that previously detected MORE chapters would leave
        # the surplus rows behind, silently inflating the chapter list. Upsert
        # cannot express that, so trim explicitly.
        stale = (
            supabase.table("chapters")
            .delete()
            .eq("book_id", book_id)
            .gte("chapter_index", len(payload))
            .execute()
        )
        removed = len(rows(stale))

        supabase.table("books").update(
            {"status": "ready", "page_count": int(extracted["page_count"])}
        ).eq("book_id", book_id).execute()

        logger.info(
            "book_ingest_job DONE book_id=%s chapters=%d rung=%s pages=%d stale_removed=%d",
            book_id,
            len(payload),
            result.rung,
            extracted["page_count"],
            removed,
        )
        return {
            "book_id": book_id,
            "chapters": len(payload),
            "boundary_confidence": result.rung,
            "page_count": int(extracted["page_count"]),
        }

    except Exception as exc:
        logger.exception("book_ingest_job FAILED book_id=%s", book_id)
        # Mark failed before re-raising: ARQ retries, and after the last attempt
        # nothing else would record the outcome. 'failed' was previously written
        # nowhere in the codebase, so a stuck book looked identical to a slow one.
        try:
            supabase.table("books").update({"status": "failed"}).eq("book_id", book_id).execute()
        except Exception:  # noqa: BLE001 — never mask the original failure
            logger.exception("book_ingest_job could not mark book %s failed", book_id)
        raise BookIngestError(str(exc)) from exc
