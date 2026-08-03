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
PASSWORD = "test_only_not_a_secret"  # noqa: S105 — throwaway container, loopback-only
_ALLOWED_ROLES = frozenset({"anon", "authenticated", "service_role", "postgres"})

# The migration under test. Files sorting before it are the "pre-existing schema";
# seeding between the two halves is what makes AC8/AC9/AC10 testable at all.
MIGRATION_UNDER_TEST = "20260803000000_chapters_book_scoped.sql"

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
        # Allow-list rather than raw interpolation. Every other value in this
        # module goes through _lit() or is a uuid4(); `role` is the one identifier
        # spliced into SQL, and it is spliced into a SUPERUSER connection.
        if role not in _ALLOWED_ROLES:
            raise ValueError(f"unknown test role {role!r}; allowed: {sorted(_ALLOWED_ROLES)}")
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
def _migrations(*, before_target: bool = False) -> list[pathlib.Path]:
    """All migration files in apply order, optionally only those predating the
    migration under test. The 'before' half is the schema as production has it
    today — the only honest starting point for AC8/AC9/AC10."""
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    assert any(p.name == MIGRATION_UNDER_TEST for p in files), (
        f"{MIGRATION_UNDER_TEST} not found in {MIGRATIONS_DIR} — this module's "
        f"pre/post split is meaningless without it"
    )
    if before_target:
        return [p for p in files if p.name < MIGRATION_UNDER_TEST]
    return files


def _provision(db: str, *, before_target: bool = False) -> None:
    """Fresh database + Supabase shim + migrations. Each scenario gets its own
    database inside the one container, so no scenario can see another's rows."""
    assert sql(f'CREATE DATABASE "{db}"', db="postgres").ok
    shim = sql_file(SHIM_SQL, db=db)
    assert shim.ok, f"supabase shim failed to apply: {shim!r}"
    for path in _migrations(before_target=before_target):
        res = sql_file(path, db=db)
        assert res.ok, f"migration {path.name} failed to apply: {res!r}"


def _seed_identities(db: str) -> dict[str, str]:
    """Two users, each with one book. Inserting into auth.users is enough:
    initial_schema.sql:74-79 has a trigger copying (id, email) into public.users.
    email must be supplied — public.users.email is NOT NULL, so a NULL here
    fails 23502 inside the trigger."""
    ids = {k: str(uuid.uuid4()) for k in ("user_a", "user_b", "book_a", "book_b")}
    res = sql(
        f"""
        INSERT INTO auth.users (id, email) VALUES
          ('{ids["user_a"]}', 'a@example.test'), ('{ids["user_b"]}', 'b@example.test');
        INSERT INTO public.books (book_id, user_id, filename) VALUES
          ('{ids["book_a"]}', '{ids["user_a"]}', 'a.pdf'),
          ('{ids["book_b"]}', '{ids["user_b"]}', 'b.pdf');
        """,
        db=db,
    )
    assert res.ok, f"seed failed: {res!r}"
    return ids


@pytest.fixture(scope="session")
def pg_server() -> object:
    """One container for the whole session. Each scenario provisions its own
    database inside it."""
    if PSQL is None:
        pytest.skip("psql client not found — cannot verify against real Postgres")
    if not _docker_up():
        pytest.skip("Docker daemon not reachable — cannot start a Postgres container")

    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)  # noqa: S603,S607
    try:
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
                # 127.0.0.1 deliberately: a bare "PORT:5432" publishes on 0.0.0.0,
                # exposing a superuser Postgres — which is RCE via COPY ... FROM
                # PROGRAM — with a password committed to this repo.
                "-p",
                f"127.0.0.1:{PORT}:5432",
                IMAGE,
            ],
            capture_output=True,
            text=True,
            check=False,
            # The only subprocess call here that could block on a cold or
            # rate-limited image pull. Without it a CI job hangs with no output.
            timeout=600,
        )
        assert up.returncode == 0, f"could not start {IMAGE}: {up.stderr}"

        deadline = time.time() + 120
        while time.time() < deadline:
            if sql("SELECT 1", db="postgres").ok:
                break
            time.sleep(2)
        else:
            pytest.fail("Postgres container did not become ready within 120s")
        yield
    finally:
        # Inside try/finally including startup: `docker run` can return non-zero
        # after creating the container, which would otherwise leak it.
        subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)  # noqa: S603,S607


@pytest.fixture(scope="session")
def pg(pg_server: object) -> object:  # noqa: ARG001
    """The full chain applied to an empty database."""
    _provision(DB)
    return None


@pytest.fixture
def seeded(pg: object) -> dict[str, str]:  # noqa: ARG001
    """Two users, each with one book — the two identities AC16 needs."""
    return _seed_identities(DB)


# ── AC8 / AC9 / AC10: the migration applied to a database that ALREADY HAS DATA ──
# These are the only fixtures where the migration under test runs SECOND. Every
# assertion elsewhere in this module operates on rows created after it applied,
# which cannot establish anything about pre-existing rows.

LEGACY_DB = "transformed_legacy"
DUPES_DB = "transformed_dupes"

# Field-by-field snapshot of a legacy chapter, exactly as the pre-migration
# pipeline wrote it (graph.py:609-638 — a chapter that DOES carry a lesson_id).
_LEGACY = {
    "title": "Legacy Chapter",
    "page_start": 1,
    "page_end": 41,
    "chapter_index": 1,
}


def _seed_legacy_rows(db: str, ids: dict[str, str]) -> dict[str, str]:
    """A lesson, a lesson-backed chapter, and a chunk under it — the shapes the
    old single-chapter pipeline produced."""
    lesson_id, chapter_id, chunk_id = (str(uuid.uuid4()) for _ in range(3))
    res = sql(
        f"""
        INSERT INTO public.lessons (lesson_id, user_id, title, book_id)
          VALUES ('{lesson_id}', '{ids["user_a"]}', 'legacy lesson', '{ids["book_a"]}');
        INSERT INTO public.chapters
          (chapter_id, book_id, lesson_id, title, page_start, page_end, chapter_index)
          VALUES ('{chapter_id}', '{ids["book_a"]}', '{lesson_id}',
                  '{_LEGACY["title"]}', {_LEGACY["page_start"]},
                  {_LEGACY["page_end"]}, {_LEGACY["chapter_index"]});
        INSERT INTO public.chunks (chunk_id, chapter_id, content, chunk_index)
          VALUES ('{chunk_id}', '{chapter_id}', 'legacy chunk body', 0);
        """,
        db=db,
    )
    assert res.ok, f"legacy seed failed: {res!r}"
    return {"lesson_id": lesson_id, "chapter_id": chapter_id, "chunk_id": chunk_id}


@pytest.fixture(scope="session")
def pg_legacy(pg_server: object) -> dict[str, str]:  # noqa: ARG001
    """Pre-migration schema → seed real rows → THEN apply the migration."""
    _provision(LEGACY_DB, before_target=True)
    ids = _seed_identities(LEGACY_DB)
    legacy = _seed_legacy_rows(LEGACY_DB, ids)
    res = sql_file(MIGRATIONS_DIR / MIGRATION_UNDER_TEST, db=LEGACY_DB)
    assert res.ok, f"migration failed against a populated database: {res!r}"
    return {**ids, **legacy}


@pytest.fixture(scope="session")
def pg_dupes(pg_server: object) -> SqlResult:  # noqa: ARG001
    """Pre-migration schema → seed DUPLICATE (book_id, chapter_index) → attempt
    the migration. Returns the result so AC10 can assert it failed loudly."""
    _provision(DUPES_DB, before_target=True)
    ids = _seed_identities(DUPES_DB)
    lesson_id = str(uuid.uuid4())
    seed = sql(
        f"""
        INSERT INTO public.lessons (lesson_id, user_id, title, book_id)
          VALUES ('{lesson_id}', '{ids["user_a"]}', 'dupe lesson', '{ids["book_a"]}');
        INSERT INTO public.chapters
          (book_id, lesson_id, title, page_start, page_end, chapter_index) VALUES
          ('{ids["book_a"]}', '{lesson_id}', 'first',  1, 10, 1),
          ('{ids["book_a"]}', '{lesson_id}', 'second', 11, 20, 1);
        """,
        db=DUPES_DB,
    )
    assert seed.ok, f"duplicate seed failed (pre-migration schema should allow it): {seed!r}"
    return sql_file(MIGRATIONS_DIR / MIGRATION_UNDER_TEST, db=DUPES_DB)


# ════════════════════════════════════════════════════════════════════════════
# Premise checks — these must hold or every assertion below is meaningless
# ════════════════════════════════════════════════════════════════════════════
def test_full_migration_chain_replays_from_empty(pg: object) -> None:  # noqa: ARG001
    """AC12 — the whole chain applied cleanly (the pg fixture asserts each file)."""
    assert scalar("SELECT count(*) FROM pg_tables WHERE schemaname='public'") != "0"


# MOCK-CONTRACT: auth.uid() here is supabase_shim.sql's re-implementation, not
# Supabase's. This test establishes that the shim behaves as this module assumes
# — it CANNOT detect the shim diverging from production, because nothing in this
# repo can reach a real Supabase instance. The real-dependency test does not exist
# yet; it is the "apply to the real Supabase project" step recorded as an open
# limitation in docs/stories/1-9-chapters-storable-migration.md and as D38 in
# docs/DEFECT-REGISTER.md. Until that runs, every RLS verdict in this file is
# conditional on the shim being faithful.
def test_shim_auth_uid_reads_jwt_claims(pg: object) -> None:  # noqa: ARG001
    """Premise: auth.uid() resolves the JWT sub claim, otherwise every RLS
    assertion in this file is vacuous."""
    who = str(uuid.uuid4())
    assert scalar("SELECT auth.uid()::text", as_user=who) == who
    assert scalar("SELECT coalesce(auth.uid()::text, 'NULL')") == "NULL"


def test_shim_auth_uid_returns_null_for_empty_or_absent_claims(pg: object) -> None:  # noqa: ARG001
    """Premise: an EMPTY claims GUC must yield NULL, not an error.

    PostgREST leaves the GUC empty on an unauthenticated request, so this is the
    live anon path. Supabase applies nullif(..., '') before the ::jsonb cast;
    casting first makes that raise 22P02 inside every policy, so the query errors
    instead of returning zero rows — and `test_anon_role_sees_nothing` would then
    fail for a reason that has nothing to do with the policies.

    A non-JSON GUC raises 22P02 in real Supabase too, so the shim matching that is
    correct behaviour and is deliberately not asserted as NULL here."""
    assert scalar("SELECT coalesce(auth.uid()::text, 'NULL')") == "NULL"
    res = sql("SET request.jwt.claims TO ''; SELECT coalesce(auth.uid()::text,'NULL')")
    assert res.ok, f"auth.uid() errored on an empty claims GUC: {res!r}"
    assert res.stdout.strip().splitlines()[-1] == "NULL"


def test_shim_auth_uid_honours_the_legacy_claim_sub_guc(pg: object) -> None:  # noqa: ARG001
    """Premise: Supabase checks `request.jwt.claim.sub` before parsing the JSON
    claims blob. A shim that only read the JSON would resolve NULL where
    production resolves a user."""
    who = str(uuid.uuid4())
    res = sql(f"SET request.jwt.claim.sub TO {_lit(who)}; SELECT auth.uid()::text")
    assert res.ok, f"legacy claim GUC path errored: {res!r}"
    assert res.stdout.strip().splitlines()[-1] == who


def test_rls_is_enabled_on_chapters_and_chunks(pg: object) -> None:  # noqa: ARG001
    got = scalar(
        "SELECT string_agg(relname||'='||relrowsecurity::text, ',' ORDER BY relname) "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname='public' AND relname IN ('chapters','chunks')"
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
    """AC3 — dropping NOT NULL must not drop the FK, and the AC names the cascade
    and the target explicitly. Asserting only that "an FK exists" would pass if it
    were repointed at another table or downgraded to NO ACTION."""
    assert (
        scalar(
            "SELECT rc.delete_rule||' -> '||ccu.table_name||'.'||ccu.column_name "
            "FROM information_schema.referential_constraints rc "
            "JOIN information_schema.key_column_usage k "
            "  ON k.constraint_name = rc.constraint_name "
            " AND k.constraint_schema = rc.constraint_schema "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON ccu.constraint_name = rc.constraint_name "
            " AND ccu.constraint_schema = rc.constraint_schema "
            "WHERE k.table_schema='public' AND k.table_name='chapters' "
            "AND k.column_name='lesson_id'"
        )
        == "CASCADE -> lessons.lesson_id"
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
            "SELECT rc.delete_rule||' -> '||ccu.table_name||'.'||ccu.column_name "
            "FROM information_schema.referential_constraints rc "
            "JOIN information_schema.key_column_usage k "
            "  ON k.constraint_name = rc.constraint_name "
            " AND k.constraint_schema = rc.constraint_schema "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON ccu.constraint_name = rc.constraint_name "
            " AND ccu.constraint_schema = rc.constraint_schema "
            "WHERE k.table_schema='public' AND k.table_name='lessons' "
            "AND k.column_name='chapter_id'"
        )
        == "SET NULL -> chapters.chapter_id"
    )


def test_lessons_chapter_id_set_null_actually_fires(seeded: dict[str, str]) -> None:
    """AC4's promise in behaviour, not catalog: 'a lesson survives deletion of its
    source chapter'. The catalog says SET NULL; this observes it."""
    lesson_id, chapter_id = str(uuid.uuid4()), str(uuid.uuid4())
    assert sql(
        f"INSERT INTO public.chapters "
        f"(chapter_id, book_id, lesson_id, title, page_start, page_end, chapter_index) "
        f"VALUES ('{chapter_id}', '{seeded['book_a']}', NULL, 'src', 0, 9, 505);"
        f"INSERT INTO public.lessons (lesson_id, user_id, title, book_id, chapter_id) "
        f"VALUES ('{lesson_id}', '{seeded['user_a']}', 'from ch', "
        f"'{seeded['book_a']}', '{chapter_id}');"
        f"DELETE FROM public.chapters WHERE chapter_id = '{chapter_id}';"
    ).ok
    assert (
        scalar(
            "SELECT count(*)||'/'||count(chapter_id) FROM public.lessons "
            f"WHERE lesson_id = '{lesson_id}'"
        )
        == "1/0"
    ), "lesson did not survive deletion of its chapter with chapter_id nulled"


def test_lessons_chapter_id_is_indexed(pg: object) -> None:  # noqa: ARG001
    """AC7."""
    assert (
        scalar(
            "SELECT count(*) FROM pg_indexes WHERE schemaname='public' "
            "AND tablename='lessons' AND indexname='lessons_chapter_id_idx'"
        )
        == "1"
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
_EXPECTED_CMDS = "DELETE,INSERT,SELECT,UPDATE"


def _policy_cmds(table: str) -> str:
    """Sorted 'policyname=cmd' pairs — by NAME and COMMAND, per AC14/15/17.

    A count is not enough: four FOR SELECT policies also count 4, and RLS is
    default-deny, so INSERT/UPDATE/DELETE would be silently blocked for every
    user with no test noticing."""
    return scalar(
        "SELECT string_agg(policyname||'='||cmd, ', ' ORDER BY policyname) "
        f"FROM pg_policies WHERE schemaname='public' AND tablename='{table}'"
    )


def _policy_predicates(table: str) -> str:
    """Every predicate, qual AND with_check kept separate — coalesce(qual, with_check)
    silently discards the with_check of a policy that has both, which is exactly
    where a permissive write-side predicate would hide."""
    return scalar(
        "SELECT string_agg(coalesce(qual,'')||' '||coalesce(with_check,''), ' ' "
        "ORDER BY policyname) "
        f"FROM pg_policies WHERE schemaname='public' AND tablename='{table}'"
    )


@pytest.mark.parametrize("table", ["chapters", "chunks"])
def test_policies_cover_all_four_commands_exactly_once(pg: object, table: str) -> None:  # noqa: ARG001
    """AC14/AC15 — drop-then-create left exactly one policy per command."""
    got = _policy_cmds(table)
    assert got == (
        f"{table}: delete own=DELETE, {table}: insert own=INSERT, "
        f"{table}: select own=SELECT, {table}: update own=UPDATE"
    ), f"{table} policy name/command set is wrong: {got}"


def test_chapters_policies_reference_books_not_lessons(pg: object) -> None:  # noqa: ARG001
    """AC14 — every one of the four, not merely one of them."""
    per_policy = scalar(
        "SELECT string_agg(policyname||'::'||coalesce(qual,'')||coalesce(with_check,''), "
        "'|' ORDER BY policyname) "
        "FROM pg_policies WHERE schemaname='public' AND tablename='chapters'"
    ).split("|")
    assert len(per_policy) == 4
    for entry in per_policy:
        assert "books" in entry, f"chapters policy does not reference books: {entry}"
        assert "lessons" not in entry, f"chapters policy still roots through lessons: {entry}"


def test_chunks_policies_reference_chapters_and_books_not_lessons(pg: object) -> None:  # noqa: ARG001
    """AC15 — the AC names a two-hop chunks -> chapters -> books path, so assert
    BOTH hops. 'books present, lessons absent' alone would pass a policy that
    skipped chapters entirely."""
    per_policy = scalar(
        "SELECT string_agg(policyname||'::'||coalesce(qual,'')||coalesce(with_check,''), "
        "'|' ORDER BY policyname) "
        "FROM pg_policies WHERE schemaname='public' AND tablename='chunks'"
    ).split("|")
    assert len(per_policy) == 4
    for entry in per_policy:
        assert "chapters" in entry, f"chunks policy skips the chapters hop: {entry}"
        assert "books" in entry, f"chunks policy does not reach books: {entry}"
        assert "lessons" not in entry, f"chunks policy still roots through lessons: {entry}"


def test_no_other_table_policy_changed(pg: object) -> None:  # noqa: ARG001
    """AC17 — 'every other table', asserted by NAME against a literal snapshot.

    A count cannot see a drop-and-recreate under a new name, and checking only
    lessons/books leaves ~12 tables unguarded. This is the guard that fails if a
    future migration quietly widens an unrelated policy."""
    got = scalar(
        "SELECT string_agg(tablename||'.'||policyname||'='||cmd, ', ' "
        "ORDER BY tablename, policyname) FROM pg_policies "
        "WHERE schemaname='public' AND tablename NOT IN ('chapters','chunks')"
    )
    expected_tables = {
        "attention_events",
        "books",
        "learner_dna",
        "lesson_jobs",
        "lessons",
        "onboarding_responses",
        "quiz_attempts",
        "session_events",
        "sessions",
        "teachback_attempts",
        "user_consents",
        "users",
    }
    seen = {entry.split(".", 1)[0] for entry in got.split(", ") if entry}
    assert seen == expected_tables, (
        f"the set of RLS-protected tables changed.\n  missing: {expected_tables - seen}"
        f"\n  unexpected: {seen - expected_tables}"
    )
    for table in ("lessons", "books"):
        cmds = sorted(
            entry.split("=")[-1] for entry in got.split(", ") if entry.startswith(f"{table}.")
        )
        assert ",".join(cmds) == _EXPECTED_CMDS, f"{table} policies changed: {cmds}"


# ── write-side RLS: every INSERT elsewhere in this module runs as superuser ──
def test_user_cannot_insert_a_chapter_into_another_users_book(
    seeded: dict[str, str],
) -> None:
    """AC14 — the WITH CHECK on 'chapters: insert own'. Untested, this is how a
    cross-tenant write ships: user B posting a chapter into user A's book."""
    res = sql(
        f"INSERT INTO public.chapters "
        f"(book_id, lesson_id, title, page_start, page_end, chapter_index) "
        f"VALUES ('{seeded['book_a']}', NULL, 'B writing into A', 0, 9, 500)",
        as_user=seeded["user_b"],
        role="authenticated",
    )
    assert not res.ok, "user B inserted a chapter into user A's book — RLS write hole"
    assert res.sqlstate == "42501", f"expected RLS policy violation, got {res!r}"


def test_user_can_insert_a_chapter_into_their_own_book(seeded: dict[str, str]) -> None:
    """Anti-vacuity for the test above: the WITH CHECK must permit the owner.
    Without this, a policy of WITH CHECK (false) would pass that test."""
    res = sql(
        f"INSERT INTO public.chapters "
        f"(book_id, lesson_id, title, page_start, page_end, chapter_index) "
        f"VALUES ('{seeded['book_a']}', NULL, 'A writing into A', 0, 9, 501)",
        as_user=seeded["user_a"],
        role="authenticated",
    )
    assert res.ok, f"owner could not insert into their own book: {res!r}"


def test_user_cannot_delete_another_users_chapter(seeded: dict[str, str]) -> None:
    """AC14 — 'chapters: delete own'. RLS DELETE matches zero rows rather than
    erroring, so assert the row survives, not the returncode."""
    assert sql(
        f"INSERT INTO public.chapters "
        f"(book_id, lesson_id, title, page_start, page_end, chapter_index) "
        f"VALUES ('{seeded['book_a']}', NULL, 'A owns this', 0, 9, 502)"
    ).ok
    sql(
        "DELETE FROM public.chapters WHERE chapter_index=502",
        as_user=seeded["user_b"],
        role="authenticated",
    )
    assert (
        scalar(
            "SELECT count(*) FROM public.chapters WHERE chapter_index=502",
            role="service_role",
        )
        == "1"
    ), "user B deleted user A's chapter"


def test_chunks_are_visible_to_their_owner_and_no_one_else(seeded: dict[str, str]) -> None:
    """AC15 behaviourally — no chunk row was previously read or written under a
    role, so the whole two-hop join was asserted only by substring match. A
    predicate like `c.chapter_id = chunks.chunk_id` (both uuid, no type error)
    creates cleanly and makes every chunk invisible in production."""
    chapter_id = str(uuid.uuid4())
    assert sql(
        f"INSERT INTO public.chapters "
        f"(chapter_id, book_id, lesson_id, title, page_start, page_end, chapter_index) "
        f"VALUES ('{chapter_id}', '{seeded['book_a']}', NULL, 'ch', 0, 9, 503);"
        f"INSERT INTO public.chunks (chapter_id, content, chunk_index) "
        f"VALUES ('{chapter_id}', 'owned by A', 0);"
    ).ok

    q = f"SELECT count(*) FROM public.chunks WHERE chapter_id = '{chapter_id}'"
    owner = scalar(q, as_user=seeded["user_a"], role="authenticated")
    other = scalar(q, as_user=seeded["user_b"], role="authenticated")
    assert owner == "1", f"owner cannot see their own chunk (got {owner}) — chunks RLS is broken"
    assert other == "0", f"another user can read the chunk — RLS leak (got {other})"


def test_anon_role_sees_nothing(seeded: dict[str, str]) -> None:
    """The shim grants anon ALL on every table; RLS is the only barrier. Nothing
    previously exercised the unauthenticated path at all."""
    assert sql(
        f"INSERT INTO public.chapters "
        f"(book_id, lesson_id, title, page_start, page_end, chapter_index) "
        f"VALUES ('{seeded['book_a']}', NULL, 'not for anon', 0, 9, 504)"
    ).ok
    assert (
        scalar("SELECT count(*) FROM public.chapters WHERE chapter_index=504", role="anon") == "0"
    )


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
def test_migration_applies_to_a_populated_database(pg_legacy: dict[str, str]) -> None:
    """AC8 — the migration ran SECOND here, over rows that already existed.

    The `pg_legacy` fixture asserting `res.ok` is the load-bearing part: it is the
    only place in this module where the migration meets pre-existing data."""
    assert (
        scalar(
            f"SELECT count(*) FROM public.chapters WHERE chapter_id = '{pg_legacy['chapter_id']}'",
            db=LEGACY_DB,
        )
        == "1"
    )


def test_preexisting_chapter_keeps_every_original_field(pg_legacy: dict[str, str]) -> None:
    """AC8 — field-by-field, as the AC words it: lesson_id, book_id, title,
    page_start, page_end, chapter_index all survive unchanged."""
    got = scalar(
        "SELECT lesson_id||'|'||book_id||'|'||title||'|'||page_start||'|'"
        "||page_end||'|'||chapter_index "
        f"FROM public.chapters WHERE chapter_id = '{pg_legacy['chapter_id']}'",
        db=LEGACY_DB,
    )
    expected = (
        f"{pg_legacy['lesson_id']}|{pg_legacy['book_a']}|{_LEGACY['title']}"
        f"|{_LEGACY['page_start']}|{_LEGACY['page_end']}|{_LEGACY['chapter_index']}"
    )
    assert got == expected


def test_preexisting_chunk_survives_the_rls_rerooting(pg_legacy: dict[str, str]) -> None:
    """AC8 — chunks hang off chapters, and the chunks policies were rewritten too."""
    assert (
        scalar(
            f"SELECT content FROM public.chunks WHERE chunk_id = '{pg_legacy['chunk_id']}'",
            db=LEGACY_DB,
        )
        == "legacy chunk body"
    )


def test_preexisting_rows_are_backfilled_to_fallback(pg_legacy: dict[str, str]) -> None:
    """AC9 — the ADD COLUMN NOT NULL DEFAULT backfill of rows that existed BEFORE
    the DDL. Distinct from the column default on INSERT, which
    test_boundary_confidence_defaults_to_fallback covers; that test would pass
    even if the backfill were broken."""
    assert (
        scalar(
            "SELECT boundary_confidence FROM public.chapters "
            f"WHERE chapter_id = '{pg_legacy['chapter_id']}'",
            db=LEGACY_DB,
        )
        == "fallback"
    )


def test_migration_aborts_loudly_on_preexisting_duplicates(pg_dupes: SqlResult) -> None:
    """AC10 — the story's only data-destruction guard, and previously untested.

    A database carrying duplicate (book_id, chapter_index) must make the migration
    FAIL, not quietly discard a row."""
    assert not pg_dupes.ok, (
        "migration succeeded against duplicate (book_id, chapter_index) — it must abort"
    )
    assert pg_dupes.sqlstate == "23505", f"expected 23505, got {pg_dupes!r}"


def test_aborted_migration_destroys_no_data_and_leaves_no_partial_schema(
    pg_dupes: SqlResult,
) -> None:
    """AC10 + atomicity — after the abort both duplicate rows are still present and
    the schema is untouched, so the header's 'resolve duplicates, then re-apply'
    is actually a workable remedy. Without BEGIN/COMMIT, steps 1-2 would have
    committed and the re-apply would die at 42701."""
    assert scalar("SELECT count(*) FROM public.chapters", db=DUPES_DB) == "2"
    assert (
        scalar(
            "SELECT count(*) FROM information_schema.columns WHERE table_name='chapters' "
            "AND column_name='boundary_confidence'",
            db=DUPES_DB,
        )
        == "0"
    )
    assert (
        scalar(
            "SELECT count(*) FROM information_schema.columns WHERE table_name='lessons' "
            "AND column_name='chapter_id'",
            db=DUPES_DB,
        )
        == "0"
    )


def test_migration_contains_no_silent_data_discarding_statement() -> None:
    """AC10's other half — the migration must not gain a DELETE/TRUNCATE or an
    ON CONFLICT DO NOTHING that papers over a duplicate. Cheap text guard; the
    behavioural proof is the two tests above."""
    body = (MIGRATIONS_DIR / MIGRATION_UNDER_TEST).read_text(encoding="utf-8")
    sql_only = "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("--")
    ).upper()
    for forbidden in ("DELETE FROM", "TRUNCATE", "ON CONFLICT"):
        assert forbidden not in sql_only, f"{forbidden} appeared in {MIGRATION_UNDER_TEST}"


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


def test_unique_constraint_supports_the_pipelines_upsert_conflict_target(
    seeded: dict[str, str],
) -> None:
    """Real-dependency counterpart to
    tests/unit/test_chunk_node.py::test_chunk_node_chapter_write_is_retry_safe.

    That test asserts chunk_node calls upsert(on_conflict="book_id,chapter_index");
    only Postgres can confirm the constraint actually accepts that conflict target.
    Writing the same (book_id, chapter_index) twice must succeed and leave ONE row —
    which is what makes an ARQ retry survivable."""
    for title in ("first write", "retry write"):
        res = sql(
            f"INSERT INTO public.chapters "
            f"(book_id, lesson_id, title, page_start, page_end, chapter_index) "
            f"VALUES ('{seeded['book_a']}', NULL, '{title}', 0, 9, 506) "
            f"ON CONFLICT (book_id, chapter_index) DO UPDATE SET title = EXCLUDED.title"
        )
        assert res.ok, f"upsert on the pipeline's conflict target failed: {res!r}"

    assert (
        scalar(
            "SELECT count(*)||'|'||max(title) FROM public.chapters "
            f"WHERE book_id='{seeded['book_a']}' AND chapter_index=506"
        )
        == "1|retry write"
    )
