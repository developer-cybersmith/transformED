"""
Unit tests for the book/chapter read endpoints (Story 1-11, book-scale Phase 3.5).

Covers AC1-AC6:
  AC1  GET /api/content/books                     — caller's books, newest first
  AC2  GET /api/content/books/{book_id}           — one book, same shape
  AC3  GET /api/content/books/{book_id}/chapters  — ordered by chapter_index
  AC4  lesson_id / has_lesson ship now (null/false until Phase 6)
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

CHAPTER_ROWS: list[dict[str, Any]] = [
    {
        "chapter_id": FAKE_CHAPTER_ID,
        "chapter_index": 0,
        "title": "Physical World",
        "page_start": 40,
        "page_end": 68,
        "boundary_confidence": "toc",
        "lesson_id": None,
    },
    {
        "chapter_id": "55555555-5555-5555-5555-555555555555",
        "chapter_index": 1,
        "title": "Units and Measurements",
        "page_start": 69,
        "page_end": 92,
        "boundary_confidence": "toc",
        "lesson_id": None,
    },
]


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

    chapters_tbl = MagicMock()
    chapters_tbl.select.return_value.eq.return_value.order.return_value.execute.return_value = (
        _resp(chapter_rows if chapter_rows is not None else [])
    )

    table_map = {"books": books_tbl, "chapters": chapters_tbl}
    sb = MagicMock()
    sb.table.side_effect = lambda name: table_map.get(name, MagicMock())
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
    }
    assert body[0]["chapter_id"] == FAKE_CHAPTER_ID
    assert body[0]["chapter_index"] == 0
    assert body[0]["title"] == "Physical World"
    assert body[0]["page_start"] == 40
    assert body[0]["page_end"] == 68
    assert body[0]["boundary_confidence"] == "toc"


@pytest.mark.unit
def test_list_chapters_is_ordered_by_chapter_index() -> None:
    """AC3: ordered by chapter_index — asserted on the query, since the mock
    cannot sort for us."""
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=CHAPTER_ROWS)
    resp = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters")

    assert resp.status_code == 200
    chapters_tbl = sb.table("chapters")
    chapters_tbl.select.return_value.eq.assert_any_call("book_id", FAKE_BOOK_ID)
    chapters_tbl.select.return_value.eq.return_value.order.assert_called_once_with("chapter_index")
    assert [c["chapter_index"] for c in resp.json()] == [0, 1]


@pytest.mark.unit
def test_list_chapters_lesson_id_and_has_lesson_ship_now() -> None:
    """AC4: both fields exist today even though Phase 6 has not landed —
    null/false, not absent."""
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=CHAPTER_ROWS)
    body = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters").json()
    assert body[0]["lesson_id"] is None
    assert body[0]["has_lesson"] is False


@pytest.mark.unit
def test_list_chapters_has_lesson_is_true_once_a_lesson_exists() -> None:
    """AC4: has_lesson is derived from lesson_id, so it is already correct when
    Phase 6 starts writing it."""
    rows_with_lesson = [{**CHAPTER_ROWS[0], "lesson_id": FAKE_LESSON_ID}, CHAPTER_ROWS[1]]
    sb = _make_supabase_mock(book_row=BOOK_ROW, chapter_rows=rows_with_lesson)
    body = _get(sb, f"/api/content/books/{FAKE_BOOK_ID}/chapters").json()
    assert body[0]["lesson_id"] == FAKE_LESSON_ID
    assert body[0]["has_lesson"] is True
    assert body[1]["has_lesson"] is False


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


@pytest.mark.unit
def test_migration_parser_finds_known_columns() -> None:
    """Premise assertion: the parser above must actually work, otherwise the two
    guards below pass vacuously."""
    books = _columns_of("books")
    chapters = _columns_of("chapters")
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


@pytest.mark.unit
def test_book_select_names_no_column_absent_from_books() -> None:
    """D9/D37: an unknown column name 42703s the whole endpoint for every user."""
    from app.modules.content.router import _BOOK_COLUMNS

    real = _columns_of("books")
    for column in _BOOK_COLUMNS.split(","):
        assert column.strip() in real, (
            f"_BOOK_COLUMNS names {column!r}, which is not a column on public.books"
        )


@pytest.mark.unit
def test_chapter_select_names_no_column_absent_from_chapters() -> None:
    from app.modules.content.router import _CHAPTER_COLUMNS

    real = _columns_of("chapters")
    for column in _CHAPTER_COLUMNS.split(","):
        assert column.strip() in real, (
            f"_CHAPTER_COLUMNS names {column!r}, which is not a column on public.chapters"
        )


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
