"""
Content module router.

Handles PDF upload → lesson pipeline dispatch and lesson status/retrieval.
"""

from __future__ import annotations

import contextlib
import copy
import logging
import math
import os
import re
import uuid
from typing import Any

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel

from app.core.db import get_supabase, rows, single_row
from app.core.rate_limit import _get_user_key, limiter
from app.core.storage import sign_storage_path
from app.dependencies import ArqRedis, CurrentUser

# Story 1-11: book/chapter read models live in this module, NOT packages/shared
# (frozen contract, 4-dev review — CLAUDE.md §16).
from app.modules.content.schemas import BookResponse, ChapterResponse

# S2-LM3 (Learner Mode, unblocked 2026-07-17 once S2-LM1's 4-dev sign-off was
# recorded): single source of truth for the tier default/valid set, shared
# with the pipeline graph (2026-07-17 review fix, Blind Hunter — a local copy
# here previously duplicated graph.py's, a DRY violation inviting drift).
from app.schemas.lesson import LessonPackage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["content"])

MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


# ── Response models ───────────────────────────────────────────────────────────


class BookUploadResponse(BaseModel):
    """Book-scale Phase 3: upload ingests a BOOK; lessons are generated per
    chapter afterwards. There is no lesson_id to return here any more."""

    book_id: str
    job_id: str
    status: str  # "queued"


class LessonStatusResponse(BaseModel):
    lesson_id: str
    status: str  # queued | running | ready | failed
    title: str | None = None
    error: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    # Story 2-31 AC-4: lifted from the content JSONB so dashboard/library cards
    # can show a real subject + duration without an N+1 round-trip per lesson.
    # Cheap scalars only — NOT the whole package (see `content` below).
    subject: str | None = None
    estimated_duration_mins: float | None = None
    # Story 1-6: populated by get_lesson ONLY (never list_lessons — resolving
    # every asset's signed URL for every row in a paginated list would be an
    # N-lessons x M-assets signing storm).
    content: LessonPackage | None = None


# Story 2-31 AC-5: URLs embedded in the lesson response are signed ONCE at fetch
# time and never refreshed — there is no client-side re-sign path today
# (AudioTimeline's retryAudio() re-mounts the same src rather than re-fetching).
# At the 1-hour default, a student who pauses a lesson and returns loses audio
# and images with no recovery. 8 hours covers a realistic study session with
# breaks, while staying well short of a durable link.
#
# This shortens the exposure window; it does not close it. The real fix is a
# re-sign path — deliberately deferred, since revision-mode video may supersede
# the whole question (docs/decisionupdate.md §7b) and the standalone
# GET /api/media/signed-url endpoint remains dormant pending that decision.
_EMBEDDED_MEDIA_EXPIRY_S: int = 8 * 60 * 60


# Story 2-31 AC-4: an explicit column list for list_lessons, replacing `select("*")`.
#
# `subject` and `estimated_duration_mins` are lifted out of the `content` JSONB
# with PostgREST path selectors (`->metadata->>field`) so the list response can
# show them WITHOUT pulling the whole package column for every row — the exact
# N-lessons x M-assets cost Story 1-6 AC-7 exists to prevent. `->>` yields text,
# so the duration is coerced back to float in `_row_to_status_response`.
#
# NOTE: the `content` column is deliberately absent here — list_lessons must
# never attach full content or resolve signed URLs (Story 1-6 AC-7).
#
# `completed_at` is deliberately ABSENT: it is a column on `lesson_jobs`, NOT on
# `lessons` (see supabase/migrations/20260611000000_initial_schema.sql — lessons
# has only lesson_id/user_id/title/status/content/source_file_path/created_at/
# updated_at, plus book_id and tier from later migrations). Under `select("*")`
# naming it was harmless — `lesson.get("completed_at")` simply returned None —
# but naming it EXPLICITLY makes PostgREST reject the whole query with
# `42703 column lessons.completed_at does not exist`, i.e. GET /lessons fails for
# every user on every request. `_row_to_status_response` still reads it via
# .get(), so the response field keeps its existing always-null behaviour.
_LIST_COLUMNS: str = (
    "lesson_id,status,title,created_at,"
    "subject:content->metadata->>subject,"
    "estimated_duration_mins:content->metadata->>estimated_duration_mins"
)


# Story 1-11 (book-scale Phase 3.5) — select lists for the book/chapter reads.
#
# EVERY name below is a real column, verified against supabase/migrations/:
#   books    — 20260625000000_chunks_inline_embedding.sql (book_id, user_id,
#              filename, page_count, status, created_at, updated_at)
#   chapters — 20260611000000_initial_schema.sql (chapter_id, book_id, lesson_id,
#              title, page_start, page_end, chapter_index, created_at)
#              + 20260803000000_chapters_book_scoped.sql (boundary_confidence)
# Naming a column that does not exist makes PostgREST reject the WHOLE query with
# `42703` — i.e. the endpoint fails for every user on every request. That is D9,
# and `_LIST_COLUMNS` above is the cautionary example, not a template.
# `tests/unit/test_book_endpoints.py` asserts these lists against the migration SQL.
#
# `user_id` is selected so ownership can be re-checked on the row exactly as
# `get_lesson` does, even though the query already filters on it. It is dropped
# before the response is built — BookResponse has no such field.
_BOOK_COLUMNS: str = "book_id,user_id,filename,status,page_count,created_at"

# `chapters(count)` is a PostgREST embedded aggregate over the
# chapters.book_id → books.book_id FK (chapters_book_id_fkey, 20260625000000).
# It makes chapter_count ONE query for the whole page rather than N+1 per book.
_BOOK_SELECT: str = f"{_BOOK_COLUMNS},chapters(count)"

_CHAPTER_COLUMNS: str = (
    "chapter_id,chapter_index,title,page_start,page_end,boundary_confidence,lesson_id"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

_STATUS_MAP: dict[str, str] = {
    "generating": "running",
    "ready": "ready",
    "failed": "failed",
}


def _map_status(db_status: str) -> str:
    return _STATUS_MAP.get(db_status, "queued")


def _row_to_status_response(
    lesson: dict[str, Any],
    error: str | None = None,
) -> LessonStatusResponse:
    return LessonStatusResponse(
        lesson_id=str(lesson["lesson_id"]),
        status=_map_status(lesson.get("status", "generating")),
        title=lesson.get("title"),
        error=error,
        created_at=str(lesson["created_at"]) if lesson.get("created_at") else None,
        completed_at=str(lesson["completed_at"]) if lesson.get("completed_at") else None,
        subject=_coerce_str(_metadata_field(lesson, "subject")),
        estimated_duration_mins=_coerce_float(_metadata_field(lesson, "estimated_duration_mins")),
    )


def _metadata_field(lesson: dict[str, Any], field: str) -> Any:  # noqa: ANN401
    """Read a LessonPackage.metadata field from either shape (Story 2-31 AC-4).

    `list_lessons` aliases the value via a PostgREST JSONB path selector, so it
    arrives as a flat top-level key. `get_lesson` selects `*`, so it arrives
    nested under `content.metadata`. Supporting both keeps the two endpoints
    consistent without making the list query pull the whole content column.
    """
    if lesson.get(field) is not None:
        return lesson[field]
    content = lesson.get("content")
    if isinstance(content, dict):
        metadata = content.get("metadata")
        if isinstance(metadata, dict):
            return metadata.get(field)
    return None


_MAX_SUBJECT_LEN = 200


def _coerce_str(value: Any) -> str | None:  # noqa: ANN401
    """Coerce an untrusted JSONB value to `str | None` for a typed response field.

    `content.metadata` is LLM-generated JSONB — the least trustworthy source in
    the system — and `get_lesson` reads it as a raw nested value (`select("*")`),
    so `subject` can be a dict, list, or number. Pydantic v2 does NOT coerce
    those into `str`, so handing one to `LessonStatusResponse` raises
    ValidationError. On the LIST path that 500s the ENTIRE page, not one card.
    Drop anything that is not already a string, and cap the length so one row
    cannot balloon a paginated response.
    """
    if not isinstance(value, str):
        return None
    return value[:_MAX_SUBJECT_LEN]


def _coerce_float(value: Any) -> float | None:  # noqa: ANN401
    """PostgREST `->>` returns text; the nested dict returns a real number.

    Rejects non-finite values: `float("NaN")`, `float("inf")` and `float("1e400")`
    all SUCCEED in Python, and a bare `NaN`/`Infinity` token in the response is
    invalid JSON that throws in the browser's `JSON.parse` — breaking the whole
    lesson list, not one card. `math.isfinite` is the guard `try/except` cannot be.
    """
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _embedded_count(value: Any) -> int:  # noqa: ANN401 — postgrest embed shape varies
    """Unwrap a PostgREST embedded aggregate into a plain int (Story 1-11).

    `chapters(count)` arrives as `[{"count": 21}]`; an empty relation can arrive
    as `[]`, and a to-one embed as `{"count": 0}`. A book with zero chapters is
    the NORMAL state while ingestion runs, so every one of those shapes must
    yield 0 rather than raising and 500-ing the whole book list.
    """
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("count")
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _row_to_book_response(book: dict[str, Any]) -> BookResponse:
    page_count = book.get("page_count")
    return BookResponse(
        book_id=str(book["book_id"]),
        filename=str(book.get("filename") or ""),
        status=str(book.get("status") or "processing"),
        page_count=int(page_count) if isinstance(page_count, int | float) else None,
        chapter_count=_embedded_count(book.get("chapters")),
        created_at=str(book["created_at"]) if book.get("created_at") else None,
    )


def _row_to_chapter_response(chapter: dict[str, Any]) -> ChapterResponse:
    # AC4: has_lesson is DERIVED from lesson_id, never stored, so it is already
    # correct the moment Phase 6 starts writing chapters.lesson_id.
    lesson_id = chapter.get("lesson_id")
    return ChapterResponse(
        chapter_id=str(chapter["chapter_id"]),
        chapter_index=int(chapter["chapter_index"]),
        title=str(chapter.get("title") or ""),
        page_start=int(chapter["page_start"]),
        page_end=int(chapter["page_end"]),
        boundary_confidence=str(chapter.get("boundary_confidence") or "fallback"),
        lesson_id=str(lesson_id) if lesson_id else None,
        has_lesson=bool(lesson_id),
    )


def _validated_book_id(book_id: str) -> str:
    """AC6: a malformed book_id is a 404, never a 500.

    Same guard and same convention as `get_lesson` (:429-433) — deliberately
    identical, because a different shape here would be a different security
    posture. The detail string carries no metadata (AC5).
    """
    try:
        uuid.UUID(book_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Book not found"
        ) from None
    return book_id


def _fetch_owned_book(
    supabase: Any,  # noqa: ANN401 — supabase Client
    book_id: str,
    user_id: str,
    columns: str,
) -> dict[str, Any]:
    """Fetch one book the caller owns, or raise 404.

    The Supabase client is SERVICE-ROLE (core/db.py:40-47) so RLS does NOT filter
    here — the `user_id` predicate is the only thing standing between this and an
    IDOR, and the post-fetch ownership check is the second line of defence that
    survives a refactor dropping the predicate.

    404, never 403 (AC5): a 403 confirms the id exists. The detail string is the
    same for "absent" and "someone else's", and carries no book metadata.
    """
    resp = (
        supabase.table("books")
        .select(columns)
        .eq("book_id", book_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    book: dict[str, Any] | None = single_row(resp)
    if not book or book.get("user_id") != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    return book


def _resolve_lesson_content(
    content: dict[str, Any],
    supabase: Any,  # noqa: ANN401
) -> LessonPackage:
    """Resolve every Narration.audio_url/Slide.image_url in a raw content
    dict (as stored in lessons.content JSONB) to a real signed URL.

    Degrades a single asset to its established "no media" fallback on a
    signing failure ("" for audio_url — required non-optional str;
    None for image_url — optional) rather than failing the whole lesson.
    fallback_image_url is never touched — the pipeline never sets it to
    anything but None (Story 1-6 Dev Notes).

    Trusted internal data (our own package_builder wrote it) — a
    LessonPackage.model_validate failure after resolution indicates real
    corruption and is allowed to raise, not silently swallowed.

    Pure function — does not mutate the `content` dict passed in.
    """
    content = copy.deepcopy(content)
    for segment in content.get("segments") or []:
        narration = segment.get("narration") or {}
        audio_path = narration.get("audio_url")
        if audio_path:
            narration["audio_url"] = (
                sign_storage_path(supabase, "lesson-audio", audio_path, _EMBEDDED_MEDIA_EXPIRY_S)
                or ""
            )
        for slide in segment.get("slides") or []:
            image_path = slide.get("image_url")
            if image_path:
                slide["image_url"] = sign_storage_path(
                    supabase, "lesson-images", image_path, _EMBEDDED_MEDIA_EXPIRY_S
                )
    return LessonPackage.model_validate(content)


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post(
    "/lessons",
    response_model=BookUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a book PDF and enqueue chapter detection",
)
@limiter.limit("5/minute", key_func=_get_user_key)
async def upload_lesson(
    request: Request,
    response: Response,
    current_user: CurrentUser,
    arq_redis: ArqRedis,
    file: UploadFile = File(..., description="PDF file to process (max 50 MB)"),  # noqa: B008
    tier: str | None = Form(  # noqa: B008
        None,
        description=(
            "REMOVED in book-scale Phase 3. Tier is chosen per chapter when a lesson "
            "is generated, not per upload. Supplying it here returns 422."
        ),
    ),
) -> BookUploadResponse:
    """Accept a book PDF, store it, and enqueue chapter detection.

    INGESTION ONLY (book-scale Phase 3, Story 1-10). This creates the `books` row
    and enqueues `book_ingest_job`; it no longer creates a `lessons` row and no
    longer enqueues the generation pipeline. A book is uploaded once; lessons are
    generated per chapter afterwards (CLAUDE.md §9 Phase A / Phase B).

    BREAKING, deliberately (decision D-A): between this change and Phase 6 there is
    no endpoint that generates a lesson, and clients reading `lesson_id` off this
    response will break — `apps/web` Story 1-8 does exactly that. Accepted because
    there are no users yet; tracked in the defect register with the trigger
    "Phase 6 lands".

    Returns immediately with book_id + job_id. Detection is fast — Phase 1
    measured <= 15 s for a 1,000-page book — so the client polls the book rather
    than waiting.
    """
    user_id: str = current_user["sub"]
    supabase = get_supabase()

    # ── tier is no longer accepted here (decision D-B, Story 1-10) ───────────
    # Upload creates no lesson, so there is nothing for a tier to apply to. It is
    # chosen per chapter at generation time instead. Rejecting loudly rather than
    # ignoring it: a silent drop is how a caller keeps sending T3 and keeps
    # getting T2, with nothing anywhere to show why.
    if tier is not None:
        raise HTTPException(
            status_code=422,
            detail=(
                "tier is no longer accepted on upload — a book has no tier. Choose it "
                "per chapter when generating a lesson "
                "(POST /books/{book_id}/chapters/{chapter_id}/lessons)."
            ),
        )

    # ── Size check (fast path before reading body) ────────────────────────────
    if file.size and file.size > MAX_PDF_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")

    # ── Magic bytes: first 4 bytes must be %PDF ───────────────────────────────
    first_bytes = await file.read(4)
    await file.seek(0)
    if first_bytes != b"%PDF":
        raise HTTPException(status_code=422, detail="File is not a valid PDF")

    # ── MIME type check ───────────────────────────────────────────────────────
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=422, detail="Invalid content type — expected application/pdf"
        )

    # ── Read full body with streaming size guard (enforces limit even without Content-Length) ──
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        chunk = await file.read(1024 * 1024)  # 1 MB per iteration
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > MAX_PDF_SIZE_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")
        chunks.append(chunk)
    pdf_bytes = b"".join(chunks)

    safe_filename = re.sub(
        r"[^a-zA-Z0-9._\-]", "_", os.path.basename(file.filename or "upload.pdf")
    )

    book_id: str | None = None
    storage_path: str | None = None

    try:
        # ── 1. books row ──────────────────────────────────────────────────────
        books_resp = (
            supabase.table("books")
            .insert(
                {
                    "user_id": user_id,
                    "filename": safe_filename,
                }
            )
            .execute()
        )
        books_rows = rows(books_resp)
        if not books_rows:
            raise RuntimeError("books insert returned no rows")
        book_id = books_rows[0]["book_id"]

        # ── 2. Storage upload ─────────────────────────────────────────────────
        storage_path = f"{user_id}/{book_id}/{safe_filename}"
        supabase.storage.from_("source-pdfs").upload(
            path=storage_path,
            file=pdf_bytes,
            file_options={"content-type": "application/pdf"},
        )

        # ── 3. Enqueue chapter detection ──────────────────────────────────────
        # `storage_path` is passed rather than derived in the job: the layout is
        # this router's business and `books` has no column for it, so rebuilding
        # it there would be a second source of truth.
        #
        # _job_id dedupes per BOOK now, not per lesson. Re-uploading the same
        # book while its detection is still queued is a duplicate request, not a
        # second book — and book_ingest_job is idempotent anyway (it upserts on
        # (book_id, chapter_index)), so a redelivered job is harmless.
        job = await arq_redis.enqueue_job(
            "book_ingest_job", book_id, storage_path, _job_id=f"book_ingest:{book_id}"
        )
        if job is None:
            # ARQ deduplicated the key — no job will run, so nothing would ever
            # move this book out of 'processing'. Clean up and say so. Each delete
            # is isolated so a transient failure on one does not abandon the rest.
            logger.warning("ARQ deduped book_ingest job for book_id=%s", book_id)
            if storage_path:
                with contextlib.suppress(Exception):
                    supabase.storage.from_("source-pdfs").remove([storage_path])
            with contextlib.suppress(Exception):
                supabase.table("books").delete().eq("book_id", book_id).execute()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This book is already being ingested",
            )
        job_id: str = job.job_id

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("upload_lesson failed for user_id=%s filename=%s", user_id, safe_filename)
        # P4: hard-delete all created rows in FK order so the user gets a clean slate on retry.
        # (marking as "failed" leaves orphaned books rows on subsequent retry attempts)
        if storage_path:
            with contextlib.suppress(Exception):
                supabase.storage.from_("source-pdfs").remove([storage_path])
        if book_id:
            with contextlib.suppress(Exception):
                supabase.table("books").delete().eq("book_id", book_id).execute()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to ingest book — please retry",
        ) from exc

    return BookUploadResponse(book_id=book_id, job_id=job_id, status="queued")


@router.get(
    "/lessons/{lesson_id}",
    response_model=LessonStatusResponse,
    summary="Get the status and metadata of a lesson",
)
async def get_lesson(
    lesson_id: str,
    current_user: CurrentUser,
) -> LessonStatusResponse:
    """Return current status of a lesson.

    Returns 404 if not found or user does not own the lesson.
    """
    try:
        uuid.UUID(lesson_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found"
        ) from None
    user_id: str = current_user["sub"]
    supabase = get_supabase()

    lesson_resp = (
        supabase.table("lessons").select("*").eq("lesson_id", lesson_id).maybe_single().execute()
    )
    lesson: dict[str, Any] | None = single_row(lesson_resp)

    if not lesson or lesson.get("user_id") != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found")

    # Fetch error from lesson_jobs if present
    error: str | None = None
    if lesson.get("status") == "failed":
        jobs_resp = (
            supabase.table("lesson_jobs")
            .select("error")
            .eq("lesson_id", lesson_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        jobs_rows = rows(jobs_resp)
        if jobs_rows:
            error = jobs_rows[0].get("error")

    resp = _row_to_status_response(lesson, error=error)
    if lesson.get("status") == "ready" and lesson.get("content"):
        resp.content = _resolve_lesson_content(lesson["content"], supabase)
    return resp


@router.get(
    "/lessons",
    response_model=list[LessonStatusResponse],
    summary="List all lessons for the current user",
)
async def list_lessons(
    current_user: CurrentUser,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[LessonStatusResponse]:
    """Return paginated lessons for the authenticated user, newest first."""
    user_id: str = current_user["sub"]
    supabase = get_supabase()

    resp = (
        supabase.table("lessons")
        .select(_LIST_COLUMNS)
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    lesson_rows = rows(resp)
    return [_row_to_status_response(row) for row in lesson_rows]


# ── Books & chapters (Story 1-11, book-scale Phase 3.5) ───────────────────────
#
# `chapters` had three writes and zero SELECTs before this: Phase 3 wrote 21
# correct rows for a 1,151-page book and no API could see any of them.


@router.get(
    "/books",
    response_model=list[BookResponse],
    summary="List the caller's uploaded books, newest first",
)
async def list_books(
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[BookResponse]:
    """Return the caller's books, newest first, with a real chapter count.

    `chapter_count` comes from a PostgREST embedded aggregate on the same query
    (`chapters(count)`) — one round-trip for the whole page, not one per book.
    """
    user_id: str = current_user["sub"]
    supabase = get_supabase()

    resp = (
        supabase.table("books")
        .select(_BOOK_SELECT)
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return [_row_to_book_response(row) for row in rows(resp)]


@router.get(
    "/books/{book_id}",
    response_model=BookResponse,
    summary="Get one book (upload progress is polled here)",
)
async def get_book(
    book_id: str,
    current_user: CurrentUser,
) -> BookResponse:
    """Return one book in exactly the same shape as `GET /books`.

    This is what the upload flow polls after `POST /lessons` returns a book_id:
    `status` goes processing → ready|failed, and `chapter_count` becomes non-zero
    when `book_ingest_job` has written the chapter rows.

    404 — not 403 — when the book belongs to another user or does not exist.
    """
    user_id: str = current_user["sub"]
    supabase = get_supabase()
    book = _fetch_owned_book(supabase, _validated_book_id(book_id), user_id, _BOOK_SELECT)
    return _row_to_book_response(book)


@router.get(
    "/books/{book_id}/chapters",
    response_model=list[ChapterResponse],
    summary="List a book's detected chapters, ordered by chapter_index",
)
async def list_book_chapters(
    book_id: str,
    current_user: CurrentUser,
) -> list[ChapterResponse]:
    """Return the book's chapters ordered by `chapter_index`.

    Ownership is resolved on `books` first: `chapters` has no user_id of its own
    (its RLS re-roots through books.user_id — 20260803000000 step 5), and with a
    service-role client there is no RLS to fall back on, so an unchecked
    `chapters.eq(book_id)` would be a straight IDOR.

    `lesson_id`/`has_lesson` are always null/false until Phase 6 (AC4).
    """
    user_id: str = current_user["sub"]
    supabase = get_supabase()
    validated_id = _validated_book_id(book_id)
    _fetch_owned_book(supabase, validated_id, user_id, "book_id,user_id")

    resp = (
        supabase.table("chapters")
        .select(_CHAPTER_COLUMNS)
        .eq("book_id", validated_id)
        .order("chapter_index")
        .execute()
    )
    return [_row_to_chapter_response(row) for row in rows(resp)]
