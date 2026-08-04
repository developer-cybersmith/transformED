"""
Content module response schemas.

Story 1-11 (book-scale Phase 3.5). These are LOCAL to the content module by
design: `packages/shared` is a frozen interface contract requiring four-developer
review (CLAUDE.md §16), and the book/chapter read endpoints need no change to it.

The router still declares its older lesson models inline; new models land here.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator

from app.schemas.lesson import DEFAULT_TIER, VALID_TIERS


class GenerateLessonRequest(BaseModel):
    """Body of POST /books/{book_id}/chapters/{chapter_id}/lessons (Story 1-14).

    `tier` is the ONLY thing the client gets to choose. Everything else the
    pipeline needs — book_id, chapter_id, the page range, the source PDF path —
    is read from the database rows the caller has already been proven to own,
    never accepted from the request body. A client-supplied page range would be
    a straight authorization bypass of the AC11 size gate.

    The default and the valid set are imported from `app.schemas.lesson`, which
    is the single source of truth shared with the pipeline graph. A local copy
    of the tier literals here would be the third one in the repo and is the DRY
    violation a previous Blind Hunter review already rejected once.

    Validation is a field validator rather than a `Literal[...]` annotation so
    the set stays imported (one source of truth) instead of being retyped into a
    type expression. It runs during request parsing, i.e. strictly BEFORE the
    handler body and therefore before any DB call — an invalid tier can never
    reach `supabase.table(...)`.
    """

    tier: str = DEFAULT_TIER

    @field_validator("tier")
    @classmethod
    def _tier_must_be_known(cls, value: str) -> str:
        if value not in VALID_TIERS:
            raise ValueError(f"tier must be one of {', '.join(sorted(VALID_TIERS))}")
        return value


class LatestLesson(BaseModel):
    """The newest lesson generated from a chapter, embedded in ChapterResponse.

    `status` is carried deliberately: `has_lesson=true` on a chapter whose only
    lesson is `failed` would render a "Watch" button that 404s the player.

    The value is the API vocabulary, not the DB column: `router._latest_lesson`
    runs the raw `lessons.status` through `_map_status` first. The two differ on
    exactly one value — the DB's `generating` is the API's `running` — and every
    other lesson-facing route in this API already speaks the API vocabulary. If
    this field carried the raw column, a client switch matching `running` would
    silently fall through on chapter cards and nowhere else.
    """

    lesson_id: str
    # API vocabulary: queued | running | ready | failed.
    # (DB `lessons.status` is generating | ready | failed — lessons_status_check.)
    status: str
    tier: str  # T1 | T2 | T3
    created_at: str | None = None


class LessonGenerationResponse(BaseModel):
    """Result of requesting a lesson for one chapter at one tier (Story 1-14).

    Returned with 202 when a new lesson was created and enqueued, and with 200
    when an existing non-failed lesson for the same (chapter, tier, user) was
    returned instead (the idempotent path).

    `job_id` is None on the 200 path: the ARQ id of the original enqueue is not
    persisted anywhere, and inventing one would be a lie the client could try to
    poll. `truncation_expected` is True when the chapter is large enough that the
    LLM-visible window covers only part of it — see router._TRUNCATION_WARN_PAGES.
    """

    lesson_id: str
    chapter_id: str
    tier: str
    # API vocabulary on BOTH paths: queued | running | ready | failed.
    # "queued" on the 202 (the job was just enqueued and no node has run); on the
    # 200 path the existing lesson's DB status passed through `router._map_status`,
    # so a DB `generating` is reported as `running` — never the raw column, which
    # would make one field mean "API acceptance state" on one branch and "DB
    # lifecycle state" on the other.
    status: str
    job_id: str | None = None
    truncation_expected: bool = False


class BookResponse(BaseModel):
    """One uploaded book, as returned by GET /books and GET /books/{book_id}.

    The two endpoints return the SAME shape deliberately (AC2): `UploadFlow`
    polls the single-book route and renders the list route with one component.

    `page_count` is nullable because `books.page_count` is nullable and is only
    written once `book_ingest_job` finishes detection — a book in 'processing'
    legitimately has none yet.
    """

    book_id: str
    filename: str
    status: str  # processing | ready | failed (books_status_check)
    page_count: int | None = None
    chapter_count: int = 0
    created_at: str | None = None


class ChapterResponse(BaseModel):
    """One detected chapter, as returned by GET /books/{book_id}/chapters.

    Story 1-14 (Phase 6) re-sourced the lesson link. It is now derived from the
    `lessons` side of `lessons_chapter_id_fkey` — a to-MANY relation — and not
    from the scalar `chapters.lesson_id`, which is a dead column with a live
    ON DELETE CASCADE and is never read or written (see router._CHAPTER_COLUMNS).

    `lesson_id` and `has_lesson` are kept because they are Dev 2's committed
    contract, but their meaning is now: the NEWEST lesson generated from this
    chapter, and "at least one lesson exists in any state". A scalar column could
    never express one chapter with lessons at three tiers; `lesson_count` and
    `latest_lesson` can. Zero-lesson chapters are the normal state, so all four
    fields have empty defaults.
    """

    chapter_id: str
    chapter_index: int
    title: str
    page_start: int
    page_end: int
    boundary_confidence: str  # toc | contents | heading | font | fallback
    lesson_id: str | None = None
    has_lesson: bool = False
    lesson_count: int = 0
    latest_lesson: LatestLesson | None = None
