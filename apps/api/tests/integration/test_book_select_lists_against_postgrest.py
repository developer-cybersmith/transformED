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

import atexit
import json
import os
import pathlib
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator

import pytest

pytestmark = pytest.mark.postgres

# Where PostgREST is. Reassigned by `ensure_postgrest_stack()` when this suite
# provisions its own containers, so `query()` must read the module global at call
# time rather than capture it.
POSTGREST = os.environ.get("POSTGREST_URL", "http://127.0.0.1:53000")

# The Postgres container PostgREST is pointed at. Seeding for the AC18 shape test
# goes through `docker exec ... psql` rather than PostgREST, because
# `users.id REFERENCES auth.users(id)` (20260611000000:66) and PostgREST only
# exposes the `public` schema — an owner row cannot be created over HTTP at all.
# That is also why GitHub Actions `services:` containers cannot host this suite:
# Actions assigns them generated names, and `docker exec` needs a known one.
LOCAL_DB_CONTAINER = os.environ.get("LOCAL_DB_CONTAINER", "transformed-local-db")
LOCAL_DB_NAME = os.environ.get("LOCAL_DB_NAME", "transformed")
PGRST_CONTAINER = os.environ.get("PGRST_CONTAINER", "transformed-local-postgrest")

# ── self-provisioning ────────────────────────────────────────────────────────
# A harness that SKIPS on the runner guards nothing (binding rule 7, and Story
# 1-14 AC24). So if nothing is listening, this module brings its own stack up the
# way test_migration_chapters_book_scoped.py does — same pattern, same images,
# identical on a laptop and on a runner. `pytest.skip` survives for exactly one
# case: the Docker daemon itself is absent.
#
# What is NOT reused from the migration suite: its `sql()` / `sql_file()` helpers
# drive a LOCAL psql binary over TCP (`_find_psql`, port 55433). A GitHub runner
# has no psql client, so importing those would trade a skip for a skip. Here SQL
# goes through `docker exec ... psql` inside the container, which needs nothing
# installed on the host. The migration-file PATHS are reused rather than
# recomputed.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
MIGRATIONS_DIR = _REPO_ROOT / "supabase" / "migrations"
SHIM_SQL = pathlib.Path(__file__).parent / "supabase_shim.sql"

_OWNED_NETWORK = "transformed-pgrst-net"
_OWNED_DB = "transformed-pgrst-db"
_OWNED_API = "transformed-pgrst-api"
_OWNED_PORT = int(os.environ.get("PGRST_OWNED_PORT", "53001"))
_DB_IMAGE = "pgvector/pgvector:pg16"
_PGRST_IMAGE = os.environ.get("PGRST_IMAGE", "postgrest/postgrest")
_OWNED_PASSWORD = "test_only_not_a_secret"  # noqa: S105 — throwaway container, loopback-only
# 32+ chars: PostgREST refuses a shorter HS256 secret outright.
_OWNED_JWT_SECRET = "test-only-postgrest-jwt-secret-32-chars-min"  # noqa: S105

_stack_ready = False


def _run(
    *args: str, timeout: int = 300, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    # encoding="utf-8" explicitly: `text=True` alone encodes stdin with the
    # process locale, which is cp1252 on a Windows dev box, and the migration
    # chain contains non-Latin-1 characters (arrows in comments). That fails as a
    # UnicodeEncodeError from inside subprocess, nowhere near the SQL.
    return subprocess.run(  # noqa: S603
        list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        input=stdin,
    )


def _postgrest_up() -> bool:
    try:
        with urllib.request.urlopen(POSTGREST + "/", timeout=5) as r:  # noqa: S310
            return r.status == 200
    except Exception:
        return False


def _docker() -> bool:
    if not shutil.which("docker"):
        return False
    return _run("docker", "info", timeout=30).returncode == 0


def _db_reachable(container: str, db: str) -> bool:
    return (
        _run(
            "docker",
            "exec",
            "-i",
            container,
            "psql",
            "-U",
            "postgres",
            "-d",
            db,
            "-c",
            "SELECT 1",
            timeout=60,
        ).returncode
        == 0
    )


def _teardown_owned_stack() -> None:
    for name in (_OWNED_API, _OWNED_DB):
        _run("docker", "rm", "-f", name, timeout=120)
    _run("docker", "network", "rm", _OWNED_NETWORK, timeout=60)


def _apply_sql_file(container: str, db: str, path: pathlib.Path) -> None:
    # utf-8-sig: 20260611000000_initial_schema.sql carries a BOM, which psql
    # reading from STDIN reports as a syntax error on line 1.
    res = _run(
        "docker",
        "exec",
        "-i",
        container,
        "psql",
        "-U",
        "postgres",
        "-d",
        db,
        "-v",
        "ON_ERROR_STOP=1",
        "-q",
        stdin=path.read_text(encoding="utf-8-sig"),
        timeout=600,
    )
    assert res.returncode == 0, f"{path.name} failed to apply: {res.stderr[-800:]}"


def _provision_owned_stack() -> None:
    """Postgres + PostgREST on a private docker network, migrations applied.

    No host port is published for Postgres — every statement goes through
    `docker exec`, so there is nothing to collide with a developer's own stack.
    """
    global POSTGREST, LOCAL_DB_CONTAINER, LOCAL_DB_NAME, PGRST_CONTAINER  # noqa: PLW0603

    _teardown_owned_stack()
    atexit.register(_teardown_owned_stack)
    _run("docker", "network", "create", _OWNED_NETWORK, timeout=60)

    up = _run(
        "docker",
        "run",
        "-d",
        "--name",
        _OWNED_DB,
        "--network",
        _OWNED_NETWORK,
        "-e",
        f"POSTGRES_PASSWORD={_OWNED_PASSWORD}",
        "-e",
        "POSTGRES_DB=postgres",
        _DB_IMAGE,
        timeout=900,  # cold image pull
    )
    assert up.returncode == 0, f"could not start {_DB_IMAGE}: {up.stderr[-500:]}"

    deadline = time.time() + 180
    while time.time() < deadline:
        if _db_reachable(_OWNED_DB, "postgres"):
            break
        time.sleep(2)
    else:
        pytest.fail("provisioned Postgres container did not become ready within 180s")

    created = _run(
        "docker",
        "exec",
        "-i",
        _OWNED_DB,
        "psql",
        "-U",
        "postgres",
        "-d",
        "postgres",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        f'CREATE DATABASE "{LOCAL_DB_NAME}"',
        timeout=120,
    )
    assert created.returncode == 0, f"could not create the test database: {created.stderr[-500:]}"

    _apply_sql_file(_OWNED_DB, LOCAL_DB_NAME, SHIM_SQL)
    migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))
    assert migrations, f"no migrations found in {MIGRATIONS_DIR}"
    for path in migrations:
        _apply_sql_file(_OWNED_DB, LOCAL_DB_NAME, path)

    api = _run(
        "docker",
        "run",
        "-d",
        "--name",
        _OWNED_API,
        "--network",
        _OWNED_NETWORK,
        "-e",
        f"PGRST_DB_URI=postgres://postgres:{_OWNED_PASSWORD}@{_OWNED_DB}:5432/{LOCAL_DB_NAME}",
        "-e",
        "PGRST_DB_SCHEMAS=public",
        "-e",
        "PGRST_DB_ANON_ROLE=anon",
        "-e",
        f"PGRST_JWT_SECRET={_OWNED_JWT_SECRET}",
        "-p",
        f"127.0.0.1:{_OWNED_PORT}:3000",
        _PGRST_IMAGE,
        timeout=900,
    )
    assert api.returncode == 0, f"could not start {_PGRST_IMAGE}: {api.stderr[-500:]}"

    POSTGREST = f"http://127.0.0.1:{_OWNED_PORT}"
    LOCAL_DB_CONTAINER = _OWNED_DB
    PGRST_CONTAINER = _OWNED_API

    deadline = time.time() + 120
    while time.time() < deadline:
        if _postgrest_up():
            return
        time.sleep(2)
    logs = _run("docker", "logs", "--tail", "40", _OWNED_API, timeout=60)
    pytest.fail(f"provisioned PostgREST never answered on {POSTGREST}: {logs.stderr[-800:]}")


def ensure_postgrest_stack() -> None:
    """Idempotent: reuse a developer's already-running stack, else provision one.

    Exported because `test_generate_rollback_postgres.py` needs the same migrated
    container and must not bring up a second copy of it.
    """
    global _stack_ready  # noqa: PLW0603
    if _stack_ready:
        return
    if not _docker():
        pytest.skip("Docker daemon not reachable — cannot verify against real Postgres/PostgREST")
    if _postgrest_up() and _db_reachable(LOCAL_DB_CONTAINER, LOCAL_DB_NAME):
        _stack_ready = True  # a local stack is already serving the migrated schema
        return
    _provision_owned_stack()
    _stack_ready = True


@pytest.fixture(scope="session", autouse=True)
def require_postgrest() -> None:
    """Provision if needed; skip VISIBLY only when Docker itself is missing.

    This used to skip whenever nothing was listening on :53000, which meant the
    whole PostgREST half of this file was silently unexecuted on CI — the CI step
    guarding it could not distinguish a partial skip from a pass. A skip does not
    satisfy an AC (Story 1-14 AC24).

    A developer's existing stack is reused untouched when it is up:

        docker network create pgrst-net
        docker network connect pgrst-net transformed-local-db
        docker run -d --name transformed-local-postgrest --network pgrst-net \\
          -e PGRST_DB_URI=postgres://postgres:localdev@transformed-local-db:5432/transformed \\
          -e PGRST_DB_SCHEMAS=public -e PGRST_DB_ANON_ROLE=anon \\
          -e PGRST_JWT_SECRET=<32+ chars> \\
          -p 127.0.0.1:53000:3000 postgrest/postgrest
    """
    ensure_postgrest_stack()


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
# The base table each select-list constant is sent against. Story 1-14 AC16
# requires the Phase 6 constants to execute here; `_CHAPTER_COLUMNS` and
# `_LIST_COLUMNS` are the two Phase 6 changes (they gain the
# `!lessons_chapter_id_fkey` embeds), so they are already covered by name.
# `test_every_router_select_list_constant_is_covered_here` below fails if the
# router grows a NEW select-list constant that is not in this map — the failure
# mode this map otherwise has is silence.
_TABLE_FOR_CONST: dict[str, str] = {
    "_BOOK_SELECT": "books",
    "_BOOK_COLUMNS": "books",
    "_CHAPTER_COLUMNS": "chapters",
    "_LIST_COLUMNS": "lessons",
    # Story 1-14 AC4/AC11 — the chapter row the generate endpoint gates on. It is
    # the query whose `page_start`/`page_end` decide a 422, so a 42703 here is a
    # 500 on every generation attempt.
    "_GENERATE_CHAPTER_COLUMNS": "chapters",
}


@pytest.mark.parametrize("const", sorted(_TABLE_FOR_CONST))
def test_select_list_is_accepted_by_postgrest(const: str) -> None:
    """Story 1-11 AC10, Story 1-14 AC16.3, and D37's missing enforcement.

    `_LIST_COLUMNS` is included deliberately: it is the one D9 broke, and its
    JSON-path selectors (`content->metadata->>subject`) have never been executed
    against a real database until now.
    """
    sel = select_list(const)
    table = _TABLE_FOR_CONST[const]
    status, body = query(f"/{table}?select={sel}&limit=1")
    assert status == 200, f"{const} rejected by PostgREST on `{table}`: {status} {body[:400]}"


def test_every_router_select_list_constant_is_covered_here() -> None:
    """A select list that is never executed against real PostgREST is exactly
    what D9 and D37 are about. Adding a constant to the router without adding it
    to `_TABLE_FOR_CONST` must fail HERE, loudly, rather than leave the new query
    unverified — a hand-maintained parametrize list cannot notice its own gaps.
    """
    from app.modules.content import router as content_router

    discovered = {
        name
        for name in dir(content_router)
        if name.startswith("_")
        and (name.endswith(("_COLUMNS", "_SELECT")))
        and isinstance(getattr(content_router, name), str)
        and getattr(content_router, name)
    }
    missing = discovered - set(_TABLE_FOR_CONST)
    assert not missing, (
        f"content.router has select-list constant(s) {sorted(missing)} that this "
        f"harness never sends to PostgREST. Add each to _TABLE_FOR_CONST with its "
        f"base table - do not delete this assertion."
    )
    stale = set(_TABLE_FOR_CONST) - discovered
    assert not stale, (
        f"_TABLE_FOR_CONST names {sorted(stale)}, which no longer exist on "
        f"content.router. A renamed constant must be renamed here too."
    )


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


# ════════════════════════════════════════════════════════════════════════════
# Story 1-14 AC16 — the FK qualifier is load-bearing, not ceremony
# ════════════════════════════════════════════════════════════════════════════
def test_the_unqualified_lessons_embed_really_is_a_300_pgrst201() -> None:
    """Premise for AC16, in the style of `test_a_bogus_column_really_does_raise_42703`.

    Two foreign keys exist between `chapters` and `lessons`
    (`chapters_lesson_id_fkey`, `lessons_chapter_id_fkey`), so a BARE `lessons(...)`
    embed is ambiguous and PostgREST refuses it. If it did not — if PostgREST
    silently picked one — then `!lessons_chapter_id_fkey` in `_CHAPTER_COLUMNS`
    would be decoration and the AC16 tests below would prove nothing.

    NOTE THE STATUS CODE. PGRST201 is served as **HTTP 300 Multiple Choices**, a
    3xx, NOT a 4xx. A health check or a client wrapper written as
    `if status_code >= 400: raise` reads this failure as SUCCESS and then hands
    the caller a body with no rows in it. That is why this asserts `== 300`
    explicitly rather than `>= 400` — the assertion the sibling 42703 test can
    afford to make.
    """
    status, body = query("/chapters?select=chapter_id,lessons(lesson_id)&limit=1")
    assert status == 300, (
        f"the unqualified chapters→lessons embed was not ambiguous ({status}); "
        f"the FK qualifier in _CHAPTER_COLUMNS would then be unverifiable: {body[:400]}"
    )
    assert "PGRST201" in body, f"expected PGRST201, got: {body[:400]}"
    # And the hint must still name the qualifier the router uses, or the router is
    # naming a constraint PostgREST no longer knows about.
    assert "lessons_chapter_id_fkey" in body, (
        f"PostgREST no longer offers lessons_chapter_id_fkey as a disambiguator: {body[:600]}"
    )


def test_the_wrong_qualifier_is_accepted_and_returns_the_dead_column() -> None:
    """The hazard AC16 exists for, made executable.

    `lessons!chapters_lesson_id_fkey` is *legal*. It resolves through
    `chapters.lesson_id` — the dead column AC14 forbids writing — and returns
    **HTTP 200** with `null`/`[]` forever. No mock, and no "the select list is
    accepted" test, can tell the two qualifiers apart; only this contrast can.

    If this ever stops returning 200, the ambiguity story has changed and AC16's
    reasoning must be re-derived rather than assumed.
    """
    status, body = query("/chapters?select=chapter_id,lessons!chapters_lesson_id_fkey(lesson_id)")
    assert status == 200, (
        f"the WRONG qualifier was rejected ({status}) — AC16's premise is that it is "
        f"silently accepted: {body[:400]}"
    )


@pytest.mark.parametrize(
    ("table", "fragment"),
    [
        ("chapters", "lessons!lessons_chapter_id_fkey(lesson_id,status,tier,created_at)"),
        ("lessons", "chapter:chapters!lessons_chapter_id_fkey(chapter_id,title,chapter_index)"),
    ],
)
def test_both_directions_of_the_disambiguated_embed_resolve(table: str, fragment: str) -> None:
    """AC16's table, executed. The same constraint named from opposite sides —
    to-many from `chapters`, to-one from `lessons`."""
    status, body = query(f"/{table}?select={_first_column(table)},{fragment}&limit=1")
    assert status == 200, f"{table} embed `{fragment}` rejected: {status} {body[:400]}"


def _first_column(table: str) -> str:
    return {"chapters": "chapter_id", "lessons": "lesson_id"}[table]


# ════════════════════════════════════════════════════════════════════════════
# Story 1-14 AC18 — embed SHAPE, which the anon role cannot show us
# ════════════════════════════════════════════════════════════════════════════
# Everything above queries as the **anon** role with RLS on, so every data query
# returns `[]`. That proves a select *parses*; it can never prove the array/object
# shapes AC16 depends on. (`test_the_chapters_count_embed_resolves_unambiguously`
# guards with `if rows:` for exactly this reason.) Below we mint a service_role
# bearer against the container's PGRST_JWT_SECRET, seed a known graph, and assert
# the shapes the router's response mapping is written against.


def _docker_exec_psql(statement: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [  # noqa: S607
            "docker",
            "exec",
            "-i",
            LOCAL_DB_CONTAINER,
            "psql",
            "-U",
            "postgres",
            "-d",
            LOCAL_DB_NAME,
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


def _jwt_secret() -> str | None:
    """The running container's PGRST_JWT_SECRET. Read from the container rather
    than hardcoded, so a re-provisioned container with a different secret SKIPS
    visibly instead of failing as a 401 that looks like a schema problem."""
    env = os.environ.get("PGRST_JWT_SECRET")
    if env:
        return env
    proc = _run(
        "docker", "inspect", PGRST_CONTAINER, "--format", "{{json .Config.Env}}", timeout=60
    )
    if proc.returncode != 0:
        return None
    for entry in json.loads(proc.stdout or "[]"):
        if entry.startswith("PGRST_JWT_SECRET="):
            return entry.split("=", 1)[1]
    return None


def _service_role_get(path: str, token: str) -> tuple[int, str]:
    req = urllib.request.Request(  # noqa: S310
        POSTGREST + path, headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


@pytest.fixture(scope="module")
def service_role_token() -> str:
    secret = _jwt_secret()
    if not secret:
        pytest.skip("PGRST_JWT_SECRET unreadable — cannot mint a service_role bearer")
    try:
        import jwt as pyjwt
    except ImportError:  # pragma: no cover - PyJWT is a hard dependency of the app
        pytest.skip("PyJWT not installed")
    return pyjwt.encode(
        {"role": "service_role", "exp": int(time.time()) + 3600}, secret, algorithm="HS256"
    )


@pytest.fixture(scope="module")
def seeded_graph(service_role_token: str) -> Iterator[dict[str, str]]:
    """1 book / 2 chapters / 3 lessons, owned by a throwaway user.

    Shapes seeded, all four of which AC18 names:
      chapter_with_lessons — two lessons, different tiers  → array of 2
      empty_chapter        — no lessons at all             → []
      orphan_lesson        — chapter_id IS NULL            → null
    Deleting the auth.users row cascades the whole graph away, so cleanup cannot
    leave a partial mess behind even if an assertion raises.
    """
    ids = {
        k: str(uuid.uuid4())
        for k in (
            "user",
            "book",
            "chapter_with_lessons",
            "empty_chapter",
            "lesson_t1",
            "lesson_t3",
            "orphan_lesson",
        )
    }
    seed = _docker_exec_psql(f"""
        INSERT INTO auth.users (id, email)
          VALUES ('{ids["user"]}', 'ac18-{ids["user"]}@example.test');
        INSERT INTO public.books (book_id, user_id, filename, status)
          VALUES ('{ids["book"]}', '{ids["user"]}', 'ac18.pdf', 'ready');
        INSERT INTO public.chapters
          (chapter_id, book_id, lesson_id, title, page_start, page_end, chapter_index)
        VALUES
          ('{ids["chapter_with_lessons"]}', '{ids["book"]}', NULL, 'AC18 ch', 1, 10, 9101),
          ('{ids["empty_chapter"]}', '{ids["book"]}', NULL, 'AC18 empty', 11, 20, 9102);
        INSERT INTO public.lessons
          (lesson_id, user_id, title, book_id, chapter_id, tier, status)
        VALUES
          ('{ids["lesson_t1"]}', '{ids["user"]}', 'AC18 T1', '{ids["book"]}',
           '{ids["chapter_with_lessons"]}', 'T1', 'generating'),
          ('{ids["lesson_t3"]}', '{ids["user"]}', 'AC18 T3', '{ids["book"]}',
           '{ids["chapter_with_lessons"]}', 'T3', 'ready'),
          ('{ids["orphan_lesson"]}', '{ids["user"]}', 'AC18 legacy', '{ids["book"]}',
           NULL, 'T1', 'ready');
        """)
    if seed.returncode != 0:
        # Not an assert: a container that cannot be seeded is an environment
        # problem, and it must be visible as such rather than as a shape failure.
        pytest.skip(f"could not seed the local Postgres container: {seed.stderr[:400]}")
    try:
        yield ids
    finally:
        cleanup = _docker_exec_psql(f"DELETE FROM auth.users WHERE id = '{ids['user']}'")
        assert cleanup.returncode == 0, (
            f"AC18 seed rows were left behind in a SHARED container: {cleanup.stderr[:400]}"
        )


def test_chapters_side_embed_is_an_array_of_every_lesson(
    seeded_graph: dict[str, str], service_role_token: str
) -> None:
    """AC18 + AC16 — to-MANY. `_CHAPTER_COLUMNS` must return a JSON **array**;
    `_row_to_chapter_response` unwraps a list and computes `lesson_count` from it.
    An object here means `latest_lesson` is wrong for every multi-tier chapter —
    the exact case a scalar `chapters.lesson_id` could never express."""
    sel = select_list("_CHAPTER_COLUMNS")
    assert "lessons!lessons_chapter_id_fkey" in sel, (
        "_CHAPTER_COLUMNS does not carry the AC15/AC16 embed yet — Phase 6's "
        "router change has not landed"
    )
    status, body = _service_role_get(
        f"/chapters?select={sel}&chapter_id=eq.{seeded_graph['chapter_with_lessons']}",
        service_role_token,
    )
    assert status == 200, f"service_role read failed: {status} {body[:400]}"
    rows = json.loads(body)
    assert len(rows) == 1, f"service_role saw {len(rows)} rows — RLS was not bypassed: {body[:300]}"
    embedded = rows[0]["lessons"]
    assert isinstance(embedded, list), f"chapters-side embed is not an array: {embedded!r}"
    assert len(embedded) == 2, f"expected both tiers, got {embedded!r}"
    assert {row["tier"] for row in embedded} == {"T1", "T3"}
    assert {row["lesson_id"] for row in embedded} == {
        seeded_graph["lesson_t1"],
        seeded_graph["lesson_t3"],
    }


def test_the_wrong_qualifier_returns_no_lessons_for_a_chapter_that_has_two(
    seeded_graph: dict[str, str], service_role_token: str
) -> None:
    """The payload half of `test_the_wrong_qualifier_is_accepted_and_returns_the_dead_column`.

    That test asserts only `status == 200` — so it proves the wrong qualifier is
    ACCEPTED, which is half the hazard, and says nothing about what comes back.
    It runs as the anon role, where RLS makes every chapter return `[]` anyway,
    so it could not have asserted the payload even if it wanted to. As a result
    the sentence its name makes — "returns the dead column" — was unproven.

    Here, as service_role with RLS bypassed and a chapter that really does have
    two lessons, both qualifiers are asked the same question and the answers are
    contrasted:

      lessons!lessons_chapter_id_fkey   → the two seeded lessons   (live FK)
      lessons!chapters_lesson_id_fkey   → nothing                  (dead column)

    What breaks in production if this fails: `chapters_lesson_id_fkey` resolves
    through `chapters.lesson_id`, which has had no writer since Story 1-13. A
    router that names it gets HTTP 200, an empty embed, and therefore
    `has_lesson=false` and `lesson_count=0` on every chapter forever. Green
    tests, dead feature — the student's "Generate" button never becomes "Watch"
    for a lesson that finished. The 200 is exactly why nothing else catches it.
    """
    chapter = seeded_graph["chapter_with_lessons"]

    right_status, right_body = _service_role_get(
        f"/chapters?select=chapter_id,lessons!lessons_chapter_id_fkey(lesson_id)"
        f"&chapter_id=eq.{chapter}",
        service_role_token,
    )
    assert right_status == 200, f"the LIVE qualifier failed: {right_status} {right_body[:400]}"
    live = json.loads(right_body)[0]["lessons"]
    assert {row["lesson_id"] for row in live} == {
        seeded_graph["lesson_t1"],
        seeded_graph["lesson_t3"],
    }, f"the live FK did not return the seeded lessons: {live!r}"

    wrong_status, wrong_body = _service_role_get(
        f"/chapters?select=chapter_id,lessons!chapters_lesson_id_fkey(lesson_id)"
        f"&chapter_id=eq.{chapter}",
        service_role_token,
    )
    assert wrong_status == 200, (
        f"the WRONG qualifier was rejected ({wrong_status}) — AC16's premise is that "
        f"it is silently ACCEPTED, which is what makes it dangerous: {wrong_body[:400]}"
    )
    dead = json.loads(wrong_body)[0]["lessons"]
    assert dead in (None, [], {}), (
        "the wrong qualifier returned lessons — `chapters.lesson_id` has a writer "
        f"again, and AC14's 'dead column' reasoning must be re-derived: {dead!r}"
    )
    assert dead != live, (
        "both qualifiers returned the same thing, so this contrast proves nothing "
        "about which one is load-bearing"
    )


def test_a_chapter_with_no_lessons_embeds_an_empty_list_not_null(
    seeded_graph: dict[str, str], service_role_token: str
) -> None:
    """AC18 — zero-lesson chapters are the NORMAL state for a book mid-ingestion.
    If PostgREST returned `null` here instead of `[]`, a bare `[0]` index in
    `_row_to_chapter_response` would 500 the whole chapter list."""
    sel = select_list("_CHAPTER_COLUMNS")
    assert "lessons!lessons_chapter_id_fkey" in sel, (
        "_CHAPTER_COLUMNS does not carry the AC15/AC16 embed yet"
    )
    status, body = _service_role_get(
        f"/chapters?select={sel}&chapter_id=eq.{seeded_graph['empty_chapter']}",
        service_role_token,
    )
    assert status == 200, f"service_role read failed: {status} {body[:400]}"
    rows = json.loads(body)
    assert len(rows) == 1
    assert rows[0]["lessons"] == [], (
        f"an empty to-many embed must be [], not {rows[0]['lessons']!r} — "
        f"`(None, False, 0)` depends on it"
    )


def test_lessons_side_embed_is_an_object_and_null_when_unset(
    seeded_graph: dict[str, str], service_role_token: str
) -> None:
    """AC18 + AC17 — to-ONE. The SAME constraint from the other side must produce
    a JSON **object**, and `null` for a legacy lesson with `chapter_id IS NULL`.
    `LessonStatusResponse.chapter_title` reads through it directly."""
    sel = select_list("_LIST_COLUMNS")
    assert "chapter:chapters!lessons_chapter_id_fkey" in sel, (
        "_LIST_COLUMNS does not carry the AC17 embed yet — Phase 6's router change has not landed"
    )
    status, body = _service_role_get(
        f"/lessons?select={sel}&book_id=eq.{seeded_graph['book']}&order=title.asc",
        service_role_token,
    )
    assert status == 200, f"service_role read failed: {status} {body[:400]}"
    rows = {row["title"]: row for row in json.loads(body)}
    assert set(rows) == {"AC18 T1", "AC18 T3", "AC18 legacy"}, f"unexpected rows: {sorted(rows)}"

    linked = rows["AC18 T1"]["chapter"]
    assert isinstance(linked, dict), f"lessons-side embed is not an object: {linked!r}"
    assert linked["chapter_id"] == seeded_graph["chapter_with_lessons"]
    assert linked["title"] == "AC18 ch"

    assert rows["AC18 legacy"]["chapter"] is None, (
        "a lesson with chapter_id IS NULL must embed null — every legacy lesson "
        f"is this shape, got {rows['AC18 legacy']['chapter']!r}"
    )
