"""Real-Postgres verification of the book-scale Phase 2 migration (Story 1-9).

WHY THIS FILE EXISTS IN THIS SHAPE
The repo's existing "migration tests" (tests/test_migration_assessment_schema.py,
tests/test_migration_analytics_schema.py) parse the .sql file as text — their own
docstring says "no live DB connection required". A text search cannot observe a
constraint firing, and would pass against DDL that Postgres rejects. Story 1-9 AC11
is explicitly not satisfiable that way, and binding rule 4 requires validation
against real Postgres because a Supabase mock has no catalog and cannot raise
42703 / 23505 / 23514.

So this replays EVERY file in supabase/migrations/ in filename order against a real
server and asserts on real SQLSTATEs.

DEPENDENCIES
Deliberately none beyond what the repo already has. SQL is driven through the psql
client binary rather than a Python driver, because no PG driver (psycopg/asyncpg)
is installed and adding one to satisfy a test is a dependency change this story
does not authorise.

Run:
    cd apps/api
    python -m pytest tests/integration/test_migration_chapters_book_scoped.py -v -m postgres
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import time
import uuid

import pytest

pytestmark = pytest.mark.postgres

# ── locations ────────────────────────────────────────────────────────────────
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
MIGRATIONS_DIR = _REPO_ROOT / "supabase" / "migrations"
SHIM_SQL = pathlib.Path(__file__).parent / "supabase_shim.sql"

CONTAINER = "transformed-migration-test"
IMAGE = "pgvector/pgvector:pg16"
PORT = 55433
DB = "transformed_test"
PASSWORD = "test_only_not_a_secret"  # noqa: S105 — throwaway container

_PSQL_CANDIDATES = (
    "psql",
    r"C:\Program Files\PostgreSQL\18\bin\psql.exe",
    r"C:\Program Files\PostgreSQL\17\bin\psql.exe",
    r"C:\Program Files\PostgreSQL\16\bin\psql.exe",
)


def _find_psql() -> str | None:
    for cand in _PSQL_CANDIDATES:
        found = shutil.which(cand) or (cand if pathlib.Path(cand).exists() else None)
        if found:
            return found
    return None


def _docker_up() -> bool:
    if shutil.which("docker") is None:
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


PSQL = _find_psql()


# ── psql driver ──────────────────────────────────────────────────────────────
class SqlResult:
    __slots__ = ("returncode", "sqlstate", "stderr", "stdout")

    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout.strip()
        self.stderr = stderr.strip()
        # VERBOSITY=verbose prefixes the SQLSTATE: "ERROR:  23505: duplicate key ..."
        self.sqlstate: str | None = None
        for line in stderr.splitlines():
            if "ERROR:" in line:
                tail = line.split("ERROR:", 1)[1].strip()
                code = tail.split(":", 1)[0].strip()
                if len(code) == 5 and code.isalnum():
                    self.sqlstate = code
                break

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def __repr__(self) -> str:
        return (
            f"SqlResult(rc={self.returncode}, sqlstate={self.sqlstate}, err={self.stderr[:200]!r})"
        )


def sql(
    statement: str,
    *,
    db: str = DB,
    as_user: uuid.UUID | str | None = None,
    role: str | None = None,
) -> SqlResult:
    """Execute SQL. `as_user` sets request.jwt.claims so auth.uid() resolves;
    `role` switches the Postgres role.

    Pass `role='authenticated'` to act as an end user's PostgREST connection —
    RLS applies. Pass `role='service_role'` to act as the ARQ worker's
    service-role key — BYPASSRLS applies. Passing no role leaves the connection
    as superuser, which also bypasses RLS; prefer an explicit role so the test
    states which identity it means."""
    # SET rather than SELECT set_config(): set_config returns a row, which would
    # be interleaved with the real result and force every caller to guess which
    # line is theirs. SET emits nothing. Claims are set before SET ROLE, matching
    # the order PostgREST uses.
    prelude = ""
    if as_user is not None:
        claims = json.dumps({"sub": str(as_user)})
        prelude += f"SET request.jwt.claims TO {_lit(claims)};\n"
    if role:
        prelude += f"SET ROLE {role};\n"

    env = {**os.environ, "PGPASSWORD": PASSWORD}
    proc = subprocess.run(  # noqa: S603
        [
            PSQL or "psql",
            "-w",
            "-X",
            "-q",
            "-h",
            "localhost",
            "-p",
            str(PORT),
            "-U",
            "postgres",
            "-d",
            db,
            "-v",
            "ON_ERROR_STOP=1",
            "-v",
            "VERBOSITY=verbose",
            "-t",
            "-A",
            "-c",
            prelude + statement,
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    return SqlResult(proc.returncode, proc.stdout, proc.stderr)


def _lit(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def sql_file(path: pathlib.Path, *, db: str = DB) -> SqlResult:
    env = {**os.environ, "PGPASSWORD": PASSWORD}
    proc = subprocess.run(  # noqa: S603
        [
            PSQL or "psql",
            "-w",
            "-X",
            "-q",
            "-h",
            "localhost",
            "-p",
            str(PORT),
            "-U",
            "postgres",
            "-d",
            db,
            "-v",
            "ON_ERROR_STOP=1",
            "-v",
            "VERBOSITY=verbose",
            "-f",
            str(path),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
        check=False,
    )
    return SqlResult(proc.returncode, proc.stdout, proc.stderr)


def scalar(statement: str, **kwargs: object) -> str:
    """Single value as text. Newlines are collapsed to spaces: pg_policies.qual
    renders across several lines, and returning only the last one silently
    truncated the value — which read as a failing assertion about the migration
    when the migration was correct."""
    res = sql(statement, **kwargs)  # type: ignore[arg-type]
    assert res.ok, f"query failed: {res!r}"
    return " ".join(line.strip() for line in res.stdout.splitlines()).strip()


# ── container lifecycle ──────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def pg() -> object:
    if PSQL is None:
        pytest.skip("psql client not found — cannot verify against real Postgres")
    if not _docker_up():
        pytest.skip("Docker daemon not reachable — cannot start a Postgres container")

    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)  # noqa: S603,S607
    up = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "docker",
            "run",
            "-d",
            "--name",
            CONTAINER,
            "-e",
            f"POSTGRES_PASSWORD={PASSWORD}",
            "-e",
            "POSTGRES_DB=postgres",
            "-p",
            f"{PORT}:5432",
            IMAGE,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert up.returncode == 0, f"could not start {IMAGE}: {up.stderr}"

    try:
        deadline = time.time() + 120
        while time.time() < deadline:
            if sql("SELECT 1", db="postgres").ok:
                break
            time.sleep(2)
        else:
            pytest.fail("Postgres container did not become ready within 120s")

        assert sql(f'CREATE DATABASE "{DB}"', db="postgres").ok
        shim = sql_file(SHIM_SQL)
        assert shim.ok, f"supabase shim failed to apply: {shim!r}"

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            res = sql_file(path)
            assert res.ok, f"migration {path.name} failed to apply: {res!r}"
        yield
    finally:
        subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)  # noqa: S603,S607


@pytest.fixture
def seeded(pg: object) -> dict[str, str]:  # noqa: ARG001
    """Two users, each with one book — the two identities AC16 needs."""
    ids = {k: str(uuid.uuid4()) for k in ("user_a", "user_b", "book_a", "book_b")}
    # Inserting into auth.users is enough: initial_schema.sql:74-79 has a trigger
    # that copies (id, email) into public.users. email must be supplied — public.users.email
    # is NOT NULL, so a NULL here fails 23502 inside the trigger.
    stmt = f"""
    INSERT INTO auth.users (id, email) VALUES
      ('{ids["user_a"]}', 'a@example.test'), ('{ids["user_b"]}', 'b@example.test');
    INSERT INTO public.books (book_id, user_id, filename) VALUES
      ('{ids["book_a"]}', '{ids["user_a"]}', 'a.pdf'),
      ('{ids["book_b"]}', '{ids["user_b"]}', 'b.pdf');
    """
    res = sql(stmt)
    assert res.ok, f"seed failed: {res!r}"
    return ids


# ════════════════════════════════════════════════════════════════════════════
# Premise checks — these must hold or every assertion below is meaningless
# ════════════════════════════════════════════════════════════════════════════
def test_full_migration_chain_replays_from_empty(pg: object) -> None:  # noqa: ARG001
    """AC12 — the whole chain applied cleanly (the pg fixture asserts each file)."""
    assert scalar("SELECT count(*) FROM pg_tables WHERE schemaname='public'") != "0"


def test_shim_auth_uid_reads_jwt_claims(pg: object) -> None:  # noqa: ARG001
    """Executable premise (binding rule 3): auth.uid() must resolve the JWT sub
    claim, otherwise every RLS assertion in this file is vacuous."""
    who = str(uuid.uuid4())
    assert scalar("SELECT auth.uid()::text", as_user=who) == who
    assert scalar("SELECT coalesce(auth.uid()::text, 'NULL')") == "NULL"


def test_rls_is_enabled_on_chapters_and_chunks(pg: object) -> None:  # noqa: ARG001
    got = scalar(
        "SELECT string_agg(relname||'='||relrowsecurity::text, ',' ORDER BY relname) "
        "FROM pg_class WHERE relname IN ('chapters','chunks')"
    )
    assert got == "chapters=true,chunks=true"


# ════════════════════════════════════════════════════════════════════════════
# AC2, AC3 — lesson_id nullable, FK retained
# ════════════════════════════════════════════════════════════════════════════
def test_chapter_row_can_exist_without_a_lesson(seeded: dict[str, str]) -> None:
    """AC2 — the entire point of Phase 2."""
    res = sql(
        f"INSERT INTO public.chapters "
        f"(book_id, lesson_id, title, page_start, page_end, chapter_index) "
        f"VALUES ('{seeded['book_a']}', NULL, 'Ch 1', 0, 39, 0)"
    )
    assert res.ok, f"chapter with NULL lesson_id was rejected: {res!r}"


def test_lesson_id_is_nullable_in_catalog(pg: object) -> None:  # noqa: ARG001
    """AC2 — asserted against the catalog, not the .sql text."""
    assert (
        scalar(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='chapters' AND column_name='lesson_id'"
        )
        == "YES"
    )


def test_lesson_id_foreign_key_survived(pg: object) -> None:  # noqa: ARG001
    """AC3 — dropping NOT NULL must not drop the FK."""
    assert (
        scalar(
            "SELECT count(*) FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage k USING (constraint_name) "
            "WHERE tc.table_name='chapters' AND tc.constraint_type='FOREIGN KEY' "
            "AND k.column_name='lesson_id'"
        )
        == "1"
    )


def test_chapter_with_bogus_lesson_id_still_rejected(seeded: dict[str, str]) -> None:
    """AC3 — nullable must not mean unconstrained."""
    res = sql(
        f"INSERT INTO public.chapters "
        f"(book_id, lesson_id, title, page_start, page_end, chapter_index) "
        f"VALUES ('{seeded['book_a']}', '{uuid.uuid4()}', 'x', 0, 1, 90)"
    )
    assert res.sqlstate == "23503", f"expected FK violation, got {res!r}"


# ════════════════════════════════════════════════════════════════════════════
# AC4 — lessons.chapter_id
# ════════════════════════════════════════════════════════════════════════════
def test_lessons_chapter_id_exists_nullable_with_fk(pg: object) -> None:  # noqa: ARG001
    assert (
        scalar(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='lessons' AND column_name='chapter_id'"
        )
        == "YES"
    )
    assert (
        scalar(
            "SELECT rc.delete_rule FROM information_schema.referential_constraints rc "
            "JOIN information_schema.key_column_usage k "
            "  ON k.constraint_name = rc.constraint_name "
            "WHERE k.table_name='lessons' AND k.column_name='chapter_id'"
        )
        == "SET NULL"
    )


def test_lessons_chapter_id_is_indexed(pg: object) -> None:  # noqa: ARG001
    """AC7."""
    assert (
        scalar(
            "SELECT count(*) FROM pg_indexes "
            "WHERE tablename='lessons' AND indexdef LIKE '%chapter_id%'"
        )
        != "0"
    )


# ════════════════════════════════════════════════════════════════════════════
# AC5 — UNIQUE (book_id, chapter_index)
# ════════════════════════════════════════════════════════════════════════════
def test_duplicate_book_chapter_index_is_rejected(seeded: dict[str, str]) -> None:
    base = (
        "INSERT INTO public.chapters "
        "(book_id, lesson_id, title, page_start, page_end, chapter_index) VALUES "
    )
    assert sql(f"{base}('{seeded['book_b']}', NULL, 'first', 0, 9, 5)").ok
    res = sql(f"{base}('{seeded['book_b']}', NULL, 'dup', 10, 19, 5)")
    assert res.sqlstate == "23505", f"expected unique violation, got {res!r}"


def test_same_chapter_index_allowed_across_different_books(seeded: dict[str, str]) -> None:
    """The constraint must be per-book, not global."""
    base = (
        "INSERT INTO public.chapters "
        "(book_id, lesson_id, title, page_start, page_end, chapter_index) VALUES "
    )
    assert sql(f"{base}('{seeded['book_a']}', NULL, 'a7', 0, 9, 7)").ok
    assert sql(f"{base}('{seeded['book_b']}', NULL, 'b7', 0, 9, 7)").ok


# ════════════════════════════════════════════════════════════════════════════
# AC6 — boundary_confidence
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("value", ["toc", "contents", "heading", "font", "fallback"])
def test_boundary_confidence_accepts_each_of_the_five_rungs(
    seeded: dict[str, str], value: str
) -> None:
    """AC6 — five values, one per detection rung in the Phase 3 ladder."""
    res = sql(
        f"INSERT INTO public.chapters "
        f"(book_id, lesson_id, title, page_start, page_end, chapter_index, boundary_confidence) "
        f"VALUES ('{seeded['book_a']}', NULL, '{value}', 0, 9, "
        f"{100 + ['toc', 'contents', 'heading', 'font', 'fallback'].index(value)}, '{value}')"
    )
    assert res.ok, f"rung {value!r} rejected: {res!r}"


def test_boundary_confidence_rejects_unknown_value(seeded: dict[str, str]) -> None:
    res = sql(
        f"INSERT INTO public.chapters "
        f"(book_id, lesson_id, title, page_start, page_end, chapter_index, boundary_confidence) "
        f"VALUES ('{seeded['book_a']}', NULL, 'x', 0, 9, 200, 'guessed')"
    )
    assert res.sqlstate == "23514", f"expected check violation, got {res!r}"


def test_boundary_confidence_defaults_to_fallback(seeded: dict[str, str]) -> None:
    """AC9 — pre-existing single-chapter rows are labelled truthfully."""
    assert sql(
        f"INSERT INTO public.chapters "
        f"(book_id, lesson_id, title, page_start, page_end, chapter_index) "
        f"VALUES ('{seeded['book_a']}', NULL, 'defaulted', 0, 9, 201)"
    ).ok
    assert (
        scalar(
            f"SELECT boundary_confidence FROM public.chapters "
            f"WHERE book_id='{seeded['book_a']}' AND chapter_index=201"
        )
        == "fallback"
    )


def test_boundary_confidence_is_not_null(pg: object) -> None:  # noqa: ARG001
    assert (
        scalar(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='chapters' AND column_name='boundary_confidence'"
        )
        == "NO"
    )


# ════════════════════════════════════════════════════════════════════════════
# AC14-AC17 — RLS re-rooted from lessons.user_id to books.user_id
# ════════════════════════════════════════════════════════════════════════════
def test_chapters_policies_reference_books_not_lessons(pg: object) -> None:  # noqa: ARG001
    """AC14 — and AC17's drop-then-create: exactly 4 policies, none left over."""
    assert scalar("SELECT count(*) FROM pg_policies WHERE tablename='chapters'") == "4"
    joined = scalar(
        "SELECT string_agg(coalesce(qual, with_check), ' ') "
        "FROM pg_policies WHERE tablename='chapters'"
    )
    assert "books" in joined, f"chapters policies do not reference books: {joined}"
    assert "lessons" not in joined, f"chapters policies still root through lessons: {joined}"


def test_chunks_policies_reference_books_not_lessons(pg: object) -> None:  # noqa: ARG001
    """AC15."""
    assert scalar("SELECT count(*) FROM pg_policies WHERE tablename='chunks'") == "4"
    joined = scalar(
        "SELECT string_agg(coalesce(qual, with_check), ' ') "
        "FROM pg_policies WHERE tablename='chunks'"
    )
    assert "books" in joined
    assert "lessons" not in joined


def test_other_tables_policies_untouched(pg: object) -> None:  # noqa: ARG001
    """AC17 — a stray DROP POLICY elsewhere must not pass unnoticed."""
    assert scalar("SELECT count(*) FROM pg_policies WHERE tablename='lessons'") == "4"
    assert scalar("SELECT count(*) FROM pg_policies WHERE tablename='books'") == "4"


def test_lessonless_chapter_is_visible_to_its_owner_and_no_one_else(
    seeded: dict[str, str],
) -> None:
    """AC16 — the criterion the whole re-rooting exists for.

    A chapter with lesson_id = NULL under the OLD policies could never satisfy
    `EXISTS (SELECT 1 FROM lessons WHERE lesson_id = chapters.lesson_id ...)`,
    so user A would see 0 rows. Under the re-rooted policies A sees 1 and B sees 0.
    """
    assert sql(
        f"INSERT INTO public.chapters "
        f"(book_id, lesson_id, title, page_start, page_end, chapter_index) "
        f"VALUES ('{seeded['book_a']}', NULL, 'owned by A', 0, 39, 300)"
    ).ok

    q = "SELECT count(*) FROM public.chapters WHERE chapter_index=300"
    owner = scalar(q, as_user=seeded["user_a"], role="authenticated")
    other = scalar(q, as_user=seeded["user_b"], role="authenticated")
    service = scalar(q, role="service_role")

    assert owner == "1", f"owner cannot see their own lessonless chapter (got {owner})"
    assert other == "0", f"another user can see it — RLS leak (got {other})"
    assert service == "1", "service-role connection should bypass RLS and see the row"
    assert owner != other, "RLS is not discriminating between users at all"


def test_service_role_and_user_role_disagree(seeded: dict[str, str]) -> None:
    """Guards the test above: if the role switch silently did nothing, every RLS
    assertion here would be a service-role query in disguise and would pass
    vacuously. B must see fewer rows than the superuser connection."""
    assert sql(
        f"INSERT INTO public.chapters "
        f"(book_id, lesson_id, title, page_start, page_end, chapter_index) "
        f"VALUES ('{seeded['book_a']}', NULL, 'A only', 0, 39, 301)"
    ).ok
    q = "SELECT count(*) FROM public.chapters WHERE chapter_index=301"
    assert scalar(q, role="service_role") == "1"
    assert scalar(q, as_user=seeded["user_b"], role="authenticated") == "0"


# ════════════════════════════════════════════════════════════════════════════
# AC8 — pre-existing rows survive
# ════════════════════════════════════════════════════════════════════════════
def test_preexisting_lesson_backed_chapter_still_readable(seeded: dict[str, str]) -> None:
    """AC8 — the permissive direction must not invalidate a legacy row: a chapter
    that DOES have a lesson_id, exactly as the old pipeline wrote it."""
    lesson_id = str(uuid.uuid4())
    assert sql(
        f"INSERT INTO public.lessons (lesson_id, user_id, title, book_id) VALUES "
        f"('{lesson_id}', '{seeded['user_a']}', 'legacy', '{seeded['book_a']}');"
        f"INSERT INTO public.chapters "
        f"(book_id, lesson_id, title, page_start, page_end, chapter_index) VALUES "
        f"('{seeded['book_a']}', '{lesson_id}', 'legacy ch', 1, 41, 400)"
    ).ok
    row = scalar(
        "SELECT title||'|'||page_start||'|'||page_end||'|'||boundary_confidence "
        "FROM public.chapters WHERE chapter_index=400"
    )
    assert row == "legacy ch|1|41|fallback"
