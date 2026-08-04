"""Every PostgREST select list this app sends, executed against a REAL PostgREST.

WHY THIS EXISTS — it closes a gap two defects are already about.

D9 was an outage: `_LIST_COLUMNS` named `completed_at`, which is a `lesson_jobs`
column and not a `lessons` one, and PostgREST rejected the whole query with
`42703 column lessons.completed_at does not exist` — `GET /lessons` failed for
every user on every request. D37 records that those same JSON-path selectors have
still never been executed against real Postgres, with the enforcement column
reading *"(to add — real-PostgREST integration test)"*. This is that test.

A Supabase mock cannot catch this class of defect by construction: it has no
Postgres catalog, so it can neither raise 42703 nor fail to resolve an embedded
relationship (binding rule 4).

The specific unknown for Story 1-11 was `chapters(count)` — an embedded aggregate.
`books` has three inbound foreign keys (chapters, chunks, lessons), so the
relationship could in principle be ambiguous; only PostgREST can say.

Run:
    cd apps/api
    python -m pytest tests/integration/test_book_select_lists_against_postgrest.py -m postgres
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request

import pytest

pytestmark = pytest.mark.postgres

POSTGREST = os.environ.get("POSTGREST_URL", "http://127.0.0.1:53000")


def _postgrest_up() -> bool:
    try:
        with urllib.request.urlopen(POSTGREST + "/", timeout=5) as r:  # noqa: S310
            return r.status == 200
    except Exception:
        return False


def _docker() -> bool:
    if not __import__("shutil").which("docker"):
        return False
    return (
        subprocess.run(  # noqa: S603
            ["docker", "info"],  # noqa: S607
            capture_output=True,
            timeout=30,
            check=False,
        ).returncode
        == 0
    )


@pytest.fixture(scope="session", autouse=True)
def require_postgrest() -> None:
    """Skip VISIBLY when PostgREST is absent — never silently.

    Bring it up with (the local Postgres container must already be running):

        docker network create pgrst-net
        docker network connect pgrst-net transformed-local-db
        docker run -d --name transformed-local-postgrest --network pgrst-net \\
          -e PGRST_DB_URI=postgres://postgres:localdev@transformed-local-db:5432/transformed \\
          -e PGRST_DB_SCHEMAS=public -e PGRST_DB_ANON_ROLE=anon \\
          -p 127.0.0.1:53000:3000 postgrest/postgrest
    """
    if not _docker():
        pytest.skip("Docker daemon not reachable — cannot verify select lists against PostgREST")
    if not _postgrest_up():
        pytest.skip(f"No PostgREST at {POSTGREST} — see this module's fixture docstring")


def query(path: str) -> tuple[int, str]:
    """Raw PostgREST request. Returns (status, body) rather than raising, because
    the body of a 4xx is the diagnostic — `42703` lives there."""
    req = urllib.request.Request(POSTGREST + path)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def select_list(name: str) -> str:
    """IMPORT the select-list constant from the router — do not re-parse it.

    The first version of this test read the constants out of the source with a
    regex. Two of them are f-strings (`_BOOK_SELECT = f"{_BOOK_COLUMNS},..."`) and
    one name was simply wrong, so the regex found nothing and the test SKIPPED —
    reporting green while verifying nothing. Importing the module gives the exact
    string the app sends at runtime, and a renamed constant becomes an
    AttributeError instead of a silent skip.
    """
    from app.modules.content import router as content_router

    value = getattr(content_router, name, None)
    assert isinstance(value, str) and value, (
        f"{name} is not a string constant on content.router — if it was renamed, "
        f"rename it here too rather than letting this test skip"
    )
    return value


# ════════════════════════════════════════════════════════════════════════════
# Premise — if these fail, every assertion below is meaningless
# ════════════════════════════════════════════════════════════════════════════
def test_postgrest_serves_the_migrated_schema() -> None:
    status, body = query("/books?limit=1")
    assert status == 200, f"PostgREST cannot read `books`: {status} {body[:300]}"


def test_a_bogus_column_really_does_raise_42703() -> None:
    """The trap must be live. If PostgREST tolerated unknown columns, every
    'the select list is valid' assertion below would pass vacuously."""
    status, body = query("/books?select=book_id,column_that_does_not_exist&limit=1")
    assert status >= 400, "PostgREST accepted a nonexistent column — this test proves nothing"
    assert "42703" in body, f"expected 42703, got: {body[:300]}"


# ════════════════════════════════════════════════════════════════════════════
# The select lists this app actually sends
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "const", ["_BOOK_SELECT", "_BOOK_COLUMNS", "_CHAPTER_COLUMNS", "_LIST_COLUMNS"]
)
def test_select_list_is_accepted_by_postgrest(const: str) -> None:
    """Story 1-11 AC10, and D37's missing enforcement.

    `_LIST_COLUMNS` is included deliberately: it is the one D9 broke, and its
    JSON-path selectors (`content->metadata->>subject`) have never been executed
    against a real database until now.
    """
    sel = select_list(const)
    table = {
        "_BOOK_SELECT": "books",
        "_BOOK_COLUMNS": "books",
        "_CHAPTER_COLUMNS": "chapters",
        "_LIST_COLUMNS": "lessons",
    }[const]
    status, body = query(f"/{table}?select={sel}&limit=1")
    assert status == 200, f"{const} rejected by PostgREST on `{table}`: {status} {body[:400]}"


def test_the_chapters_count_embed_resolves_unambiguously() -> None:
    """The specific unknown in Story 1-11.

    `books` has three inbound FKs — chapters, chunks and lessons — so an embedded
    aggregate could in principle be ambiguous, which PostgREST reports as PGRST201
    rather than as a wrong number. Only a real PostgREST can answer this; the unit
    tests mock it away.
    """
    status, body = query("/books?select=book_id,chapters(count)&limit=1")
    assert status == 200, f"the chapters(count) embed failed: {status} {body[:400]}"
    rows = json.loads(body)
    if rows:
        assert "chapters" in rows[0], f"embed produced no `chapters` key: {rows[0]}"
        embedded = rows[0]["chapters"]
        assert isinstance(embedded, list), (
            f"embed shape changed — the router's _embedded_count assumes a list: {embedded!r}"
        )
        if embedded:
            assert "count" in embedded[0], f"aggregate key changed: {embedded[0]}"


def test_chapters_can_be_ordered_by_chapter_index() -> None:
    """AC3 orders by `chapter_index`; an order on a column PostgREST cannot see
    is a 400, not a differently-sorted list."""
    status, body = query(
        "/chapters?select=chapter_id,chapter_index&order=chapter_index.asc&limit=5"
    )
    assert status == 200, f"ordering by chapter_index failed: {status} {body[:300]}"


def test_boundary_confidence_is_selectable() -> None:
    """Phase 2 added the column; Phase 3 writes it; Phase 3.5 returns it. If the
    migration were ever reverted this is where it surfaces, as a 42703."""
    status, body = query("/chapters?select=chapter_id,boundary_confidence&limit=1")
    assert status == 200, f"boundary_confidence not selectable: {status} {body[:300]}"
