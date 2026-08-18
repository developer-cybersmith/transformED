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
from datetime import UTC, datetime, timedelta
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

from app.config import get_settings
from app.core.db import get_supabase, rows, single_row
from app.core.rate_limit import _get_user_key, limiter
from app.core.storage import sign_storage_path
from app.dependencies import ApprovedUser, ArqRedis, CurrentUser

# Story 1-11: book/chapter read models live in this module, NOT packages/shared
# (frozen contract, 4-dev review — CLAUDE.md §16).
from app.modules.content.schemas import (
    BookResponse,
    ChapterResponse,
    GenerateLessonRequest,
    LatestLesson,
    LessonGenerationResponse,
)

# S2-LM3 (Learner Mode, unblocked 2026-07-17 once S2-LM1's 4-dev sign-off was
# recorded): single source of truth for the tier default/valid set, shared
# with the pipeline graph (2026-07-17 review fix, Blind Hunter — a local copy
# here previously duplicated graph.py's, a DRY violation inviting drift).
from app.schemas.lesson import LessonPackage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["content"])

MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

# Story 1-14 (book-scale Phase 6) — the one path that turns a detected chapter
# into a lesson. Declared as a constant because it is consumed TWICE: by the
# route decorator below, and by `upload_lesson`'s 422 detail, which tells a
# caller who supplied `tier` on upload where tier now belongs. Two hand-typed
# copies would drift the moment the route moves, and the drifted one is the copy
# the client reads.
GENERATE_LESSON_PATH: str = "/books/{book_id}/chapters/{chapter_id}/lessons"

# Story 1-14 AC11 — the TRUNCATION warn threshold, deliberately a different
# number from `settings.max_chapter_pages` (200) because the two gate different
# failures.
#
# `structure_max_sections` (15) x `_get_section_body(max_chars=6000)` means
# ~90,000 characters is the entire LLM-visible window REGARDLESS of page count.
# At the 2,296-2,816 chars/page measured across the Phase 1 corpus that is
# 32-39 pages. Above ~40 pages the lesson is genuinely built from only part of
# the chapter — cheap and wrong rather than expensive, so the $3.00 cost ceiling
# never fires and cannot protect us here. That is a QUALITY problem the caller
# deserves to be told about (`truncation_expected: true`), not a reason to
# refuse the request: the largest real chapter in the corpus is 138 pages.
#
# `max_chapter_pages` is the CATASTROPHE gate — it refuses a rung-5
# whole-document "chapter" of 1,151 pages. See config.py for why it is 200.
_TRUNCATION_WARN_PAGES: int = 40

# Retry-After (seconds) on the AC12 concurrency 429. A pipeline run is minutes,
# not seconds, so a short retry would just burn the client's rate-limit budget.
_CONCURRENCY_RETRY_AFTER_S: int = 60

# Story 2-47 (S4-06): safety ceiling on ChapterResponse.lessons, NOT a derived
# natural bound -- the realistic range is 1-3 (one per tier; the UI has no path
# to `force=true` regeneration), but D54's idempotency check only blocks a
# retry while an existing (chapter_id, tier) lesson is generating/ready, so a
# repeatedly-failing tier can accumulate one row per retry with no hard cap
# found anywhere in this flow. The underlying `_CHAPTER_COLUMNS` embed itself
# has no query-level `.limit()` either -- D115, pre-existing, not fixed here.
# (This was mis-cited as D59 in the original story draft; D59 covers
# admin/router.py and analytics/service.py only, never this file -- corrected
# 2026-08-17 by the story's own /bmad-code-review.) This cap is applied in
# Python after the fetch so this story does not make that gap worse by
# shipping an unbounded list to the client. `lesson_count` is computed from
# the UNCAPPED list and still reports the true total past this cap.
# BOUNDED: output capped at 20 entries here in Python (post-fetch slice); the
# underlying query itself is still unbounded -- see D115 above.
_MAX_LESSONS_EXPOSED: int = 20


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
    # Story 1-14 (book-scale Phase 6): which chapter this lesson was generated
    # from. All three are nullable and legitimately null for every lesson created
    # before Phase 6 — `lessons.chapter_id` is a nullable column added by
    # 20260803000000, and the PostgREST embed returns `null` for those rows.
    # A client must therefore treat "no chapter" as a normal case, not an error.
    chapter_id: str | None = None
    chapter_title: str | None = None
    chapter_index: int | None = None
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
# Story 1-14 adds `chapter_id` (a real column since 20260803000000:73) and a
# to-ONE embed back to `chapters`. The FK qualifier is mandatory and is NOT
# ceremony: TWO foreign keys exist between `lessons` and `chapters`
# (`chapters_lesson_id_fkey`, the dead scalar, and `lessons_chapter_id_fkey`,
# the live one), so a bare `chapters(...)` embed is rejected with PGRST201 —
# which PostgREST returns as HTTP 300, not a 4xx, so a naive `>= 400` check
# reads the failure as success. Naming the wrong one resolves through the dead
# column and returns a permanently-null chapter: green tests, dead feature.
#
# This side of `lessons_chapter_id_fkey` is to-ONE, so it arrives as a JSON
# OBJECT (or `null`), unlike `_CHAPTER_COLUMNS` below which names the SAME
# constraint from the other side and gets an ARRAY.
_LIST_COLUMNS: str = (
    "lesson_id,status,title,created_at,chapter_id,"
    "subject:content->metadata->>subject,"
    "estimated_duration_mins:content->metadata->>estimated_duration_mins,"
    "chapter:chapters!lessons_chapter_id_fkey(chapter_id,title,chapter_index)"
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

# Story 1-14 (Phase 6): the lesson link is re-sourced from `lessons`.
#
# The scalar `chapters.lesson_id` is GONE from this list — dropped outright, not
# kept as a "harmless fallback". It is a dead column with a live
# `ON DELETE CASCADE` to `lessons` (20260611000000:132), and `chunks.chapter_id`
# cascades from the chapter (:147), so pointing it at a lesson and later rolling
# that lesson back would delete the chapter and every chunk and embedding under
# it. It is also scalar, and one chapter can legitimately have lessons at three
# tiers. Nothing in `app/modules/content/` reads or writes it.
#
# `lessons!lessons_chapter_id_fkey` is the SAME constraint `_LIST_COLUMNS` names,
# viewed from the other side: to-MANY, so it arrives as a JSON ARRAY and is `[]`
# for the normal case of a chapter with no lessons yet. `_row_to_chapter_response`
# unwraps it defensively — a bare `[0]` would 500 the entire chapter list for any
# book mid-ingestion.
#
# The embed carries NO user predicate of its own — a select list cannot express
# one. `list_book_chapters` adds `.eq("lessons.user_id", ...)` to the query
# instead; see the note there for why that is not redundant.
_CHAPTER_COLUMNS: str = (
    "chapter_id,chapter_index,title,page_start,page_end,boundary_confidence,"
    "lessons!lessons_chapter_id_fkey(lesson_id,status,tier,created_at)"
)

# Columns the generate endpoint needs off the chapters row. `book_id` is
# selected so ownership can be RE-checked on the returned row even though the
# query already filters on it (the same belt-and-braces `_fetch_owned_book`
# uses); `page_start`/`page_end` drive the AC11 span gate and must come from the
# database, never from client input, or the gate is trivially bypassed.
_GENERATE_CHAPTER_COLUMNS: str = (
    "chapter_id,book_id,chapter_index,title,page_start,page_end,boundary_confidence"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

_STATUS_MAP: dict[str, str] = {
    "generating": "running",
    "ready": "ready",
    "failed": "failed",
}


def _map_status(db_status: str) -> str:
    return _STATUS_MAP.get(db_status, "queued")


def _generating_cutoff_iso() -> str:
    """The `created_at` before which a `generating` lesson cannot still be running (D53).

    NOTHING but the worker ever moves a lesson out of `generating` — there is no
    reaper, and the rollback path below can itself fail. So a worker killed
    mid-run (OOM per D50, a deploy, a container eviction) leaves a row that
    nothing clears, and an unbounded `status = 'generating'` query treats that
    corpse as live work forever. Two things then break permanently for that user:
    the idempotency pre-check keeps returning 200 with the dead lesson so the
    chapter+tier can never be regenerated (`?force=true` is D54, unbuilt), and
    three such rows exhaust `max_concurrent_generations_per_user` and 429 them
    out of ALL generation, with a `Retry-After: 60` that will never come true.

    The bound is `settings.arq_job_timeout_s` rather than a fresh constant on
    purpose: it is ARQ's own `job_timeout` for the whole pipeline, so it is the
    longest a run can possibly last before ARQ cancels it. A new magic number
    here would silently drift away from the real ceiling the first time that
    setting is tuned.

    KNOWN LIMITATION (D53): the clock starts at `lessons.created_at`, which is
    written before the job is enqueued, so the bound covers RUN time but not
    queue-wait time. A job that sits queued behind others for longer than the
    timeout could be declared stale while still live, costing a duplicate
    enqueue. Accepted for now — the queue is per-user-bounded at 3 concurrent,
    and the alternative failure (a permanent lockout) is strictly worse than a
    rare duplicate. The durable fix is the D53 reaper plus a real `started_at`.
    """
    timeout_s = get_settings().arq_job_timeout_s
    return (datetime.now(UTC) - timedelta(seconds=timeout_s)).isoformat()


def _embedded_object(value: Any) -> dict[str, Any] | None:  # noqa: ANN401 — embed shape varies
    """Unwrap a PostgREST to-ONE embed into a dict, or None (Story 1-14).

    `chapter:chapters!lessons_chapter_id_fkey(...)` is a to-one relation, so
    PostgREST sends an object or `null`. A legacy lesson has `chapter_id IS NULL`
    and therefore no chapter at all, which is the NORMAL state for every lesson
    created before Phase 6 — it must yield None, not raise. A list is tolerated
    too: the same constraint viewed from the chapters side is to-many, and
    confusing the two is the single most likely mistake here (see
    `_CHAPTER_COLUMNS`). Being permissive costs nothing; 500-ing the whole
    lesson list costs the dashboard.
    """
    if isinstance(value, list):
        value = value[0] if value else None
    return value if isinstance(value, dict) else None


def _row_to_status_response(
    lesson: dict[str, Any],
    error: str | None = None,
) -> LessonStatusResponse:
    # `get_lesson` selects `*` (no embed) and `list_lessons` selects the embed,
    # so chapter_id is read from the flat column — present on both paths — while
    # title/index come from the embed and stay None on the `*` path rather than
    # costing a second round-trip per lesson.
    chapter = _embedded_object(lesson.get("chapter"))
    chapter_id = lesson.get("chapter_id") or (chapter or {}).get("chapter_id")
    chapter_index = (chapter or {}).get("chapter_index")
    return LessonStatusResponse(
        lesson_id=str(lesson["lesson_id"]),
        status=_map_status(lesson.get("status", "generating")),
        title=lesson.get("title"),
        error=error,
        created_at=str(lesson["created_at"]) if lesson.get("created_at") else None,
        completed_at=str(lesson["completed_at"]) if lesson.get("completed_at") else None,
        subject=_coerce_str(_metadata_field(lesson, "subject")),
        estimated_duration_mins=_coerce_float(_metadata_field(lesson, "estimated_duration_mins")),
        chapter_id=str(chapter_id) if chapter_id else None,
        chapter_title=_coerce_str((chapter or {}).get("title")),
        chapter_index=int(chapter_index) if isinstance(chapter_index, int | float) else None,
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


def _embedded_lessons(value: Any) -> list[dict[str, Any]]:  # noqa: ANN401 — embed shape varies
    """Unwrap the to-MANY `lessons` embed into a list of rows (Story 1-14).

    A chapter with no lessons is the NORMAL state — it is what every chapter of
    a freshly ingested book looks like — and PostgREST sends `[]` for it. A bare
    `[0]` index would therefore 500 the entire chapter list for any book that has
    not been generated from yet, i.e. the common case. Mirrors `_embedded_count`
    above: tolerate list, dict-for-a-to-one, and null alike, and never raise.
    """
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _all_lessons(lessons: list[dict[str, Any]]) -> list[LatestLesson]:
    """Every lesson for the chapter, newest-first, capped at `_MAX_LESSONS_EXPOSED`.

    Story 2-47 (S4-06). Rows missing a `lesson_id` are skipped entirely — a
    malformed row can never be mistaken for the newest, nor silently occupy a
    slot in the exposed list. Sorted newest-first by `(created_at, lesson_id)`:
    `created_at` is `timestamptz NOT NULL DEFAULT now()` and PostgREST renders
    it ISO-8601, which sorts correctly as a string; `lesson_id` is an explicit
    secondary key so two rows tied on `created_at` (plausible under the same
    rapid failed-retry pattern `_MAX_LESSONS_EXPOSED`'s own comment describes)
    sort deterministically instead of depending on Python's sort stability
    plus whatever order PostgREST happened to return them in. Review fix
    (Story 2-47 `/bmad-code-review`, 2026-08-17): `_latest_lesson` below is
    now DERIVED from this list's first element, rather than computed
    independently — two functions computing "the newest lesson" over the same
    rows with different defensive-filtering rules is exactly how `latest_lesson`
    and `lessons[0]` could silently diverge from each other.
    """
    mapped = [
        LatestLesson(
            lesson_id=str(row["lesson_id"]),
            status=_map_status(str(row.get("status") or "generating")),
            tier=str(row.get("tier") or ""),
            created_at=str(row["created_at"]) if row.get("created_at") else None,
        )
        for row in lessons
        if row.get("lesson_id")
    ]
    mapped.sort(key=lambda lesson: (lesson.created_at or "", lesson.lesson_id), reverse=True)
    return mapped[:_MAX_LESSONS_EXPOSED]


def _latest_lesson(lessons: list[dict[str, Any]]) -> LatestLesson | None:
    """The newest lesson, or None — always `_all_lessons(lessons)[0]`.

    Single source of truth (see `_all_lessons`'s docstring for why this used
    to be a second, independent implementation and what that risked). Note
    this reads correctly even though `_all_lessons` caps its return value at
    `_MAX_LESSONS_EXPOSED`: the cap is applied AFTER the newest-first sort, so
    the newest lesson is always at index 0 regardless of how many total rows
    exist — capping only ever drops the OLDEST entries.
    """
    all_lessons = _all_lessons(lessons)
    return all_lessons[0] if all_lessons else None


def _row_to_chapter_response(chapter: dict[str, Any]) -> ChapterResponse:
    """Build one chapter card, with its lesson link sourced from `lessons`.

    Story 1-14: `has_lesson`/`lesson_id` are still DERIVED, never stored, but
    they are now derived from the embedded `lessons` rows rather than from the
    dead scalar `chapters.lesson_id` — which this module neither reads nor
    writes, because its `ON DELETE CASCADE` makes writing it destructive (see
    `_CHAPTER_COLUMNS`). Their meaning changed accordingly: `lesson_id` is the
    NEWEST lesson, and `has_lesson` means "at least one lesson exists, in any
    state". `latest_lesson` carries the status alongside it precisely because
    "at least one, in any state" is not enough for the client — a chapter whose
    only lesson is `failed` must not render a Watch button that 404s the player.
    """
    lessons = _embedded_lessons(chapter.get("lessons"))
    # Computed once, not via _latest_lesson(lessons) + _all_lessons(lessons)
    # separately -- both derive from the same sort, and `latest_lesson` is
    # guaranteed to equal `lessons[0]` by construction (see _all_lessons).
    all_lessons = _all_lessons(lessons)
    latest = all_lessons[0] if all_lessons else None
    return ChapterResponse(
        chapter_id=str(chapter["chapter_id"]),
        chapter_index=int(chapter["chapter_index"]),
        title=str(chapter.get("title") or ""),
        page_start=int(chapter["page_start"]),
        page_end=int(chapter["page_end"]),
        boundary_confidence=str(chapter.get("boundary_confidence") or "fallback"),
        lesson_id=latest.lesson_id if latest else None,
        has_lesson=bool(lessons),
        lesson_count=len(lessons),
        latest_lesson=latest,
        lessons=all_lessons,
    )


def _validated_book_id(book_id: str) -> str:
    """AC6: a malformed book_id is a 404, never a 500.

    Same guard and same convention as `get_lesson` (:429-433) — deliberately
    identical, because a different shape here would be a different security
    posture. The detail string carries no metadata (AC5).

    Returns the CANONICAL form (`str(uuid.UUID(x))`), never the caller's string.
    `uuid.UUID()` accepts far more spellings than it emits: uppercase hex,
    `{braces}`, and a `urn:uuid:` prefix all parse. Postgres compares uuids
    canonically, so an uppercase id matches its row perfectly — but any
    STRING comparison this module then makes against the returned value fails.
    That mismatch is not hypothetical: `generate_chapter_lesson` compares the
    fetched `chapter["book_id"]` to this value, so an uppercase book_id used to
    produce a 404 for a chapter the caller owns and can see in
    `GET /books/{id}/chapters`. Canonicalise once, here, and every downstream
    comparison, INSERT and storage-key reconstruction is on the same footing.
    """
    try:
        canonical = uuid.UUID(book_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Book not found"
        ) from None
    return str(canonical)


def _validated_chapter_id(chapter_id: str) -> str:
    """A malformed chapter_id is a 404, never a 500 (Story 1-14 AC4/AC5).

    Deliberately symmetric with `_validated_book_id` above — a different shape
    here would be a different security posture on the same request. It runs
    BEFORE any DB call, so a garbage path segment never reaches PostgREST (where
    it would produce a `22P02 invalid input syntax for type uuid` and a 500 that
    tells the caller the id was merely malformed rather than absent).

    The detail is the flat "Chapter not found" — byte-identical to the 404 for a
    chapter that belongs to a different book of the caller's, and carrying no
    title, page range or index (AC5).

    Returns the CANONICAL form for the same reason as `_validated_book_id` — see
    the note there. Here the canonical value is what gets INSERTed into
    `lessons.chapter_id` and echoed back in the response, so returning the
    caller's spelling would let the response `chapter_id` differ byte-for-byte
    from the one `GET /books/{id}/chapters` reports for the same row.
    """
    try:
        canonical = uuid.UUID(chapter_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found"
        ) from None
    return str(canonical)


def _source_pdf_path(user_id: str, book_id: str, filename: str) -> str:
    """The ONE expression of the `source-pdfs` storage key layout (Story 1-14 AC7).

    `books` has no path column — the table is created once
    (20260625000000:28-45) and the only later ALTER enables RLS — so the key has
    to be RECONSTRUCTED whenever a lesson is generated, minutes or days after the
    upload that wrote the object. Two independent f-strings would be two sources
    of truth for a value that must be byte-exact, and the failure mode of a
    mismatch is silent here: the `lessons` INSERT succeeds, the caller gets a
    202, and the pipeline dies minutes later inside `extract_node` looking like a
    parsing bug. Hence one helper, used by both `upload_lesson` (which writes the
    object) and `generate_chapter_lesson` (which reconstructs the key).

    Reconstruction is exact because `upload_lesson` sanitises the filename ONCE
    and stores that same sanitised value in `books.filename`; the pre-Phase-3
    formula was identical, so legacy rows reconstruct too. `filename` must
    therefore come from the fetched `books` row — never re-sanitised here, and
    never taken from the request.

    `book_id` must likewise be the CANONICAL uuid string. `upload_lesson` writes
    the object under the id Postgres minted, which is always lowercase-hyphenated;
    a caller spelling the same id in uppercase would reconstruct a key that does
    not exist. `_validated_book_id` now guarantees that form. Until it did, this
    was safe only by accident — the uppercase request was rejected earlier by the
    unrelated `chapter["book_id"] != validated_book_id` string comparison, so the
    "byte-exact" guarantee above was a property of a bug, not of this code.

    `user_id` likewise comes from the books row rather than the JWT. They are
    equal on every path that reaches here (ownership is proven first), but the
    row is what the object was actually written under, and a future admin or
    support path with a different caller identity must not silently point at a
    key that does not exist.
    """
    return f"{user_id}/{book_id}/{filename}"


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
    current_user: ApprovedUser,
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
                f"(POST {GENERATE_LESSON_PATH})."
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
        # The key layout lives in ONE place (AC7) — `generate_chapter_lesson`
        # must reconstruct this exact string from the books row long after the
        # upload, and `books` has no column to store it in.
        storage_path = _source_pdf_path(user_id, str(book_id), safe_filename)
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

    `lesson_count`, `has_lesson`, `lesson_id` and `latest_lesson` are derived
    from the embedded `lessons` rows on the same query (Story 1-14) — one
    round-trip for the whole book, not one per chapter — and are `0/false/null`
    for a chapter nobody has generated from yet, which is the normal state.
    """
    user_id: str = current_user["sub"]
    supabase = get_supabase()
    validated_id = _validated_book_id(book_id)
    _fetch_owned_book(supabase, validated_id, user_id, "book_id,user_id")

    # `lessons.user_id` is an EMBEDDED filter: it constrains the rows inside the
    # `lessons` array, not which chapters come back. (Verified against a real
    # PostgREST: a chapter whose only lessons belong to another user is still
    # returned, with `lessons: []` — it does not vanish from the list, and a
    # mistyped embedded column is a 400/42703, not a silent 200.)
    #
    # Defence in depth, and only that TODAY: this endpoint is the sole writer of
    # `lessons.chapter_id`, and it always writes the caller's own user_id, so
    # `lessons.user_id` currently equals the book owner by construction. But the
    # Supabase client is service-role with no RLS backstop, and the moment a
    # second writer exists — admin regenerate, a shared book, a backfill —
    # another user's `lesson_id`, `status` and `tier` would surface on the
    # owner's chapter cards, and `_latest_lesson` could hand back a `lesson_id`
    # that `GET /lessons/{id}` then 404s. Enforcing the invariant here makes it a
    # property of this query rather than something inherited from who happens to
    # write the table.
    # One book's chapters, capped by the detection ladder before the query runs:
    # `gate.py` selects the coarsest outline level with 4-80 entries, so a book
    # cannot produce more than 80 chapter rows, and the 8-book Phase 1 corpus
    # measured 20-53. A `.limit()` here would silently truncate a legitimate
    # chapter list — the exact failure this endpoint exists to prevent.
    # The embedded `lessons` side is NOT bounded by that argument — see D115
    # (mis-cited as D59 in the original story draft; corrected 2026-08-17).
    # BOUNDED: <= 80 rows, enforced by the chapter-detection gate (4-80 entries).
    resp = (
        supabase.table("chapters")
        .select(_CHAPTER_COLUMNS)
        .eq("book_id", validated_id)
        .eq("lessons.user_id", user_id)
        .order("chapter_index")
        .execute()
    )
    return [_row_to_chapter_response(row) for row in rows(resp)]


@router.post(
    GENERATE_LESSON_PATH,
    response_model=LessonGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate a lesson from one chapter at a chosen difficulty tier",
)
@limiter.limit("3/minute;20/hour", key_func=_get_user_key)
async def generate_chapter_lesson(
    request: Request,
    response: Response,
    book_id: str,
    chapter_id: str,
    body: GenerateLessonRequest,
    current_user: CurrentUser,
    arq_redis: ArqRedis,
) -> LessonGenerationResponse:
    """Create one `lessons` row for one chapter and enqueue the pipeline.

    This is the single write that reconnects book ingestion to lesson
    generation. `content_pipeline_job` already selects `chapter_id` and threads
    it to `extract_node`, which looks the chapter up and passes its real
    `page_start`/`page_end` to the isolated PDF subprocess — all of that is built
    and merged. Nothing wrote the column, so between Phase 3 and now there was no
    way to generate a lesson at all. One INSERT lights the whole path up.

    ── `request: Request` is load-bearing ────────────────────────────────────
    slowapi resolves the client key by looking for a parameter LITERALLY named
    `request` of type `Request`; without it `@limiter.limit` raises at call time,
    not at import time, so the failure would first appear in production. The
    parameter is otherwise unused — do not "clean it up".

    ── The rate limit is only correct at ONE replica (AC13, D49) ─────────────
    `RATE_LIMIT_STORAGE_URL` defaults to `memory://` (`core/rate_limit.py:69`),
    which is per-process storage, so N API replicas enforce N x `3/minute;20/hour`
    and every counter resets on restart. This endpoint spends real money — at the
    $3.00/lesson ceiling the hourly limit is ~$60/user/hour PER REPLICA — so the
    number chosen to bound spend holds only while there is exactly one replica.
    Set `RATE_LIMIT_STORAGE_URL` to the Railway Redis URL before scaling out or
    migrating to the India region (D49).

    ── Authorization: 404, never 403, and no timing padding ──────────────────
    The Supabase client is service-role and bypasses RLS, and `chapters` has no
    `user_id` column at all, so application-layer filtering is the ONLY control
    here. Ownership is resolved on `books` first and re-checked on the returned
    row; the chapter fetch is additionally scoped by `book_id` and re-checked
    after the fetch. Those post-fetch re-checks are not redundant — they are what
    survives a future refactor that drops a `.eq()`.

    A 403 would confirm the id exists, so both "absent" and "someone else's" are
    the same 404 with the same body, carrying no filename, title, page range or
    index.

    There is deliberately NO timing padding between the one-query and two-query
    404s. The difference is only reachable AFTER the caller has proven ownership
    of the book, and it distinguishes states they can already enumerate for free
    via `GET /books/{id}/chapters`. Padding it would add latency and guard
    nothing — please do not "fix" this later.

    `extract_node` does re-verify that the chapter belongs to the book, but this
    endpoint must NOT lean on that: by then the `lessons` row, the `lesson_jobs`
    row and the ARQ job all exist, so the caller receives a 202 and a `failed`
    lesson instead of a 404, and a worker slot has been burnt.

    ── Idempotency is best-effort and TOCTOU-racy, by construction ───────────
    A 202 invites a retry, so an existing `generating`/`ready` lesson for the
    same (chapter, tier, user) is returned with 200 and no second enqueue. Only
    `failed` matches are regenerated; a different tier is always a new lesson,
    which the schema permits deliberately (`lessons_chapter_id_idx` is
    NON-unique).

    This check is a read followed by a write with no lock between them: two
    concurrent requests can both see nothing and both insert. There is no
    database uniqueness to lean on — no UNIQUE exists on `lessons.chapter_id`,
    `chapters.lesson_id` or `(chapter_id, tier)` in any migration. The durable
    fix is a partial unique index `(chapter_id, tier) WHERE status <> 'failed'`,
    which is a frozen-contract migration and out of scope; it is registered in
    the defect register instead. Treat the 200 path as an optimisation, never as
    a guarantee.

    ── Two different page numbers gate two different failures ────────────────
    `settings.max_chapter_pages` (200) refuses a CATASTROPHE — a rung-5
    whole-document "chapter" of 1,151 pages, the exact bug this effort exists to
    fix. `_TRUNCATION_WARN_PAGES` (40) warns about a QUALITY cliff: only ~90,000
    characters of any chapter are ever LLM-visible, so past ~40 pages the lesson
    is genuinely built from part of the chapter. The $3.00 cost ceiling does not
    protect against either — a too-large chapter produces a cheap WRONG lesson,
    not an expensive one, and never trips the ceiling. Span is computed from the
    DB row, never from client input.

    ── What rollback may touch ──────────────────────────────────────────────
    Only what this request created: `lesson_jobs` then `lessons`. Never the
    `books` row, never the storage object, and never the `chapters` row. The
    pre-Phase-3 code deleted all three, correctly, because upload and generation
    were one call; doing it here would destroy a whole book's ingestion over one
    failed generation.
    """
    user_id: str = current_user["sub"]
    supabase = get_supabase()
    settings = get_settings()
    tier: str = body.tier

    # ── Gate 1-2: both ids validated BEFORE any DB call ───────────────────────
    validated_book_id = _validated_book_id(book_id)
    validated_chapter_id = _validated_chapter_id(chapter_id)

    # ── Gate 3a: ownership of the BOOK, proven first ──────────────────────────
    # `user_id` and `filename` are selected because `_source_pdf_path` must
    # reconstruct the storage key from the row that was actually written, not
    # from the JWT. `books` has no path column to read it back from.
    book = _fetch_owned_book(
        supabase, validated_book_id, user_id, "book_id,user_id,filename,status"
    )

    # ── Gate 3b: the chapter, scoped to that book, then re-checked ────────────
    chapter_resp = (
        supabase.table("chapters")
        .select(_GENERATE_CHAPTER_COLUMNS)
        .eq("chapter_id", validated_chapter_id)
        .eq("book_id", validated_book_id)
        .maybe_single()
        .execute()
    )
    chapter: dict[str, Any] | None = single_row(chapter_resp)
    if not chapter or str(chapter.get("book_id")) != validated_book_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

    # ── Gate 4: the book must have finished ingestion ─────────────────────────
    # 409, not 404: the book exists and the caller owns it — there is simply
    # nothing to generate from yet, and 'processing' becomes 'ready' on its own.
    # A 'failed' book needs a re-upload, which is also the caller's move.
    if str(book.get("status") or "") != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Book is not ready — chapter detection has not finished",
        )

    # Arithmetic only; the 422 it feeds is raised below, after idempotency.
    page_span = int(chapter["page_end"]) - int(chapter["page_start"]) + 1

    # ── Gate 4b: the span must be a real span ─────────────────────────────────
    # Nothing in `supabase/migrations/` CHECKs `page_end >= page_start`, so a
    # detection bug can persist a chapter whose span is zero or negative. Every
    # gate below is an upper bound, so such a row sails through both of them: it
    # is under `max_chapter_pages`, and under `_TRUNCATION_WARN_PAGES` too, so
    # the caller is told the lesson is complete while `extract_node` is handed a
    # page range that selects nothing.
    #
    # 409, not 422: the request is well-formed and the caller supplied no page
    # numbers at all (they are read from the DB precisely so they cannot be), so
    # this is a broken chapter row, not bad input — and unlike the 422 below it
    # is not something a smaller/different request would fix. Raised eagerly
    # rather than deferred past idempotency like the catastrophe gate, because
    # returning 200 with an existing lesson would report success for a chapter
    # whose page range is nonsense.
    if page_span < 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chapter page range is invalid — re-ingest the book",
        )

    truncation_expected = page_span > _TRUNCATION_WARN_PAGES

    # ── Gate 5: idempotency (best-effort — see the docstring) ─────────────────
    # `created_at` is selected purely to age out dead `generating` rows (D53).
    #
    # The staleness bound is applied HERE, in Python, and not as a `.gte()` on
    # the query — deliberately, and the difference from Gate 7 below matters. A
    # query-level age filter would drop old `ready` lessons too, and a `ready`
    # lesson is idempotent FOREVER: aging it out would regenerate a lesson that
    # already exists and bill the user a second time for it. Only the
    # `generating` branch gets a clock.
    stale_before = _generating_cutoff_iso()
    existing_resp = (
        supabase.table("lessons")
        .select("lesson_id,status,tier,created_at")
        .eq("chapter_id", validated_chapter_id)
        .eq("tier", tier)
        .eq("user_id", user_id)
        .execute()
    )
    # D54: `body.force` bypasses ONLY the early-return below — the branch that
    # hands an existing `generating`/`ready` lesson back as-is instead of a new
    # one being created. Gate 6 and Gate 7 still run unconditionally after this
    # block, whether force is set or not. `existing_resp` itself is still
    # fetched above unconditionally — nothing downstream of this block reads
    # it, so skipping only the early-return, not the query, is deliberate: it
    # keeps this diff minimal and leaves the query available if that changes.
    # The D53 stale-generating `continue` inside the loop becomes moot when
    # force=True (the loop never runs at all), which is correct: force means
    # "make a new one regardless," not "decide whether the old one still
    # counts."
    for existing in rows(existing_resp) if not body.force else []:
        existing_status = str(existing.get("status") or "")
        if existing_status == "generating" and str(existing.get("created_at") or "") < stale_before:
            # Older than any run can last, so no worker is on it. Fall through
            # and generate a replacement rather than handing the caller a corpse
            # they have no way to clear (D53; escape hatch is `force=true`, D54).
            # `created_at` is `timestamptz` rendered ISO-8601 by PostgREST and
            # the cutoff is built the same way, so the string compare is a real
            # time compare — the same property `_latest_lesson` relies on.
            logger.warning(
                "stale generating lesson ignored for idempotency (D53): "
                "lesson_id=%s chapter_id=%s tier=%s created_at=%s",
                existing.get("lesson_id"),
                validated_chapter_id,
                tier,
                existing.get("created_at"),
            )
            continue
        if existing_status in ("generating", "ready"):
            # 200, not 202: nothing was accepted for processing this time, and
            # no job was enqueued. `job_id` stays None — the original ARQ id is
            # not persisted anywhere and inventing one would hand the client a
            # token it could poll forever.
            response.status_code = status.HTTP_200_OK
            return LessonGenerationResponse(
                lesson_id=str(existing["lesson_id"]),
                chapter_id=validated_chapter_id,
                tier=tier,
                # Mapped, so `status` means the same thing on both branches of
                # this endpoint AND across every other lesson-facing route:
                # 'queued' on the 202 (the job was just enqueued and no node has
                # run), then 'running'|'ready'|'failed' thereafter. Returning the
                # raw 'generating' here would make one field mean "API acceptance
                # state" on one branch and "DB lifecycle state" on the other.
                status=_map_status(existing_status),
                job_id=None,
                truncation_expected=truncation_expected,
            )

    # ── Gate 6: the catastrophe gate ──────────────────────────────────────────
    if page_span > settings.max_chapter_pages:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "chapter_too_large",
                "page_span": page_span,
                "max_page_span": settings.max_chapter_pages,
                # Returned so the client can explain WHY the span is absurd: a
                # 'fallback' boundary means detection found no signal at all and
                # made the whole document one chapter. It is NOT itself a gate —
                # a legitimate 60-page single-chapter PDF is also rung 5.
                "boundary_confidence": str(chapter.get("boundary_confidence") or "fallback"),
            },
        )

    # ── Gate 7: per-user concurrency — the real spend control ─────────────────
    # The rate limit above bounds request RATE; this bounds concurrent
    # PIPELINES, each of which can cost up to `max_lesson_cost_usd`. Counted
    # rows rather than a PostgREST exact count so the value survives the
    # `rows()` helper unchanged.
    #
    # `.gte("created_at", ...)` bounds it by age (D53). Unlike Gate 5 the
    # predicate belongs on the QUERY here, because this query already filters to
    # `status = 'generating'` and nothing else — there is no `ready` row for an
    # age filter to wrongly discard. Without it, three lessons abandoned by
    # killed workers consume every slot permanently and 429 the user out of all
    # generation forever, behind a `Retry-After` that can never come true.
    running = rows(
        supabase.table("lessons")
        .select("lesson_id")
        .eq("user_id", user_id)
        .eq("status", "generating")
        .gte("created_at", stale_before)
        .execute()
    )
    if len(running) >= settings.max_concurrent_generations_per_user:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Too many lessons are already generating — wait for one to finish "
                "before starting another"
            ),
            headers={"Retry-After": str(_CONCURRENCY_RETRY_AFTER_S)},
        )

    # ── Create the work ───────────────────────────────────────────────────────
    lesson_id: str | None = None
    try:
        # Every key below is a REAL column. `lessons` has no `error`, no
        # `completed_at`, no `session_id` and no `subject`; naming one makes
        # PostgREST reject the whole statement with 42703 — the D9 outage shape,
        # which a Supabase mock cannot reproduce. `status` must be 'generating'
        # ('queued' violates lessons_status_check) and `tier` is already
        # constrained to the valid set by the request model.
        source_file_path = _source_pdf_path(
            str(book["user_id"]), validated_book_id, str(book.get("filename") or "")
        )
        lessons_resp = (
            supabase.table("lessons")
            .insert(
                {
                    "user_id": user_id,
                    "book_id": validated_book_id,
                    "chapter_id": validated_chapter_id,
                    "tier": tier,
                    "status": "generating",
                    "title": str(chapter.get("title") or f"Chapter {chapter['chapter_index']}"),
                    "source_file_path": source_file_path,
                }
            )
            .execute()
        )
        lessons_rows = rows(lessons_resp)
        if not lessons_rows:
            raise RuntimeError("lessons insert returned no rows")
        lesson_id = str(lessons_rows[0]["lesson_id"])

        # `chapters.lesson_id` is deliberately NOT written here. That FK is
        # ON DELETE CASCADE and `chunks.chapter_id` cascades from the chapter, so
        # pointing the chapter at this lesson and then rolling the lesson back
        # below would delete the chapter and every chunk and embedding under it —
        # a whole book's ingestion destroyed by one failed generation. The column
        # is also scalar and cannot express one chapter with lessons at three
        # tiers. It is dead; the reads source the link from `lessons` instead.

        supabase.table("lesson_jobs").insert(
            {"lesson_id": lesson_id, "status": "pending"}
        ).execute()

        # `pipeline:{lesson_id}` is kept verbatim: it is the retry-safety key the
        # worker and CLAUDE.md's thread_id rule already reference. A
        # chapter-keyed variant would collide across tiers and would block a
        # legitimate regeneration after a failure.
        job = await arq_redis.enqueue_job(
            "content_pipeline_job", lesson_id, _job_id=f"pipeline:{lesson_id}"
        )
        if job is None:
            # `lesson_id` was minted by the INSERT immediately above, so ARQ
            # cannot be deduplicating an in-flight key — this is unreachable by
            # construction. It is checked anyway (never assume) but it is a
            # server fault, not the caller's: it falls into the generic 500 and
            # the rollback below, rather than the old 409 whose message ("a job
            # is already queued for this ID") would now be a false statement.
            raise RuntimeError(f"ARQ returned no job for lesson_id={lesson_id}")
        job_id: str = job.job_id

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "generate_chapter_lesson failed user_id=%s book_id=%s chapter_id=%s",
            user_id,
            validated_book_id,
            validated_chapter_id,
        )
        # Only what THIS request created, child before parent, each isolated so a
        # transient failure on one does not abandon the rest. Never `books`,
        # never the storage object, never `chapters` — see the docstring.
        #
        # Each failure is LOGGED, not merely suppressed. A rollback that fails
        # leaves the `lessons` row in `generating` with no job behind it, which
        # is exactly the dead row D53 is about: it blocks this chapter+tier from
        # ever being generated again and consumes one of the caller's three
        # concurrency slots until the staleness bound above ages it out. Silent
        # suppression made that state invisible at the only moment we could see
        # it being created — the caller gets a 500 either way, so the log line is
        # the sole record that the cleanup did not happen.
        if lesson_id:
            try:
                supabase.table("lesson_jobs").delete().eq("lesson_id", lesson_id).execute()
            except Exception:  # noqa: BLE001 — best-effort rollback; the 500 below still stands
                logger.warning(
                    "rollback failed to delete lesson_jobs for lesson_id=%s (D53)",
                    lesson_id,
                    exc_info=True,
                )
            try:
                supabase.table("lessons").delete().eq("lesson_id", lesson_id).execute()
            except Exception:  # noqa: BLE001 — best-effort rollback; the 500 below still stands
                logger.warning(
                    "rollback failed to delete lesson for lesson_id=%s — it will sit in "
                    "'generating' until the staleness bound ages it out (D53)",
                    lesson_id,
                    exc_info=True,
                )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start lesson generation — please retry",
        ) from exc

    return LessonGenerationResponse(
        lesson_id=lesson_id,
        chapter_id=validated_chapter_id,
        tier=tier,
        status="queued",
        job_id=job_id,
        truncation_expected=truncation_expected,
    )
