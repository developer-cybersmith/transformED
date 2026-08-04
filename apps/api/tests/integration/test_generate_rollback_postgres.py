"""Story 1-14 AC10 — the generate endpoint's rollback, executed against real Postgres.

WHY THIS FILE EXISTS

AC10 says the rollback must delete `lesson_jobs` then `lessons` and touch nothing
else. Read as prose that is a style preference. Read against a real FK graph it is
a data-loss guard, because of one edge in the schema:

    chapters.lesson_id → lessons.lesson_id   ON DELETE CASCADE   (20260611000000:132)
    chunks.chapter_id  → chapters.chapter_id ON DELETE CASCADE   (20260611000000:147)

So the "obvious" implementation — insert the lesson, point the chapter at it via
`chapters.lesson_id`, then roll the lesson back when the ARQ enqueue fails —
**deletes the chapter and every chunk and embedding under it**. A whole book's
ingestion destroyed by one failed generation. That is the hazard AC14 forbids by
saying `chapters.lesson_id` is dead and stays dead.

A Supabase mock has no FK engine (binding rule 4). It passes whether the rollback
is correct or catastrophic, which makes every mock-level rollback test in this
story conditional on this file. Both directions are asserted here:

  * the rollback the story mandates leaves books / chapters / chunks intact
  * the rollback the story FORBIDS really does cascade the chapter away — proven
    inside a transaction that is rolled back, so AC14's prohibition is executable
    rather than a comment nobody can fail

SQL is driven through `docker exec ... psql` rather than a Python driver: no PG
driver is installed in this venv and adding one to satisfy a test is a dependency
change this story does not authorise. The same reasoning as
`test_migration_chapters_book_scoped.py`, which shells out to a psql binary.

Run:
    cd apps/api
    python -m pytest tests/integration/test_generate_rollback_postgres.py -v -m postgres
"""

from __future__ import annotations

import subprocess
import uuid
from collections.abc import Iterator

import pytest

# The migrated Postgres container, and the provisioning that guarantees there IS
# one. Imported rather than duplicated: `ensure_postgrest_stack()` reuses a
# developer's running stack and otherwise brings up its own Postgres + PostgREST,
# so this suite executes on a CI runner instead of skipping. A skip does not
# satisfy an AC (Story 1-14 AC24), and a CI step cannot tell a partial skip from
# a pass. Two modules calling it share one container — it is idempotent.
from tests.integration import test_book_select_lists_against_postgrest as pgrst_harness
from tests.integration.test_book_select_lists_against_postgrest import ensure_postgrest_stack

pytestmark = pytest.mark.postgres


def _psql(statement: str) -> subprocess.CompletedProcess[str]:
    # Container/database names are read from the harness module at CALL time:
    # self-provisioning rebinds them, so capturing them at import would address a
    # container that does not exist.
    return subprocess.run(  # noqa: S603
        [  # noqa: S607
            "docker",
            "exec",
            "-i",
            pgrst_harness.LOCAL_DB_CONTAINER,
            "psql",
            "-U",
            "postgres",
            "-d",
            pgrst_harness.LOCAL_DB_NAME,
            "-v",
            "ON_ERROR_STOP=1",
            "-q",
            "-t",
            "-A",
            "-c",
            statement,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )


def scalar(statement: str) -> str:
    res = _psql(statement)
    assert res.returncode == 0, f"query failed: {res.stderr[:500]}"
    return res.stdout.strip()


def lines(statement: str) -> list[str]:
    res = _psql(statement)
    assert res.returncode == 0, f"query failed: {res.stderr[:500]}"
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


@pytest.fixture(scope="session", autouse=True)
def require_postgres() -> None:
    """Reuse or provision a migrated Postgres; skip ONLY if Docker is missing.

    Never at collection time — Story 1-12's lesson is that `skipif` is evaluated
    at COLLECTION, so a module-level marker would decide before anything could be
    provisioned, and a later fixture could not un-skip it.
    """
    ensure_postgrest_stack()
    probe = _psql("SELECT 1")
    assert probe.returncode == 0, (
        f"container {pgrst_harness.LOCAL_DB_CONTAINER!r} is up but has no migrated "
        f"schema: {probe.stderr[:400]}"
    )


# ════════════════════════════════════════════════════════════════════════════
# Premise — the FK graph really is the one this file reasons about
# ════════════════════════════════════════════════════════════════════════════
def test_the_cascade_edges_this_file_depends_on_are_present() -> None:
    """Binding rule 3. Every assertion below is about ON DELETE behaviour; if the
    actions were not what we think, both the "safe" and the "catastrophic" test
    would pass for the wrong reason. 'c' = CASCADE, 'n' = SET NULL."""
    got = dict(
        line.split("|", 1)
        for line in lines(
            "SELECT conname||'|'||confdeltype::text FROM pg_constraint WHERE contype='f' "
            "AND conname IN ('chapters_lesson_id_fkey','lessons_chapter_id_fkey',"
            "'chunks_chapter_id_fkey','lesson_jobs_lesson_id_fkey')"
        )
    )
    assert got == {
        # the hazard: a chapter pointed at a lesson dies with that lesson
        "chapters_lesson_id_fkey": "c",
        # ... and takes its chunks with it
        "chunks_chapter_id_fkey": "c",
        # the safe direction Phase 6 writes: the chapter outlives the lesson
        "lessons_chapter_id_fkey": "n",
        # the rollback's child row
        "lesson_jobs_lesson_id_fkey": "c",
    }, f"FK delete actions are not what AC10/AC14 assume: {got}"


# ════════════════════════════════════════════════════════════════════════════
# Fixture — one book, one chapter, two chunks, one lesson, one lesson_jobs row
# ════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def ingested() -> Iterator[dict[str, str]]:
    """The state AFTER a successful book ingestion and the two INSERTs of AC6/AC8,
    immediately BEFORE the enqueue that is about to fail.

    Note what is NOT set: `chapters.lesson_id` stays NULL. That is AC14, and it is
    what makes the rollback below survivable.
    """
    ids = {
        k: str(uuid.uuid4())
        for k in ("user", "book", "chapter", "chunk_a", "chunk_b", "lesson", "job")
    }
    seed = _psql(f"""
        INSERT INTO auth.users (id, email)
          VALUES ('{ids["user"]}', 'ac10-{ids["user"]}@example.test');
        INSERT INTO public.books (book_id, user_id, filename, status, page_count)
          VALUES ('{ids["book"]}', '{ids["user"]}', 'ac10 rollback.pdf', 'ready', 120);
        INSERT INTO public.chapters
          (chapter_id, book_id, lesson_id, title, page_start, page_end, chapter_index)
          VALUES ('{ids["chapter"]}', '{ids["book"]}', NULL, 'AC10 ch', 1, 40, 9201);
        INSERT INTO public.chunks (chunk_id, chapter_id, content, chunk_index) VALUES
          ('{ids["chunk_a"]}', '{ids["chapter"]}', 'ac10 chunk one', 0),
          ('{ids["chunk_b"]}', '{ids["chapter"]}', 'ac10 chunk two', 1);
        INSERT INTO public.lessons
          (lesson_id, user_id, title, book_id, chapter_id, tier, status, source_file_path)
          VALUES ('{ids["lesson"]}', '{ids["user"]}', 'AC10 lesson', '{ids["book"]}',
                  '{ids["chapter"]}', 'T1', 'generating',
                  '{ids["user"]}/{ids["book"]}/ac10 rollback.pdf');
        INSERT INTO public.lesson_jobs (job_id, lesson_id, status)
          VALUES ('{ids["job"]}', '{ids["lesson"]}', 'pending');
        """)
    if seed.returncode != 0:
        pytest.skip(f"could not seed the shared Postgres container: {seed.stderr[:400]}")
    try:
        yield ids
    finally:
        cleanup = _psql(f"DELETE FROM auth.users WHERE id = '{ids['user']}'")
        assert cleanup.returncode == 0, (
            f"rollback-test rows were left behind in a SHARED container: {cleanup.stderr[:400]}"
        )


def _counts(ids: dict[str, str]) -> dict[str, int]:
    row = scalar(
        f"SELECT (SELECT count(*) FROM public.books    WHERE book_id='{ids['book']}')||'|'"
        f"     ||(SELECT count(*) FROM public.chapters WHERE chapter_id='{ids['chapter']}')||'|'"
        f"     ||(SELECT count(*) FROM public.chunks   WHERE chapter_id='{ids['chapter']}')||'|'"
        f"     ||(SELECT count(*) FROM public.lessons  WHERE lesson_id='{ids['lesson']}')||'|'"
        f"     ||(SELECT count(*) FROM public.lesson_jobs WHERE lesson_id='{ids['lesson']}')"
    )
    books, chapters, chunks, lessons, jobs = (int(part) for part in row.split("|"))
    return {
        "books": books,
        "chapters": chapters,
        "chunks": chunks,
        "lessons": lessons,
        "lesson_jobs": jobs,
    }


# ════════════════════════════════════════════════════════════════════════════
# AC10 — the mandated rollback destroys nothing it did not create
# ════════════════════════════════════════════════════════════════════════════
def test_the_rollback_removes_only_the_lesson_and_its_job(ingested: dict[str, str]) -> None:
    """AC10, executed. `lesson_jobs` (child) then `lessons` (parent), each under
    `contextlib.suppress(Exception)` in the router; the SQL below is that pair.

    The row that matters is `chunks`: it is two FK hops from the lesson, so no
    reviewer reading the delete statements sees it, and no mock can show it
    disappearing.
    """
    assert _counts(ingested) == {
        "books": 1,
        "chapters": 1,
        "chunks": 2,
        "lessons": 1,
        "lesson_jobs": 1,
    }, "the fixture did not produce the pre-rollback state"

    rollback = _psql(
        f"DELETE FROM public.lesson_jobs WHERE lesson_id = '{ingested['lesson']}';"
        f"DELETE FROM public.lessons     WHERE lesson_id = '{ingested['lesson']}';"
    )
    assert rollback.returncode == 0, f"the rollback itself failed: {rollback.stderr[:400]}"

    assert _counts(ingested) == {
        "books": 1,
        "chapters": 1,
        "chunks": 2,
        "lessons": 0,
        "lesson_jobs": 0,
    }, "the rollback destroyed rows this request did not create"


def test_the_rolled_back_book_and_chapter_are_unmodified_not_merely_present(
    ingested: dict[str, str],
) -> None:
    """`count(*) == 1` would also pass if the rollback had blanked the row's
    contents — `books.status` reset to 'processing', or the chapter's page range
    lost, either of which silently breaks a later regeneration. Assert the values.

    The storage object itself (AC10 also forbids `storage.remove(...)`) is not
    observable from Postgres; what is observable, and what the worker actually
    reads, is that `source_file_path` was reconstructible from an untouched
    `books.filename` — so that is asserted here and the object itself belongs to
    the AC20 live run.
    """
    before = scalar(
        "SELECT b.filename||'|'||b.status||'|'||b.page_count||'|'||c.title||'|'"
        "||c.page_start||'|'||c.page_end||'|'||c.boundary_confidence||'|'"
        "||coalesce(c.lesson_id::text,'NULL') "
        "FROM public.books b JOIN public.chapters c ON c.book_id = b.book_id "
        f"WHERE b.book_id = '{ingested['book']}'"
    )
    assert before == "ac10 rollback.pdf|ready|120|AC10 ch|1|40|fallback|NULL"

    assert (
        _psql(
            f"DELETE FROM public.lesson_jobs WHERE lesson_id = '{ingested['lesson']}';"
            f"DELETE FROM public.lessons     WHERE lesson_id = '{ingested['lesson']}';"
        ).returncode
        == 0
    )

    after = scalar(
        "SELECT b.filename||'|'||b.status||'|'||b.page_count||'|'||c.title||'|'"
        "||c.page_start||'|'||c.page_end||'|'||c.boundary_confidence||'|'"
        "||coalesce(c.lesson_id::text,'NULL') "
        "FROM public.books b JOIN public.chapters c ON c.book_id = b.book_id "
        f"WHERE b.book_id = '{ingested['book']}'"
    )
    assert after == before, f"the rollback mutated the book/chapter row: {before!r} -> {after!r}"

    bodies = lines(
        f"SELECT content FROM public.chunks WHERE chapter_id = '{ingested['chapter']}' "
        "ORDER BY chunk_index"
    )
    assert bodies == ["ac10 chunk one", "ac10 chunk two"], (
        f"chunk bodies did not survive the rollback: {bodies}"
    )


def test_the_delete_order_is_defensive_not_load_bearing(ingested: dict[str, str]) -> None:
    """A premise worth recording, because someone WILL "simplify" AC10's two
    statements into one.

    `lesson_jobs.lesson_id` is ON DELETE CASCADE, so deleting the parent alone
    also removes the job. The child-first order is therefore defensive — it is
    what keeps the rollback correct if that cascade is ever downgraded, and it
    means neither statement can fail on a dangling child. Asserting this stops a
    future reviewer from "discovering" the cascade and concluding the story's
    ordering was cargo cult.
    """
    assert (
        _psql(f"DELETE FROM public.lessons WHERE lesson_id = '{ingested['lesson']}'").returncode
        == 0
    )
    counts = _counts(ingested)
    assert counts["lessons"] == 0
    assert counts["lesson_jobs"] == 0, "lesson_jobs did not cascade from lessons"
    assert counts["chapters"] == 1
    assert counts["chunks"] == 2


# ════════════════════════════════════════════════════════════════════════════
# AC14 — the FORBIDDEN implementation, proven catastrophic
# ════════════════════════════════════════════════════════════════════════════
def test_writing_chapters_lesson_id_makes_the_same_rollback_destroy_the_chapter(
    ingested: dict[str, str],
) -> None:
    """AC14's prohibition, made executable — this is the contrast that gives the
    test above its meaning.

    Identical rollback SQL. The ONLY difference is one `UPDATE chapters SET
    lesson_id = ...` beforehand, which is the "obvious" implementation the story
    forbids. The chapter and both chunks vanish through
    `chapters_lesson_id_fkey ON DELETE CASCADE` → `chunks_chapter_id_fkey ON
    DELETE CASCADE`.

    Run inside BEGIN ... ROLLBACK so the destruction is observed and then undone;
    the assertion after the transaction proves the observation was real and that
    this test left the shared container as it found it.
    """
    destroyed = scalar(f"""
        BEGIN;
        UPDATE public.chapters SET lesson_id = '{ingested["lesson"]}'
          WHERE chapter_id = '{ingested["chapter"]}';
        DELETE FROM public.lesson_jobs WHERE lesson_id = '{ingested["lesson"]}';
        DELETE FROM public.lessons     WHERE lesson_id = '{ingested["lesson"]}';
        SELECT (SELECT count(*) FROM public.books    WHERE book_id='{ingested["book"]}')||'|'
             ||(SELECT count(*) FROM public.chapters WHERE chapter_id='{ingested["chapter"]}')||'|'
             ||(SELECT count(*) FROM public.chunks   WHERE chapter_id='{ingested["chapter"]}');
        ROLLBACK;
        """)
    assert destroyed == "1|0|0", (
        "writing chapters.lesson_id before the rollback did NOT destroy the chapter "
        f"and its chunks (got books|chapters|chunks = {destroyed!r}). If this is now "
        "safe the CASCADE has changed, and AC14's reasoning must be re-derived — do "
        "not delete this test."
    )

    # The transaction was rolled back, so the graph is intact again. Without this
    # the test above could not be distinguished from one that really did destroy
    # the fixture's rows.
    assert _counts(ingested) == {
        "books": 1,
        "chapters": 1,
        "chunks": 2,
        "lessons": 1,
        "lesson_jobs": 1,
    }, "the demonstration transaction was not rolled back — it destroyed real rows"
