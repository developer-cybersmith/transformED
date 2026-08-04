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

import ast
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


# ════════════════════════════════════════════════════════════════════════════
# The rollback under test is the ROUTER'S, not a retyped copy of it
# ════════════════════════════════════════════════════════════════════════════
#
# Review finding this addresses: the SQL below used to be two hand-written
# DELETEs. That makes the test a statement about SQL, not about the endpoint —
# the router could grow a third delete, drop one, reverse the order, or start
# calling `storage.remove(...)`, and every assertion here would still pass while
# describing code that no longer exists. The FK graph would be exercised
# faithfully and the wrong program would be exercised.
#
# So the statements are DERIVED from `generate_chapter_lesson`'s own exception
# handler: its deletes are parsed out of the source, their shape is asserted, and
# the SQL is generated from what was parsed. Adding a `books` delete to the
# router therefore changes what this file executes, and the blast-radius
# assertions catch it.
#
# The AST helpers are imported from the unit suite rather than re-written; they
# carry their own premise tests there, and a second copy is a second chance to
# get `_selected_table` subtly wrong in the file whose whole job is precision.


def _generate_handler() -> ast.FunctionDef | ast.AsyncFunctionDef:
    from tests.unit.test_generate_lesson_endpoint import (
        _executable_tree,
        _find_function,
        _router_path,
    )

    tree = _executable_tree(_router_path().read_text(encoding="utf-8"))
    return _find_function(tree, "generate_chapter_lesson")


def _handler_names(node: ast.Try) -> list[str | None]:
    return [h.type.id if isinstance(h.type, ast.Name) else None for h in node.handlers]


def _rollback_handler() -> ast.ExceptHandler:
    """The `except Exception` arm of `generate_chapter_lesson`'s OUTER try — the
    rollback.

    Identified by the `except HTTPException: raise` arm that sits beside it: that
    re-raise is what distinguishes the outer create-the-work block (where a
    gate's 4xx must pass through untouched) from the small inner try/except pairs
    that isolate each individual delete. Selecting on "the only `except
    Exception` in the function" was correct until D53 replaced
    `contextlib.suppress` with logging try/excepts, and would now match three.
    """
    tries = [
        node
        for node in ast.walk(_generate_handler())
        if isinstance(node, ast.Try) and {"HTTPException", "Exception"} <= set(_handler_names(node))
    ]
    assert len(tries) == 1, (
        f"expected exactly one outer try with both an HTTPException re-raise and "
        f"an Exception rollback arm, found {len(tries)}"
    )
    handlers = [
        h for h in tries[0].handlers if isinstance(h.type, ast.Name) and h.type.id == "Exception"
    ]
    assert len(handlers) == 1
    return handlers[0]


def _parsed_rollback_deletes() -> list[tuple[str, str]]:
    """`[(table, filter_column), ...]` in SOURCE ORDER, read off the router."""
    from tests.unit.test_generate_lesson_endpoint import _selected_table

    found: list[tuple[int, str, str]] = []
    for node in ast.walk(_rollback_handler()):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "eq":
            continue
        inner = node.func.value
        if not (
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Attribute)
            and inner.func.attr == "delete"
        ):
            continue
        table = _selected_table(inner.func.value)
        column = node.args[0] if node.args else None
        assert table is not None, f"could not resolve the table for {ast.unparse(node)}"
        assert isinstance(column, ast.Constant) and isinstance(column.value, str), (
            f"the rollback filters on a non-literal column: {ast.unparse(node)}"
        )
        found.append((node.lineno, table, column.value))
    return [(table, column) for _, table, column in sorted(found)]


def test_the_routers_rollback_is_exactly_two_deletes_child_before_parent() -> None:
    """Binding the SQL in this file to the code it claims to be testing.

    What breaks in production if this fails: the rollback grew — or lost — a
    statement, and every FK-level assertion in this file went on passing about a
    program that is no longer running. The specific regressions it catches are
    the three AC10 forbids by name: deleting the `books` row (destroys the whole
    book over one failed generation), `storage.remove(...)` on the PDF (the
    object every future generation of every other chapter reconstructs its key
    to), and touching `chapters` (the ON DELETE CASCADE this entire file exists
    to demonstrate). The pre-Phase-3 code did all three, correctly, because
    upload and generation were one call — so this is a live copy-forward risk,
    not a hypothetical.

    Order is asserted, not just membership: child before parent.
    """
    assert _parsed_rollback_deletes() == [
        ("lesson_jobs", "lesson_id"),
        ("lessons", "lesson_id"),
    ], "the router's rollback is no longer `lesson_jobs` then `lessons` by lesson_id"

    handler = _rollback_handler()

    # Nothing else writes. `_WRITE_METHODS` covers insert/update/upsert/delete.
    from tests.unit.test_generate_lesson_endpoint import _WRITE_METHODS, _selected_table

    writes = [
        (_selected_table(node.func.value), node.func.attr)
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _WRITE_METHODS
    ]
    assert writes == [("lesson_jobs", "delete"), ("lessons", "delete")], (
        f"the rollback performs writes beyond the two mandated deletes: {writes}"
    )

    # ...and never reaches Supabase Storage. This is the AC10 clause that has no
    # observable counterpart in Postgres at all (see the storage test below).
    storage_refs = [
        ast.unparse(node)
        for node in ast.walk(handler)
        if isinstance(node, ast.Attribute) and node.attr in {"storage", "remove"}
    ]
    assert not storage_refs, (
        "the rollback touches Supabase Storage — the uploaded PDF belongs to the "
        f"BOOK, not to this request, and removing it orphans every other chapter: {storage_refs}"
    )


def _rollback_sql(lesson_id: str) -> str:
    """The router's own rollback, rendered as SQL against the container.

    Every delete must filter on `lesson_id` — the only identifier this request
    minted. A delete keyed on anything else (`book_id`, `chapter_id`) is by
    definition reaching outside the request's blast radius, and rendering it with
    the lesson id would produce a statement that matches no rows and therefore
    looks harmless: the destructive router would be exercised as a safe one. Fail
    instead, loudly, rather than test a program that is not the one on disk.
    """
    deletes = _parsed_rollback_deletes()
    assert deletes, "no deletes were parsed out of the router's rollback"
    foreign = [(table, column) for table, column in deletes if column != "lesson_id"]
    assert not foreign, (
        "the router's rollback deletes rows keyed on something other than the "
        f"lesson id it just created — that is outside this request's blast radius: {foreign}"
    )
    return "".join(
        f"DELETE FROM public.{table} WHERE {column} = '{lesson_id}';" for table, column in deletes
    )


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
    """AC10, executed. `lesson_jobs` (child) then `lessons` (parent), each
    isolated in the router so a transient failure on one does not abandon the
    other.

    The SQL is GENERATED from the router's own exception handler by
    `_rollback_sql`, not retyped: a retyped copy makes this a test of SQL rather
    than of the endpoint, and a divergence between the two would be invisible.
    `test_the_routers_rollback_is_exactly_two_deletes_child_before_parent` pins
    the shape being generated.

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

    rollback = _psql(_rollback_sql(ingested["lesson"]))
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

    The storage object is covered separately by
    `test_the_pdfs_storage_key_is_still_reconstructible_after_the_rollback`.
    """
    before = scalar(
        "SELECT b.filename||'|'||b.status||'|'||b.page_count||'|'||c.title||'|'"
        "||c.page_start||'|'||c.page_end||'|'||c.boundary_confidence||'|'"
        "||coalesce(c.lesson_id::text,'NULL') "
        "FROM public.books b JOIN public.chapters c ON c.book_id = b.book_id "
        f"WHERE b.book_id = '{ingested['book']}'"
    )
    assert before == "ac10 rollback.pdf|ready|120|AC10 ch|1|40|fallback|NULL"

    assert _psql(_rollback_sql(ingested["lesson"])).returncode == 0

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


def test_the_pdfs_storage_key_is_still_reconstructible_after_the_rollback(
    ingested: dict[str, str],
) -> None:
    """AC10's third prohibition — never `storage.remove(...)` the PDF — asserted
    rather than deferred.

    WHAT IS AND IS NOT COVERED HERE, plainly:

    * NOT covered: whether an object exists in the Supabase Storage bucket. This
      container is Postgres + PostgREST; there is no Storage service in it and no
      `storage.objects` table, so the object's existence is not observable from
      this harness at all. Only the AC20 live run can observe that, and asserting
      a stand-in as though it were the object would be worse than saying so.

    * COVERED, and it is the half that can actually regress silently: the object
      is ADDRESSABLE only by recomputing `{user_id}/{book_id}/{filename}` from the
      `books` row, because `books` has no path column. The rollback must therefore
      leave that row's `user_id` and `filename` byte-identical — a rollback that
      deleted or rewrote them would orphan the object just as surely as removing
      it, and the symptom would be identical: `extract_node` dying on a missing
      object minutes after a 202. This asserts the key the lesson was created with
      is reproducible from the surviving book row, using the production helper.

    * COVERED by its partner, and the reason a source assertion is not optional
      here: `test_the_routers_rollback_is_exactly_two_deletes_child_before_parent`
      proves the handler contains no `storage`/`remove` reference on ANY branch.
      Between the two, "the object survives" is established without a Storage
      service — one shows no code path can delete it, the other shows the key
      that finds it still resolves.
    """
    from app.modules.content.router import _source_pdf_path

    key_before = scalar(
        f"SELECT source_file_path FROM public.lessons WHERE lesson_id = '{ingested['lesson']}'"
    )
    assert key_before, "the fixture's lesson has no source_file_path to reconstruct"

    assert _psql(_rollback_sql(ingested["lesson"])).returncode == 0

    user_id, filename = scalar(
        f"SELECT user_id::text||'|'||filename FROM public.books "
        f"WHERE book_id = '{ingested['book']}'"
    ).split("|", 1)

    rebuilt = _source_pdf_path(user_id, ingested["book"], filename)
    assert rebuilt == key_before, (
        "after the rollback the surviving books row no longer reproduces the "
        f"storage key the lesson was created with: {rebuilt!r} != {key_before!r} — "
        "the uploaded PDF is now unreachable for every future generation of every "
        "chapter in this book"
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
        {_rollback_sql(ingested["lesson"])}
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
