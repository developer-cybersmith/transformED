"""
Unit tests for the book/chapter read endpoints (Story 1-11, book-scale Phase 3.5).

Covers AC1-AC6:
  AC1  GET /api/content/books                     — caller's books, newest first
  AC2  GET /api/content/books/{book_id}           — one book, same shape
  AC3  GET /api/content/books/{book_id}/chapters  — ordered by chapter_index
  AC4  lesson_id / has_lesson ship now — and, since Story 1-14 (AC14/AC15),
       are derived from the embedded `lessons` array plus the new
       lesson_count / latest_lesson fields. `chapters.lesson_id` is a dead
       column with a live CASCADE and is never read.
  AC5  another user's book → 404 (never 403), with NO metadata in the body
  AC6  malformed (non-UUID) book_id → 404, not 500

The Supabase client is SERVICE-ROLE (app/core/db.py:42), so RLS does not filter
for these queries — ownership is application-level and is asserted here directly
on the query the router builds, not only on the response body.

Mocks: Supabase client, JWT auth dependency. No network, Redis or DB.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ── Fixtures / fakes ──────────────────────────────────────────────────────────

FAKE_USER: dict[str, Any] = {
    "sub": "550e8400-e29b-41d4-a716-446655440000",
    "email": "test@example.com",
    "role": "authenticated",
}
OTHER_USER: dict[str, Any] = {**FAKE_USER, "sub": "99999999-9999-9999-9999-999999999999"}

FAKE_BOOK_ID = "11111111-1111-1111-1111-111111111111"
OTHER_BOOK_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
FAKE_CHAPTER_ID = "44444444-4444-4444-4444-444444444444"
FAKE_LESSON_ID = "22222222-2222-2222-2222-222222222222"

# Shapes as PostgREST returns them: an embedded aggregate arrives as a list of
# one dict, e.g. {"chapters": [{"count": 21}]}.
BOOK_ROW: dict[str, Any] = {
    "book_id": FAKE_BOOK_ID,
    "user_id": FAKE_USER["sub"],
    "filename": "ncert_xi_part1.pdf",
    "status": "ready",
    "page_count": 1151,
    "created_at": "2026-08-03T10:00:00Z",
    "chapters": [{"count": 21}],
}

# Story 1-14 (AC15): the chapters select no longer names `chapters.lesson_id`.
# It embeds `lessons!lessons_chapter_id_fkey(...)`, which PostgREST returns as a
# JSON ARRAY (to-many) — `[]` for the normal zero-lesson chapter. These rows are
# shaped the way PostgREST really answers, not the way the old scalar column did.
CHAPTER_ROWS: list[dict[str, Any]] = [
    {
        "chapter_id": FAKE_CHAPTER_ID,
        "chapter_index": 0,
        "title": "Physical World",
        "page_start": 40,
        "page_end": 68,
        "boundary_confidence": "toc",
        "lessons": [],
    },
    {
        "chapter_id": "55555555-5555-5555-5555-555555555555",
        "chapter_index": 1,
        "title": "Units and Measurements",
        "page_start": 69,
        "page_end": 92,
        "boundary_confidence": "toc",
        "lessons": [],
    },
]


def _lesson(
    lesson_id: str, *, tier: str = "T1", status: str = "ready", created_at: str
) -> dict[str, Any]:
    """One element of the embedded `lessons` array."""
    return {"lesson_id": lesson_id, "status": status, "tier": tier, "created_at": created_at}


def _resp(data: Any) -> MagicMock:  # noqa: ANN401 — postgrest response payloads vary
    r = MagicMock()
    r.data = data
    return r


def _make_supabase_mock(
    book_rows: list[dict[str, Any]] | None = None,
    book_row: dict[str, Any] | None = None,
    chapter_rows: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Supabase mock wired for the three read endpoints.

    `book_row` is what the single-book fetch resolves to — None models both
    "no such book" and "owned by someone else", because the query filters on
    user_id, so a foreign book simply does not come back.
    """
    books_tbl = MagicMock()
    select = books_tbl.select.return_value
    eq_user = select.eq.return_value
    # list_books: .select().eq("user_id").order().range().execute()
    eq_user.order.return_value.range.return_value.execute.return_value = _resp(
        book_rows if book_rows is not None else []
    )
    # get_book / ownership probe: .select().eq(...).eq(...).maybe_single().execute()
    eq_user.eq.return_value.maybe_single.return_value.execute.return_value = _resp(book_row)

    # `list_book_chapters` filters TWICE — `.eq("book_id", …)` and, since the
    # 2026-08-04 review, `.eq("lessons.user_id", …)` scoping the embedded lessons
    # to the caller. A mock that hardcodes one `.eq()` returns a fresh MagicMock
    # for the second and the endpoint silently sees zero chapters, so the chain is
    # self-returning and the filters are RECORDED — a test that merely tolerated
    # the extra call would stop noticing if the scoping were dropped.
    chapters_filters: list[tuple[str, Any]] = []
    chapters_chain = MagicMock()

    def _record_eq(key: str, value: Any) -> MagicMock:  # noqa: ANN401
        chapters_filters.append((key, value))
        return chapters_chain

    chapters_chain.eq.side_effect = _record_eq
    chapters_chain.order.return_value.execute.return_value = _resp(
        chapter_rows if chapter_rows is not None else []
    )
    chapters_tbl = MagicMock()
    chapters_tbl.select.return_value = chapters_chain

    table_map = {"books": books_tbl, "chapters": chapters_tbl}
    sb = MagicMock()
    sb.table.side_effect = lambda name: table_map.get(name, MagicMock())
    sb.chapters_filters = chapters_filters
    return sb


def _client(sb: MagicMock, user: dict[str, Any] | None = None) -> Any:  # noqa: ANN401
    """Context-managed TestClient with auth + Supabase patched."""
    from app.dependencies import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: user or FAKE_USER
    return app, TestClient(app, raise_server_exceptions=True)


def _get(sb: MagicMock, url: str, user: dict[str, Any] | None = None) -> Any:  # noqa: ANN401
    app, client = _client(sb, user)
    try:
        with patch("app.modules.content.router.get_supabase", return_value=sb):
            return client.get(url)
    finally:
        app.dependency_overrides.clear()


def _tables_touched(sb: MagicMock) -> list[str]:
    return [call.args[0] for call in sb.table.call_args_list if call.args]


# ── AC1 — GET /books ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_list_books_returns_the_documented_shape() -> None:
    """AC1: [{book_id, filename, status, page_count, chapter_count, created_at}]."""
    sb = _make_supabase_mock(book_rows=[BOOK_ROW])
    resp = _get(sb, "/api/content/books")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert set(body[0]) == {
        "book_id",
        "filename",
        "status",
        "page_count",
        "chapter_count",
        "created_at",
    }
    assert body[0]["book_id"] == FAKE_BOOK_ID
    assert body[0]["filename"] == "ncert_xi_part1.pdf"
    assert body[0]["status"] == "ready"
    assert body[0]["page_count"] == 1151
    assert body[0]["created_at"] == "2026-08-03T10:00:00Z"


@pytest.mark.unit
def test_list_books_chapter_count_is_the_real_count() -> None:
    """AC1: chapter_count is the book's real chapter row count (21 for the
    1,151-page book Phase 3 ingested), unwrapped from PostgREST's embedded
    aggregate shape."""
    sb = _make_supabase_mock(book_rows=[BOOK_ROW])
    body = _get(sb, "/api/content/books").json()
    assert body[0]["chapter_count"] == 21


@pytest.mark.unit
def test_list_books_chapter_count_is_not_an_n_plus_1_query() -> None:
    """AC1 / T2: one aggregate query — the chapters table must never be queried
    once per book."""
    sb = _make_supabase_mock(book_rows=[BOOK_ROW, {**BOOK_ROW, "book_id": OTHER_BOOK_ID}])
    resp = _get(sb, "/api/content/books")

    assert resp.status_code == 200
    assert "chapters" not in _tables_touched(sb), (
        "chapter_count must come from an embedded aggregate on the books query, "
        "not a per-book SELECT on chapters"
    )
    sb.table("books").select.assert_called_once()


@pytest.mark.unit
def test_list_books_is_filtered_by_the_caller_and_newest_first() -> None:
    """AC1 + IDOR: the client is service-role, so RLS does not filter. The
    user_id predicate must be in the query itself."""
    sb = _make_supabase_mock(book_rows=[BOOK_ROW])
    resp = _get(sb, "/api/content/books")

    assert resp.status_code == 200
    books_tbl = sb.table("books")
    books_tbl.select.return_value.eq.assert_any_call("user_id", FAKE_USER["sub"])
    books_tbl.select.return_value.eq.return_value.order.assert_called_once_with(
        "created_at", desc=True
    )


@pytest.mark.unit
def test_list_books_empty_is_200_not_404() -> None:
    sb = _make_supabase_mock(book_rows=[])
    resp = _get(sb, "/api/content/books")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.unit
def test_list_books_with_no_chapters_yet_reports_zero() -> None:
    """A book still ingesting has no chapter rows; PostgREST returns count 0."""
    row = {**BOOK_ROW, "status": "processing", "page_count": None, "chapters": [{"count": 0}]}
    sb = _make_supabase_mock(book_rows=[row])
    body = _get(sb, "/api/content/books").json()
    assert body[0]["chapter_count"] == 0
    assert body[0]["page_count"] is None
    assert body[0]["status"] == "processing"


# ── AC2 — GET /books/{book_id} ────────────────────────────────────────────────


@pytest.mark.unit
def test_get_book_returns_the_same_shape_as_the_list() -> None:
    """AC2: UploadFlow polls this instead of GET /lessons/{id}, so the shape must
    match AC1's exactly."""
    sb = _make_supabase_mock(book_row=BOOK_ROW)
    resp = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "book_id",
        "filename",
        "status",
        "page_count",
        "chapter_count",
        "created_at",
    }
    assert body["book_id"] == FAKE_BOOK_ID
    assert body["chapter_count"] == 21


@pytest.mark.unit
def test_get_book_query_is_scoped_to_the_caller() -> None:
    sb = _make_supabase_mock(book_row=BOOK_ROW)
    assert _get(sb, f"/api/content/books/{FAKE_BOOK_ID}").status_code == 200

    eq = sb.table("books").select.return_value.eq
    eq.assert_any_call("book_id", FAKE_BOOK_ID)
    # second predicate, on the chained builder
    eq.return_value.eq.assert_any_call("user_id", FAKE_USER["sub"])


@pytest.mark.unit
def test_get_book_404_when_absent() -> None:
    sb = _make_supabase_mock(book_row=None)
    resp = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}")
    assert resp.status_code == 404


# ── AC5 — foreign book is 404, not 403, and leaks nothing ─────────────────────


@pytest.mark.unit
def test_get_book_of_another_user_is_404_not_403() -> None:
    """AC5: 403 would confirm the id exists."""
    sb = _make_supabase_mock(book_row=None)  # user_id predicate excludes it
    resp = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}", user=OTHER_USER)
    assert resp.status_code == 404, "403 confirms the id exists — must be 404"


@pytest.mark.unit
def test_get_book_of_another_user_body_carries_no_metadata() -> None:
    """AC5: no filename, no page count, no status, no chapter count in the body."""
    sb = _make_supabase_mock(book_row=None)
    resp = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}", user=OTHER_USER)
    text = resp.text.lower()
    for leaked in ("ncert_xi_part1.pdf", "1151", "page_count", "chapter_count", "filename"):
        assert leaked.lower() not in text, f"404 body leaked {leaked!r}"


@pytest.mark.unit
def test_get_book_ownership_is_rechecked_even_if_the_row_comes_back() -> None:
    """Defence in depth: if a future refactor drops the user_id predicate, the
    explicit ownership check must still 404 (get_lesson's convention)."""
    sb = _make_supabase_mock(book_row=BOOK_ROW)  # row owned by FAKE_USER
    resp = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}", user=OTHER_USER)
    assert resp.status_code == 404
    assert "ncert_xi_part1.pdf" not in resp.text


@pytest.mark.unit
def test_chapters_of_another_users_book_is_404_with_no_metadata() -> None:
    """AC5 applies to the chapters route too — and it must not fall through to
    returning the chapter rows."""
    sb = _make_supabase_mock(book_row=None, chapter_rows=CHAPTER_ROWS)
    resp = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters", user=OTHER_USER)
    assert resp.status_code == 404
    assert "Physical World" not in resp.text


# ── AC6 — malformed UUID is 404, not 500 ──────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize("bad_id", ["not-a-uuid", "1", "%20", "11111111-1111-1111-1111"])
def test_get_book_malformed_uuid_is_404(bad_id: str) -> None:
    """AC6: matches get_lesson's uuid.UUID() guard (router.py:429-433)."""
    sb = _make_supabase_mock(book_row=BOOK_ROW)
    resp = _get(sb, f"/api/content/books/{bad_id}")
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.parametrize("bad_id", ["not-a-uuid", "1", "11111111-1111-1111-1111"])
def test_chapters_malformed_uuid_is_404(bad_id: str) -> None:
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=CHAPTER_ROWS)
    resp = _get(sb, f"/api/content/books/{bad_id}/chapters")
    assert resp.status_code == 404


@pytest.mark.unit
def test_malformed_uuid_never_reaches_the_database() -> None:
    """A rejected id must not be interpolated into a query at all."""
    sb = _make_supabase_mock(book_row=BOOK_ROW)
    assert _get(sb, "/api/content/books/not-a-uuid").status_code == 404
    assert _tables_touched(sb) == []


# ── AC3 / AC4 — GET /books/{book_id}/chapters ─────────────────────────────────


@pytest.mark.unit
def test_list_chapters_returns_the_documented_shape() -> None:
    """AC3 + AC4."""
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=CHAPTER_ROWS)
    resp = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert set(body[0]) == {
        "chapter_id",
        "chapter_index",
        "title",
        "page_start",
        "page_end",
        "boundary_confidence",
        "lesson_id",
        "has_lesson",
        # Story 1-14 AC15 — a scalar chapters.lesson_id cannot express one
        # chapter with lessons at three tiers; these two can. Kept `==`, never
        # `>=`: an extra key here is a contract change Dev 2 must review.
        "lesson_count",
        "latest_lesson",
        # Story 2-47 (S4-06) AC-1 — every lesson for the chapter, not just the
        # newest. Reviewed and added deliberately, same discipline as above.
        "lessons",
    }
    assert body[0]["chapter_id"] == FAKE_CHAPTER_ID
    assert body[0]["chapter_index"] == 0
    assert body[0]["title"] == "Physical World"
    assert body[0]["page_start"] == 40
    assert body[0]["page_end"] == 68
    assert body[0]["boundary_confidence"] == "toc"


@pytest.mark.unit
def test_list_chapters_scopes_the_embedded_lessons_to_the_caller() -> None:
    """The embed has no RLS behind it (service-role client), so the `user_id`
    predicate is the only thing keeping another user's lessons out of this book
    owner's chapter cards. Dropping it is invisible today — `lessons.user_id`
    always equals the book owner because the generate endpoint is the sole
    writer — and becomes a cross-tenant leak the moment a second writer exists
    (admin regenerate, shared book, backfill).
    """
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=CHAPTER_ROWS)
    _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters")

    filters = dict(sb.chapters_filters)
    assert filters.get("book_id") == FAKE_BOOK_ID
    assert filters.get("lessons.user_id") == FAKE_USER["sub"], (
        "the embedded lessons must be scoped to the caller, not merely to the book"
    )


@pytest.mark.unit
def test_list_chapters_is_ordered_by_chapter_index() -> None:
    """AC3: ordered by chapter_index — asserted on the query, since the mock
    cannot sort for us."""
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=CHAPTER_ROWS)
    resp = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters")

    assert resp.status_code == 200
    # `.eq()` now returns the SAME chain object (it is called twice — book_id and
    # the embedded lessons.user_id scoping), so `order` hangs off the chain rather
    # than off `eq.return_value`.
    chain = sb.table("chapters").select.return_value
    assert ("book_id", FAKE_BOOK_ID) in sb.chapters_filters
    chain.order.assert_called_once_with("chapter_index")
    assert [c["chapter_index"] for c in resp.json()] == [0, 1]


@pytest.mark.unit
def test_list_chapters_lesson_id_and_has_lesson_ship_now() -> None:
    """AC4 + Story 1-14 AC15: a chapter with no lessons yields (None, False, 0).

    An empty embed is the NORMAL state — every chapter of a freshly ingested
    book is here. A bare `row["lessons"][0]` would 500 the whole chapter list
    for that book, so the empty-list unwrap is load-bearing, not defensive
    decoration.
    """
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=CHAPTER_ROWS)
    body = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters").json()
    assert body[0]["lesson_id"] is None
    assert body[0]["has_lesson"] is False
    assert body[0]["lesson_count"] == 0
    assert body[0]["latest_lesson"] is None


@pytest.mark.unit
def test_list_chapters_has_lesson_is_true_once_a_lesson_exists() -> None:
    """INVERTED for Story 1-14 AC14/AC15.

    This test used to assert `has_lesson` is derived from a scalar
    `chapters.lesson_id`, "already correct the moment Phase 6 starts writing
    it". Phase 6 never writes it: that FK is ON DELETE CASCADE
    (20260611000000:132), so pointing a chapter at a lesson and later rolling
    the lesson back deletes the chapter and every chunk under it.

    The new invariant, which is what this now protects: both fields are derived
    from the EMBEDDED `lessons` array, and `chapters.lesson_id` is never read.
    The row below carries a stale scalar `lesson_id` alongside an empty embed —
    exactly what a legacy row looks like — and the response must ignore it.
    """
    lesson = _lesson(FAKE_LESSON_ID, created_at="2026-08-03T10:00:00Z")
    rows = [
        {**CHAPTER_ROWS[0], "lessons": [lesson]},
        # Legacy scalar set, no lesson actually linked → must still read false.
        {**CHAPTER_ROWS[1], "lesson_id": FAKE_LESSON_ID, "lessons": []},
    ]
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=rows)
    body = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters").json()

    assert body[0]["lesson_id"] == FAKE_LESSON_ID
    assert body[0]["has_lesson"] is True
    assert body[0]["lesson_count"] == 1
    assert body[0]["latest_lesson"] == lesson

    assert body[1]["has_lesson"] is False, "chapters.lesson_id is dead and must not be read"
    assert body[1]["lesson_id"] is None
    assert body[1]["lesson_count"] == 0
    assert body[1]["latest_lesson"] is None


@pytest.mark.unit
def test_list_chapters_reports_every_tier_and_the_newest_lesson() -> None:
    """Story 1-14 AC15: the case a scalar column could never express.

    One chapter, two lessons at different tiers: `lesson_count == 2` and
    `latest_lesson` is the newer by `created_at`. Order is asserted against a
    row where the newer lesson arrives SECOND, so "take element 0" fails.
    """
    older = _lesson(
        "33333333-3333-3333-3333-333333333333", tier="T1", created_at="2026-08-01T09:00:00Z"
    )
    newer = _lesson(
        FAKE_LESSON_ID, tier="T3", status="generating", created_at="2026-08-03T18:30:00Z"
    )
    rows = [{**CHAPTER_ROWS[0], "lessons": [older, newer]}, CHAPTER_ROWS[1]]
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=rows)
    body = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters").json()

    assert body[0]["lesson_count"] == 2
    # `newer` is the DB row; the response maps `status` into the client
    # vocabulary, so compare every other field verbatim and the status mapped.
    assert body[0]["latest_lesson"] == {**newer, "status": "running"}
    assert body[0]["lesson_id"] == FAKE_LESSON_ID, "lesson_id now means the NEWEST lesson"
    assert body[0]["has_lesson"] is True
    # AC15: status travels with latest_lesson so Dev 2 does not render a
    # "Watch" button for a chapter whose newest lesson is still generating.
    #
    # It is the MAPPED status: `lessons.status` is generating|ready|failed, but
    # every lesson-facing response in this API is queued|running|ready|failed
    # (`LessonStatusResponse`). Returning the raw column here would hand Dev 2
    # 'generating' from the chapter card and 'running' from `GET /lessons` for
    # the same lesson, so a status switch matching on 'running' would silently
    # fall through on chapter cards only.
    assert body[0]["latest_lesson"]["status"] == "running"


@pytest.mark.unit
def test_list_chapters_latest_lesson_is_newest_when_the_newer_arrives_first() -> None:
    """Same invariant, opposite input order — kills a `[-1]` implementation the
    test above would let through."""
    newer = _lesson(FAKE_LESSON_ID, tier="T3", created_at="2026-08-03T18:30:00Z")
    older = _lesson(
        "33333333-3333-3333-3333-333333333333", tier="T1", created_at="2026-08-01T09:00:00Z"
    )
    rows = [{**CHAPTER_ROWS[0], "lessons": [newer, older]}, CHAPTER_ROWS[1]]
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=rows)
    body = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters").json()

    assert body[0]["lesson_count"] == 2
    assert body[0]["latest_lesson"] == newer


@pytest.mark.unit
def test_list_chapters_lessons_field_lists_every_lesson_newest_first() -> None:
    """AC-1 (Story 2-47): `lessons` carries every lesson for the chapter, not
    just the newest — newest-first, status-mapped the same way `latest_lesson`
    already is (DB `generating` -> API `running`)."""
    older = _lesson(
        "33333333-3333-3333-3333-333333333333", tier="T1", created_at="2026-08-01T09:00:00Z"
    )
    newer = _lesson(
        FAKE_LESSON_ID, tier="T3", status="generating", created_at="2026-08-03T18:30:00Z"
    )
    rows = [{**CHAPTER_ROWS[0], "lessons": [older, newer]}, CHAPTER_ROWS[1]]
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=rows)
    body = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters").json()

    assert body[0]["lessons"] == [{**newer, "status": "running"}, older]
    # Unrelated chapter with zero lessons still returns an empty list, not null.
    assert body[1]["lessons"] == []


@pytest.mark.unit
def test_list_chapters_lessons_field_capped_at_20_newest_lesson_count_unaffected() -> None:
    """AC-2 (Story 2-47, Scale & Load): the exposed `lessons` list is capped at
    20 (newest-first) as a safety ceiling — `lesson_count` still reports the
    TRUE total past the cap, so the discrepancy is visible in the data, not
    hidden."""
    lessons = [
        _lesson(f"lesson-{i:02d}", tier="T1", created_at=f"2026-08-01T{i:02d}:00:00Z")
        for i in range(23)
    ]
    rows = [{**CHAPTER_ROWS[0], "lessons": lessons}, CHAPTER_ROWS[1]]
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=rows)
    body = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters").json()

    assert body[0]["lesson_count"] == 23, "the TRUE total, not the capped list length"
    assert len(body[0]["lessons"]) == 20
    # Newest-first: created_at desc means lesson-22 down to lesson-03 survive.
    assert [item["lesson_id"] for item in body[0]["lessons"]] == [
        f"lesson-{i:02d}" for i in range(22, 2, -1)
    ]


@pytest.mark.unit
def test_list_chapters_lessons_field_exactly_20_returns_all_uncapped() -> None:
    """Review fix (Story 2-47 /bmad-code-review): boundary test at exactly the
    cap — 20 lessons must all survive, not 19 (off-by-one under) or 20 minus
    the newest (wrong end trimmed)."""
    lessons = [
        _lesson(f"lesson-{i:02d}", tier="T1", created_at=f"2026-08-01T{i:02d}:00:00Z")
        for i in range(20)
    ]
    rows = [{**CHAPTER_ROWS[0], "lessons": lessons}, CHAPTER_ROWS[1]]
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=rows)
    body = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters").json()

    assert body[0]["lesson_count"] == 20
    assert len(body[0]["lessons"]) == 20
    assert [item["lesson_id"] for item in body[0]["lessons"]] == [
        f"lesson-{i:02d}" for i in range(19, -1, -1)
    ]


@pytest.mark.unit
def test_list_chapters_lessons_field_exactly_21_drops_only_the_single_oldest() -> None:
    """Review fix: one lesson past the cap must drop exactly the oldest one —
    `lesson-00` — and nothing else."""
    lessons = [
        _lesson(f"lesson-{i:02d}", tier="T1", created_at=f"2026-08-01T{i:02d}:00:00Z")
        for i in range(21)
    ]
    rows = [{**CHAPTER_ROWS[0], "lessons": lessons}, CHAPTER_ROWS[1]]
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=rows)
    body = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters").json()

    assert body[0]["lesson_count"] == 21
    ids = [item["lesson_id"] for item in body[0]["lessons"]]
    assert len(ids) == 20
    assert "lesson-00" not in ids, "the single oldest lesson must be the one dropped"
    assert ids == [f"lesson-{i:02d}" for i in range(20, 0, -1)]


@pytest.mark.unit
def test_list_chapters_lessons_skips_a_row_missing_lesson_id() -> None:
    """Review fix: a malformed row with no `lesson_id` must be skipped from
    `lessons`, not surfaced as a phantom entry, and must not throw."""
    malformed = {"status": "ready", "tier": "T1", "created_at": "2026-08-05T00:00:00Z"}
    valid = _lesson(FAKE_LESSON_ID, tier="T2", created_at="2026-08-01T00:00:00Z")
    rows = [{**CHAPTER_ROWS[0], "lessons": [malformed, valid]}, CHAPTER_ROWS[1]]
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=rows)
    body = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters").json()

    assert body[0]["lessons"] == [valid]
    # lesson_count counts EVERY embedded row including malformed ones — it is
    # the true total, not the post-filter count (matches the cap semantics).
    assert body[0]["lesson_count"] == 2


@pytest.mark.unit
def test_list_chapters_latest_lesson_always_equals_lessons_first_entry() -> None:
    """Review fix (Story 2-47 /bmad-code-review, Edge Case Hunter): `latest_lesson`
    must be derived from the same sort as `lessons`, not computed independently —
    otherwise a row with the newest `created_at` but no `lesson_id` could make
    `latest_lesson` and `lessons[0]` diverge (previously: `latest_lesson` fell
    through to None entirely in this exact case, even though a valid older
    lesson existed)."""
    newest_but_malformed = {
        "status": "ready",
        "tier": "T3",
        "created_at": "2026-08-05T00:00:00Z",
    }
    valid = _lesson(FAKE_LESSON_ID, tier="T1", created_at="2026-08-01T00:00:00Z")
    rows = [{**CHAPTER_ROWS[0], "lessons": [newest_but_malformed, valid]}, CHAPTER_ROWS[1]]
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=rows)
    body = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters").json()

    assert body[0]["lessons"] == [valid]
    assert body[0]["latest_lesson"] == valid, "must fall back to the newest VALID lesson"
    assert body[0]["latest_lesson"] == body[0]["lessons"][0]


@pytest.mark.unit
def test_list_chapters_of_an_own_book_with_no_chapters_is_empty_200() -> None:
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=[])
    resp = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.unit
def test_list_chapters_404_when_the_book_does_not_exist() -> None:
    sb = _make_supabase_mock(book_row=None, chapter_rows=CHAPTER_ROWS)
    resp = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters")
    assert resp.status_code == 404


# ── AC10 / binding rule 4 — every named column must exist in the migrations ───
#
# D9: naming `completed_at` (a lesson_jobs column) in the lessons select list
# made PostgREST reject the WHOLE query with 42703 for every user on every
# request. A Supabase mock has no Postgres catalog and cannot 42703, so the
# select lists are asserted against the migration SQL that defines the tables.

_MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "supabase" / "migrations"


def _columns_of(table: str) -> set[str]:
    """Parse `CREATE TABLE public.<table> (...)` plus every later
    `ALTER TABLE public.<table> ADD COLUMN ...` out of the migration chain."""
    columns: set[str] = set()
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        sql = re.sub(r"--[^\n]*", "", sql)  # strip comments — they mention columns too

        create = re.search(
            rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?public\.{table}\s*\((.*?)\n\s*\);",
            sql,
            re.IGNORECASE | re.DOTALL,
        )
        if create:
            depth = 0
            for line in create.group(1).splitlines():
                stripped = line.strip()
                if (
                    depth == 0
                    and stripped
                    and not stripped.upper().startswith(
                        ("PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT")
                    )
                ):
                    columns.add(stripped.split()[0].strip('",'))
                depth += line.count("(") - line.count(")")

        for alter in re.finditer(
            rf"ALTER\s+TABLE\s+public\.{table}\s+(.*?);", sql, re.IGNORECASE | re.DOTALL
        ):
            for add in re.finditer(
                r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)",
                alter.group(1),
                re.IGNORECASE,
            ):
                columns.add(add.group(1))
    return columns


# Story 1-14 AC6 — the exact key set of the `lessons` INSERT in
# `generate_chapter_lesson`. It lives HERE, next to the migration parser, and is
# imported by tests/unit/test_generate_lesson_endpoint.py rather than retyped
# there, so the payload assertion and the schema assertion can never drift apart.
# That import is what makes the `# MOCK-CONTRACT:` marker on the payload test
# name a partner that really exists (binding rule 2).
LESSONS_INSERT_KEYS: frozenset[str] = frozenset(
    {
        "user_id",
        "book_id",
        "chapter_id",
        "tier",
        "status",
        "title",
        "source_file_path",
    }
)


@pytest.mark.unit
def test_migration_parser_finds_known_columns() -> None:
    """Premise assertion: the parser above must actually work, otherwise the two
    guards below pass vacuously.

    Story 1-14 extends this to `lessons`, which is the table the generate
    endpoint INSERTs into. `lessons` gains columns across FOUR migrations
    (20260611000000 base, 20260625000000 book_id, 20260714020000 tier,
    20260803000000 chapter_id), so a parser that stopped after the CREATE TABLE
    would report `tier` and `chapter_id` as non-existent and the AC6 guard below
    would fail for the wrong reason.
    """
    books = _columns_of("books")
    chapters = _columns_of("chapters")
    lessons = _columns_of("lessons")
    assert {"book_id", "user_id", "filename", "page_count", "status", "created_at"} <= books
    assert "completed_at" not in books
    assert {
        "chapter_id",
        "book_id",
        "lesson_id",
        "title",
        "page_start",
        "page_end",
        "chapter_index",
        "boundary_confidence",
    } <= chapters
    # The four-migration accumulation, named explicitly: `tier` and `chapter_id`
    # are ALTER-added, so they prove the ALTER branch of the parser runs.
    assert {"lesson_id", "user_id", "title", "status", "source_file_path"} <= lessons
    assert {"book_id", "tier", "chapter_id"} <= lessons, (
        f"the parser did not pick up the ALTER-added lessons columns — got {sorted(lessons)}"
    )
    # D9's shape: these read like lesson fields and are NOT columns on `lessons`.
    # `completed_at` and `error` live on `lesson_jobs`; `subject` is a JSONB
    # metadata key; `session_id` does not exist anywhere on this table.
    assert not ({"error", "completed_at", "session_id", "subject"} & lessons)


@pytest.mark.unit
def test_the_generate_endpoints_lessons_insert_names_only_real_columns() -> None:
    """Story 1-14 AC6, the real-dependency half.

    `tests/unit/test_generate_lesson_endpoint.py` asserts that the INSERT payload
    has exactly these keys — but it asserts that against a Supabase double it
    built itself, which has no Postgres catalog and cannot 42703. This test is
    the partner its `# MOCK-CONTRACT:` marker names: it checks the same key set
    against the migration SQL that actually defines the table.

    What breaks in production if this fails: PostgREST rejects the WHOLE INSERT
    with `42703 column lessons.<name> does not exist` — so no student can
    generate any lesson from any chapter, all at once, and the unit suite stays
    green because a mock accepts any key. That is the D9 outage shape.
    """
    lessons = _columns_of("lessons")
    assert lessons, "no CREATE TABLE public.lessons found in supabase/migrations/"
    missing = sorted(LESSONS_INSERT_KEYS - lessons)
    assert not missing, (
        f"generate_chapter_lesson's INSERT names {missing}, which are not columns "
        f"on public.lessons (parsed: {sorted(lessons)})"
    )


def _split_top_level(select: str) -> list[str]:
    """Split on commas that are NOT inside an embed's parentheses."""
    parts: list[str] = []
    depth = 0
    buf = ""
    for ch in select:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(buf)
            buf = ""
            continue
        buf += ch
    if buf.strip():
        parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def _select_pairs(select: str, base_table: str) -> list[tuple[str, str]]:
    """Resolve a PostgREST select list into `(table, column)` pairs.

    Story 1-14 (AC19). Both guards below used to `split(",")`, which shreds an
    embed — `lessons!lessons_chapter_id_fkey(lesson_id,status)` becomes three
    nonsense fragments — so adding AC15's embed would have made them fail on
    SYNTAX rather than on a real defect. That is precisely the failure that
    tempts a reviewer to delete a guard. Teaching them to parse instead means
    strictly MORE names are validated against `supabase/migrations/` than
    before: outer names against the base table, and every name inside an embed
    against the EMBEDDED table.

    PostgREST features handled, all of which already appear in these lists:
      * alias            `subject:content->metadata->>subject`
      * JSON path        `content->metadata->>subject` (head of the path is the
                         real column; `->`/`->>` operands are JSON keys)
      * embed            `alias:table!constraint(col,col)`
      * embed aggregate  `chapters(count)` — `count` is a PostgREST aggregate,
                         not a column, so it is not looked up.
    """
    pairs: list[tuple[str, str]] = []
    for spec in _split_top_level(select):
        if "(" in spec:
            head, _, inner = spec.partition("(")
            inner = inner.rstrip().removesuffix(")")
            target = head.split(":", 1)[1] if ":" in head else head  # drop `alias:`
            embedded = target.split("!", 1)[0].strip()  # drop `!constraint`
            for nested in _split_top_level(inner):
                if nested == "count":  # PostgREST aggregate, not a column
                    continue
                pairs.extend(_select_pairs(nested, embedded))
            continue
        source = spec.split(":", 1)[1] if ":" in spec else spec  # drop `alias:`
        pairs.append((base_table, source.split("->", 1)[0].strip()))  # head of JSON path
    return pairs


@pytest.mark.unit
def test_select_pair_parser_understands_embeds() -> None:
    """Premise assertion (binding rule 3): a parser that silently returns [] or
    that mis-attributes an embedded name would make both guards below pass
    vacuously — the same class of bug as a scanner that matches nothing."""
    assert _select_pairs("a,b:c->d->>e", "books") == [("books", "a"), ("books", "c")]
    assert _select_pairs(
        "chapter_id,lessons!lessons_chapter_id_fkey(lesson_id,tier)", "chapters"
    ) == [
        ("chapters", "chapter_id"),
        ("lessons", "lesson_id"),
        ("lessons", "tier"),
    ]
    assert _select_pairs("book_id,chapters(count)", "books") == [("books", "book_id")]
    # aliased embed: `chapter:chapters!...` resolves to the chapters table
    assert _select_pairs("chapter:chapters!lessons_chapter_id_fkey(title)", "lessons") == [
        ("chapters", "title")
    ]


def _assert_every_name_is_a_real_column(select: str, base_table: str, const_name: str) -> None:
    cache: dict[str, set[str]] = {}
    pairs = _select_pairs(select, base_table)
    assert pairs, f"{const_name} parsed to nothing — the guard would pass vacuously"
    for table, column in pairs:
        real = cache.setdefault(table, _columns_of(table))
        assert real, f"no CREATE TABLE public.{table} found in supabase/migrations/"
        assert column in real, (
            f"{const_name} names {column!r}, which is not a column on public.{table}"
        )


@pytest.mark.unit
def test_book_select_names_no_column_absent_from_books() -> None:
    """D9/D37: an unknown column name 42703s the whole endpoint for every user."""
    from app.modules.content.router import _BOOK_COLUMNS

    _assert_every_name_is_a_real_column(_BOOK_COLUMNS, "books", "_BOOK_COLUMNS")


@pytest.mark.unit
def test_chapter_select_names_no_column_absent_from_chapters() -> None:
    """Story 1-14 AC15: `_CHAPTER_COLUMNS` now embeds `lessons`, so the embedded
    names are validated against public.lessons — a bogus one there 42703s the
    chapter list exactly as a bogus chapters column would."""
    from app.modules.content.router import _CHAPTER_COLUMNS

    _assert_every_name_is_a_real_column(_CHAPTER_COLUMNS, "chapters", "_CHAPTER_COLUMNS")


@pytest.mark.unit
def test_book_embed_targets_a_real_relationship() -> None:
    """`chapters(count)` relies on the chapters.book_id → books.book_id FK added
    by 20260625000000; without it PostgREST answers PGRST200, not a count."""
    from app.modules.content.router import _BOOK_SELECT

    assert "chapters(count)" in _BOOK_SELECT
    fk_sql = "".join(p.read_text(encoding="utf-8") for p in sorted(_MIGRATIONS_DIR.glob("*.sql")))
    assert re.search(
        r"ALTER\s+TABLE\s+public\.chapters\s+ADD\s+CONSTRAINT\s+chapters_book_id_fkey\s+"
        r"FOREIGN\s+KEY\s*\(\s*book_id\s*\)\s+REFERENCES\s+public\.books",
        fk_sql,
        re.IGNORECASE,
    ), "the embedded chapters(count) needs the chapters.book_id FK to exist"


# ── Response models live local to the module, not in the frozen contract ──────


@pytest.mark.unit
def test_response_models_are_module_local_not_shared_contract() -> None:
    """T1: packages/shared is a frozen 4-dev-review contract and needs no change."""
    from app.modules.content.schemas import BookResponse, ChapterResponse

    assert BookResponse.__module__ == "app.modules.content.schemas"
    assert ChapterResponse.__module__ == "app.modules.content.schemas"
