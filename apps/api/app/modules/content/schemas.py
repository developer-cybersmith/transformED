"""
Content module response schemas.

Story 1-11 (book-scale Phase 3.5). These are LOCAL to the content module by
design: `packages/shared` is a frozen interface contract requiring four-developer
review (CLAUDE.md §16), and the book/chapter read endpoints need no change to it.

The router still declares its older lesson models inline; new models land here.
"""

from __future__ import annotations

from pydantic import BaseModel


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

    `lesson_id` and `has_lesson` ship now (AC4) even though both are always
    null/false until Phase 6 makes lesson generation per-chapter — including
    them today means Dev 2's chapter card is not rebuilt at W3.
    """

    chapter_id: str
    chapter_index: int
    title: str
    page_start: int
    page_end: int
    boundary_confidence: str  # toc | contents | heading | font | fallback
    lesson_id: str | None = None
    has_lesson: bool = False
