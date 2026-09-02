"""Real-Postgres verification of the notification_log migration (Story 2-52).

WHY THIS FILE EXISTS IN THIS SHAPE
A mock cannot disconfirm a race condition or prove a UNIQUE constraint
actually rejects a duplicate at the database level (DEFECT-REGISTER binding
rule 2, binding rule 4). tests/unit/test_send_notification_email_job.py's
mocked tests only prove send_notification_email_job's own branching on the
two possible outcomes of the claim -- this file proves the claim mechanism
itself, against a real Postgres instance, following
tests/integration/test_migration_chapters_book_scoped.py's exact pattern
(its own container/psql harness duplicated here rather than imported, same
as that file does not import from elsewhere -- this repo has no shared
integration-test conftest).

A distinct container name and port from that file so both can run
concurrently without colliding.

Run:
    cd apps/api
    python -m pytest tests/integration/test_migration_notification_log.py -v -m postgres
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import time
import uuid

import pytest

pytestmark = pytest.mark.postgres

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
MIGRATIONS_DIR = _REPO_ROOT / "supabase" / "migrations"
SHIM_SQL = pathlib.Path(__file__).parent / "supabase_shim.sql"

CONTAINER = "transformed-notification-log-test"
IMAGE = "pgvector/pgvector:pg16"
PORT = 55434  # distinct from test_migration_chapters_book_scoped.py's 55433
DB = "transformed_notification_log_test"
PASSWORD = "test_only_not_a_secret"  # noqa: S105 — throwaway container, loopback-only

# No local psql client is required here (unlike
# test_migration_chapters_book_scoped.py, which shells out to a host-installed
# psql binary) -- every statement runs via `docker exec` into the Postgres
# container's own psql, since the pgvector/pgvector image ships one. This is
# more portable: it works in any environment with Docker but no local
# postgresql-client install, which is exactly the gap that caused this
# integration test to be skipped-not-written for a while (see this story's
# Completion Notes).


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


class SqlResult:
    __slots__ = ("returncode", "sqlstate", "stderr", "stdout")

    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout.strip()
        self.stderr = stderr.strip()
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


def _docker_exec_psql(
    args: list[str], *, stdin_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    # encoding="utf-8" is required explicitly: with text=True and no
    # encoding, Windows' subprocess defaults stdin/stdout encoding to the
    # console codepage (cp1252 here), and migration file comments contain
    # non-cp1252 characters (e.g. em dashes) -> UnicodeEncodeError on write.
    return subprocess.run(  # noqa: S603
        [
            "docker",  # noqa: S607
            "exec",
            "-i",
            "-e",
            f"PGPASSWORD={PASSWORD}",
            CONTAINER,
            "psql",
            "-w",
            "-X",
            "-q",
            "-U",
            "postgres",
            *args,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        input=stdin_text,
        timeout=300,
        check=False,
    )


def sql(statement: str, *, db: str = DB, role: str | None = None) -> SqlResult:
    prelude = ""
    if role:
        if role not in {"anon", "authenticated", "service_role", "postgres"}:
            raise ValueError(f"unknown test role {role!r}")
        prelude += f"SET ROLE {role};\n"

    proc = _docker_exec_psql(
        ["-d", db, "-v", "ON_ERROR_STOP=1", "-v", "VERBOSITY=verbose", "-t", "-A", "-c"]
        + [prelude + statement]
    )
    return SqlResult(proc.returncode, proc.stdout, proc.stderr)


def sql_file(path: pathlib.Path, *, db: str = DB) -> SqlResult:
    # -f reads a path INSIDE the container's own filesystem, which the host
    # migration file isn't -- pipe its contents over stdin via `-f -` instead.
    proc = _docker_exec_psql(
        ["-d", db, "-v", "ON_ERROR_STOP=1", "-v", "VERBOSITY=verbose", "-f", "-"],
        stdin_text=path.read_text(encoding="utf-8"),
    )
    return SqlResult(proc.returncode, proc.stdout, proc.stderr)


def scalar(statement: str, **kwargs: object) -> str:
    res = sql(statement, **kwargs)  # type: ignore[arg-type]
    assert res.ok, f"query failed: {res!r}"
    return " ".join(line.strip() for line in res.stdout.splitlines()).strip()


def _provision(db: str) -> None:
    assert sql(f'CREATE DATABASE "{db}"', db="postgres").ok
    if SHIM_SQL.exists():
        shim = sql_file(SHIM_SQL, db=db)
        assert shim.ok, f"supabase shim failed to apply: {shim!r}"
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        res = sql_file(path, db=db)
        assert res.ok, f"migration {path.name} failed to apply: {res!r}"


def _seed_user(db: str) -> str:
    user_id = str(uuid.uuid4())
    res = sql(f"INSERT INTO auth.users (id, email) VALUES ('{user_id}', 'a@example.test');", db=db)
    assert res.ok, f"seed failed: {res!r}"
    return user_id


@pytest.fixture(scope="session")
def pg_server() -> object:
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
                "-p",
                f"127.0.0.1:{PORT}:5432",
                IMAGE,
            ],
            capture_output=True,
            text=True,
            check=False,
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
        subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, check=False)  # noqa: S603,S607


@pytest.fixture(scope="session")
def pg(pg_server: object) -> str:  # noqa: ARG001
    _provision(DB)
    return _seed_user(DB)


def test_all_migrations_apply_cleanly(pg: str) -> None:  # noqa: ARG001
    """Sanity: the full chain, including notification_log, replays with no
    error against a fresh database."""


def test_notification_log_exists_with_expected_columns(pg: str) -> None:  # noqa: ARG001
    cols = scalar(
        "SELECT string_agg(column_name, ',' ORDER BY ordinal_position) "
        "FROM information_schema.columns WHERE table_name = 'notification_log';"
    )
    assert cols == "id,user_id,notification_type,resource_id,sent_at"


def test_duplicate_triple_is_rejected_by_plain_insert(pg: str) -> None:
    user_id = pg
    resource_id = str(uuid.uuid4())
    first = sql(
        f"INSERT INTO public.notification_log (user_id, notification_type, resource_id) "
        f"VALUES ('{user_id}', 'lesson_ready', '{resource_id}');"
    )
    assert first.ok, f"first insert should succeed: {first!r}"

    second = sql(
        f"INSERT INTO public.notification_log (user_id, notification_type, resource_id) "
        f"VALUES ('{user_id}', 'lesson_ready', '{resource_id}');"
    )
    assert not second.ok, "a duplicate (user_id, notification_type, resource_id) must be rejected"
    assert second.sqlstate == "23505", (
        f"expected 23505 (unique_violation), got {second.sqlstate!r}: {second!r}"
    )


def test_different_notification_type_for_the_same_resource_is_allowed(pg: str) -> None:
    """A lesson_ready and a session_report notification can coexist for the
    same underlying resource_id -- the UNIQUE constraint is on the full
    triple, not just (user_id, resource_id)."""
    user_id = pg
    resource_id = str(uuid.uuid4())
    first = sql(
        f"INSERT INTO public.notification_log (user_id, notification_type, resource_id) "
        f"VALUES ('{user_id}', 'lesson_ready', '{resource_id}');"
    )
    second = sql(
        f"INSERT INTO public.notification_log (user_id, notification_type, resource_id) "
        f"VALUES ('{user_id}', 'session_report', '{resource_id}');"
    )
    assert first.ok
    assert second.ok, (
        f"a different notification_type for the same resource must be allowed: {second!r}"
    )


def test_the_jobs_exact_claim_pattern_returns_a_row_once_then_none(pg: str) -> None:
    """Replays send_notification_email_job's real claim statement verbatim
    (INSERT ... ON CONFLICT ... DO NOTHING RETURNING id) twice for the same
    triple -- proving the atomic claim-before-send pattern the job relies on
    for Scale & Load Q6, not just the raw constraint in isolation."""
    user_id = pg
    resource_id = str(uuid.uuid4())
    claim_sql = (
        f"INSERT INTO public.notification_log (user_id, notification_type, resource_id) "
        f"VALUES ('{user_id}', 'lesson_ready', '{resource_id}') "
        f"ON CONFLICT (user_id, notification_type, resource_id) DO NOTHING RETURNING id;"
    )

    first = scalar(claim_sql)
    assert first != "", "the first claim must return the inserted row's id"

    second = scalar(claim_sql)
    assert second == "", (
        "a second claim for the SAME (user_id, notification_type, resource_id) must "
        "return no row -- this is what makes send_notification_email_job's idempotency "
        "safe under concurrent invocations, per D45's precedent"
    )


def test_invalid_notification_type_is_rejected(pg: str) -> None:
    user_id = pg
    res = sql(
        f"INSERT INTO public.notification_log (user_id, notification_type, resource_id) "
        f"VALUES ('{user_id}', 'weekly_progress', '{uuid.uuid4()}');"
    )
    assert not res.ok, "notification_type must be constrained to the 2 real values"
    assert res.sqlstate == "23514", f"expected 23514 (check_violation), got {res!r}"


def test_rls_is_enabled_with_no_policies(pg: str) -> None:
    """No frontend surface ever reads/writes this table (Story 2-52's own
    Dev Notes) -- RLS-enabled-with-zero-policies is the intended default-deny
    posture for anon/authenticated, confirmed by an actual authenticated-role
    query returning zero rows despite a real row existing."""
    user_id = pg
    resource_id = str(uuid.uuid4())
    insert = sql(
        f"INSERT INTO public.notification_log (user_id, notification_type, resource_id) "
        f"VALUES ('{user_id}', 'lesson_ready', '{resource_id}');",
        role="postgres",
    )
    assert insert.ok

    count_as_authenticated = scalar(
        "SELECT count(*) FROM public.notification_log;", role="authenticated"
    )
    assert count_as_authenticated == "0", (
        "authenticated role must see zero rows under RLS-enabled-zero-policies"
    )
