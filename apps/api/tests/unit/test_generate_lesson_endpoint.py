"""
Unit tests for POST /api/content/books/{book_id}/chapters/{chapter_id}/lessons
(Story 1-14, book-scale Phase 6).

This endpoint is the single write that reconnects the two halves of the
book-scale refactor: `lessons.chapter_id` is read by `content_pipeline_job` and
threaded to the PDF subprocess as page bounds, and until this story nothing
wrote it. So a defect here is not "one route is wrong" — it is "no lesson can be
generated at all" (D41).

Covered here (unit scope only — the [PG]/[PGRST] ACs live in the integration
suite): AC1 route registration · AC2 tier validation · AC4/AC5 authorization and
enumeration · AC6 insert payload · AC7 storage-key byte-exactness · AC8 enqueue
· AC9 idempotency · AC10 rollback blast radius · AC11 page-span gate · AC12
concurrency cap · AC13 rate-limit signature.

Supabase double
---------------
`_FakeSupabase` below is a *recording* double rather than a bare MagicMock: this
endpoint issues four structurally different queries against three tables and the
ACs assert on the predicates of specific ones ("the duplicate check filters on
user_id", "the foreign-book 404 costs exactly one table() call"). A MagicMock
whose `.eq()` chain collapses into one shared child cannot tell those apart, so
the assertions would pass vacuously. Every builder call is recorded as a
`_Query`, and `_resolve` answers it from an explicit `_Scenario`.

Binding rule 2: several assertions here necessarily observe a mock this file
constructed. Each is marked `# MOCK-CONTRACT:` and names the real-dependency
test that proves the same fact against Postgres/PostgREST.
"""

from __future__ import annotations

import ast
import inspect
import io
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ── Constants ─────────────────────────────────────────────────────────────────

FAKE_USER: dict[str, Any] = {
    "sub": "550e8400-e29b-41d4-a716-446655440000",
    "email": "test@example.com",
    "role": "authenticated",
}

BOOK_ID = "11111111-1111-1111-1111-111111111111"
OTHER_BOOK_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CHAPTER_ID = "44444444-4444-4444-4444-444444444444"
NEW_LESSON_ID = "22222222-2222-2222-2222-222222222222"
EXISTING_LESSON_ID = "33333333-3333-3333-3333-333333333333"
ARQ_JOB_ID = "66666666-6666-6666-6666-666666666666"

MINIMAL_PDF = b"%PDF-1.4 minimal\n%%EOF"

MOUNT_PREFIX = "/api/content"

# Metadata that must never appear in a 404 body (AC5).
LEAKABLE_TITLE = "Kinematics Of A Particle"
LEAKABLE_FILENAME = "ncert_xi_part1.pdf"


def _fresh_iso(age_s: int = 0) -> str:
    """An ISO-8601 `created_at` `age_s` seconds in the past (D53)."""
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(seconds=age_s)).isoformat()


def _url(book_id: str = BOOK_ID, chapter_id: str = CHAPTER_ID) -> str:
    return f"{MOUNT_PREFIX}/books/{book_id}/chapters/{chapter_id}/lessons"


# ── Recording Supabase double ─────────────────────────────────────────────────


@dataclass
class _Query:
    """One builder chain, recorded at `.execute()` time."""

    table: str
    op: str = "select"
    columns: str = ""
    payload: Any = None
    filters: list[tuple[str, Any]] = field(default_factory=list)
    single: bool = False

    def has(self, key: str) -> bool:
        return any(k == key for k, _ in self.filters)

    def value(self, key: str) -> Any:  # noqa: ANN401 — filter values are arbitrary JSON
        for k, v in self.filters:
            if k == key:
                return v
        return None


@dataclass
class _Scenario:
    """Everything the endpoint can read, in one place."""

    book_row: dict[str, Any] | None = None
    chapter_row: dict[str, Any] | None = None
    # Rows the (chapter_id, tier, user_id) idempotency pre-check finds.
    existing_lessons: list[dict[str, Any]] = field(default_factory=list)
    # How many lessons this user already has in status='generating'.
    concurrent_generating: int = 0


def _resp(data: Any, count: int | None = None) -> MagicMock:  # noqa: ANN401
    r = MagicMock()
    r.data = data
    r.count = count
    return r


def _resolve(q: _Query, sc: _Scenario) -> MagicMock:
    """Answer a recorded query from the scenario, in PostgREST's shapes."""
    if q.op != "select":
        if q.table == "lessons" and q.op == "insert":
            return _resp([{"lesson_id": NEW_LESSON_ID}])
        if q.table == "lesson_jobs" and q.op == "insert":
            return _resp([{"job_id": "job-row"}])
        return _resp([])

    if q.table == "books":
        return _resp(sc.book_row)
    if q.table == "chapters":
        return _resp(sc.chapter_row)
    if q.table == "lessons":
        # The idempotency pre-check is the only lessons read keyed on chapter_id;
        # the concurrency count is the one keyed on status='generating'.
        if q.has("chapter_id"):
            return _resp(list(sc.existing_lessons))
        rows = [
            {"lesson_id": f"gen-{i}", "status": "generating"}
            for i in range(sc.concurrent_generating)
        ]
        return _resp(rows, count=sc.concurrent_generating)
    return _resp([] if not q.single else None)


class _Builder:
    """Chainable postgrest-py stand-in that records the chain it was given."""

    def __init__(self, q: _Query, sc: _Scenario, sink: list[_Query]) -> None:
        self._q = q
        self._sc = sc
        self._sink = sink

    # -- terminal-shaping / filter methods -------------------------------------
    def select(self, columns: str = "", **_kw: Any) -> _Builder:  # noqa: ANN401
        self._q.op = "select"
        self._q.columns = columns
        return self

    def insert(self, payload: Any, **_kw: Any) -> _Builder:  # noqa: ANN401
        self._q.op = "insert"
        self._q.payload = payload
        return self

    def update(self, payload: Any, **_kw: Any) -> _Builder:  # noqa: ANN401
        self._q.op = "update"
        self._q.payload = payload
        return self

    def upsert(self, payload: Any, **_kw: Any) -> _Builder:  # noqa: ANN401
        self._q.op = "upsert"
        self._q.payload = payload
        return self

    def delete(self, **_kw: Any) -> _Builder:  # noqa: ANN401
        self._q.op = "delete"
        return self

    def eq(self, key: str, value: Any) -> _Builder:  # noqa: ANN401
        self._q.filters.append((key, value))
        return self

    def maybe_single(self) -> _Builder:
        self._q.single = True
        return self

    def single(self) -> _Builder:
        self._q.single = True
        return self

    def execute(self) -> MagicMock:
        self._sink.append(self._q)
        return _resolve(self._q, self._sc)

    def __getattr__(self, _name: str) -> Any:  # noqa: ANN401
        # order/limit/range/neq/in_/is_/... — chain-preserving no-ops.
        def _chain(*_a: Any, **_kw: Any) -> _Builder:  # noqa: ANN401
            return self

        return _chain


class _FakeSupabase:
    """Records every `.table(name)` selection and every executed chain."""

    def __init__(self, scenario: _Scenario) -> None:
        self.scenario = scenario
        self.table_calls: list[str] = []
        self.queries: list[_Query] = []
        self.storage = MagicMock()

    def table(self, name: str) -> _Builder:
        self.table_calls.append(name)
        return _Builder(_Query(table=name), self.scenario, self.queries)

    # -- assertion helpers -----------------------------------------------------
    def of(self, table: str, op: str | None = None) -> list[_Query]:
        return [q for q in self.queries if q.table == table and (op is None or q.op == op)]

    def writes(self) -> list[_Query]:
        return [q for q in self.queries if q.op in {"insert", "update", "upsert", "delete"}]


# ── Fixture data ──────────────────────────────────────────────────────────────


def _book_row(status: str = "ready", **over: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        "book_id": BOOK_ID,
        "user_id": FAKE_USER["sub"],
        "filename": LEAKABLE_FILENAME,
        "status": status,
        "page_count": 1151,
        **over,
    }


def _chapter_row(page_start: int = 40, page_end: int = 68, **over: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        "chapter_id": CHAPTER_ID,
        "book_id": BOOK_ID,
        "chapter_index": 3,
        "title": LEAKABLE_TITLE,
        "page_start": page_start,
        "page_end": page_end,
        "boundary_confidence": "toc",
        **over,
    }


def _ok_scenario(**over: Any) -> _Scenario:  # noqa: ANN401
    return _Scenario(book_row=_book_row(), chapter_row=_chapter_row(), **over)


def _arq_pool(job_id: str | None = ARQ_JOB_ID) -> AsyncMock:
    job = MagicMock()
    job.job_id = job_id
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock(return_value=None if job_id is None else job)
    return pool


def _post(
    sc: _Scenario,
    *,
    body: dict[str, Any] | None = None,
    book_id: str = BOOK_ID,
    chapter_id: str = CHAPTER_ID,
    pool: AsyncMock | None = None,
    user: dict[str, Any] | None = None,
) -> tuple[Any, _FakeSupabase, AsyncMock]:
    """POST the generate route with auth, ARQ and Supabase all substituted."""
    from app.core.rate_limit import limiter
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    sb = _FakeSupabase(sc)
    pool = pool or _arq_pool()

    limiter.reset()  # AC13 caps this route at 3/minute — never let it colour a test
    app.dependency_overrides[get_current_user] = lambda: user or FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: pool
    try:
        with patch("app.modules.content.router.get_supabase", return_value=sb):
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.post(_url(book_id, chapter_id), json=body if body is not None else {})
    finally:
        app.dependency_overrides.clear()
    return resp, sb, pool


# ── Source-scan helpers (AC2, AC10, AC13) ─────────────────────────────────────


def _router_path() -> Path:
    from app.modules.content import router as router_module

    assert router_module.__file__ is not None
    return Path(router_module.__file__)


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return tree


def _executable_tree(source: str) -> ast.Module:
    """Parse → strip docstrings → unparse → re-parse.

    Round-tripping through `ast.unparse` drops comments as well, so a scan over
    the result can never match the prose that explains what the code avoids —
    the failure mode that made the Story 1-10 equivalent guard useless.
    """
    return ast.parse(ast.unparse(_strip_docstrings(ast.parse(source))))


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in router source")


_TABLE_SELECTORS = frozenset({"table", "from_"})
_WRITE_METHODS = frozenset({"insert", "update", "upsert", "delete"})

# `{a}/{b}/{c}` and nothing else — the structural signature of the `source-pdfs`
# key layout, matched by SHAPE rather than by variable names so that renaming the
# parameters cannot smuggle a second copy past the AC7 scan.
_FORMAT_LAYOUT_RE = re.compile(r"^\{[^{}]*\}/\{[^{}]*\}/\{[^{}]*\}$")
_PRINTF_LAYOUT_RE = re.compile(r"^%[sdr]/%[sdr]/%[sdr]$")


def _add_operands(node: ast.expr) -> list[ast.expr]:
    """Flatten a left-nested chain of `+` into its operands."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return [*_add_operands(node.left), *_add_operands(node.right)]
    return [node]


def _is_slash_separated_triple(parts: list[ast.expr]) -> bool:
    """True for `[<expr>, "/", <expr>, "/", <expr>]` — three values, two slashes,
    no other literal text."""
    if len(parts) != 5:
        return False
    for index, part in enumerate(parts):
        literal = isinstance(part, ast.Constant) and part.value == "/"
        if index in (1, 3):
            if not literal:
                return False
        elif literal or (isinstance(part, ast.Constant) and isinstance(part.value, str)):
            return False
    return True


def _is_three_segment_slash_layout(node: ast.AST) -> bool:
    """True if *node* expresses `<a>/<b>/<c>` in any of the spellings a developer
    re-inlining the storage key would plausibly reach for.

    Matching only the f-string would let a `"/".join(...)` or a `+` chain
    reintroduce the second source of truth AC7 exists to prevent — and the
    scanner would still report "exactly once".
    """
    if isinstance(node, ast.JoinedStr):
        return _is_slash_separated_triple(list(node.values))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_slash_separated_triple(_add_operands(node))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        left = node.left
        return (
            isinstance(left, ast.Constant)
            and isinstance(left.value, str)
            and bool(_PRINTF_LAYOUT_RE.match(left.value))
        )
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        target = node.func.value
        if not (isinstance(target, ast.Constant) and isinstance(target.value, str)):
            return False
        if node.func.attr == "join" and target.value == "/":
            arg = node.args[0] if node.args else None
            return isinstance(arg, ast.List | ast.Tuple) and len(arg.elts) == 3
        if node.func.attr == "format":
            return bool(_FORMAT_LAYOUT_RE.match(target.value))
    return False


def _selected_table(node: ast.expr) -> str | None:
    """Return the table name if *node* chains back to `.table("name")`."""
    while isinstance(node, ast.Call | ast.Attribute | ast.Subscript):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in _TABLE_SELECTORS
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                return str(node.args[0].value)
            node = func
        elif isinstance(node, ast.Attribute):
            node = node.value
        else:
            node = node.value
    return None


# ══════════════════════════════════════════════════════════════════════════════
# AC1 — the route is registered, and the 422 that points at it cannot drift
# ══════════════════════════════════════════════════════════════════════════════


def _served_path(app: Any, endpoint_name: str) -> str:  # noqa: ANN401 — FastAPI app
    """Return the mounted path a POST to *endpoint_name* is served at.

    Read out of `app.openapi()["paths"]`, deliberately, NOT by walking
    `app.routes`: this FastAPI version keeps `include_router` results as lazy
    `_IncludedRouter` branches with no `.path`, so a scan of `app.routes` finds
    none of the module routes and reports a correctly registered endpoint as
    missing. The OpenAPI document is also the stronger instrument — it is what a
    client actually reads to find the route.

    FastAPI derives each operationId from the handler's name, so matching on the
    handler name still proves it is THIS function that got mounted, not merely
    that some POST happens to live at a similar path.
    """
    matches = [
        (path, op)
        for path, item in app.openapi()["paths"].items()
        for method, op in item.items()
        if method == "post" and str(op.get("operationId", "")).startswith(endpoint_name)
    ]
    assert matches, (
        f"no POST operation derived from {endpoint_name!r} appears in the OpenAPI "
        "document — the route did not register"
    )
    assert len(matches) == 1, f"{endpoint_name} is mounted more than once: {matches}"
    return matches[0][0]


@pytest.mark.unit
def test_generate_route_is_registered_on_the_real_app() -> None:
    """If registration silently fails, every generate call 404s in production
    while every mock-level unit test still passes — nothing in the Python suite
    notices today, because test_openapi_spec.py builds an assessment-only app.
    """
    from app.main import create_app

    path = _served_path(create_app(), "generate_chapter_lesson")

    assert "{book_id}" in path
    assert "{chapter_id}" in path


@pytest.mark.unit
def test_served_path_is_the_module_constant_under_the_content_mount() -> None:
    """A decorator that stops using GENERATE_LESSON_PATH would let the route and
    the 422 message that advertises it drift apart silently."""
    from app.main import create_app
    from app.modules.content.router import GENERATE_LESSON_PATH

    assert _served_path(create_app(), "generate_chapter_lesson") == (
        MOUNT_PREFIX + GENERATE_LESSON_PATH
    )


@pytest.mark.unit
def test_upload_tier_422_names_the_path_read_off_the_registered_route() -> None:
    """The upload 422 tells the caller where to go instead. If it names a path
    that is not the one actually served, a client following the error message
    gets a 404 and has no way to discover the real route.

    The expected substring is read out of the app's own OpenAPI document, so a
    retyped literal in the message cannot satisfy this test — the message and
    the route must both trace back to the same constant.
    """
    from app.core.rate_limit import limiter
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import create_app

    app = create_app()
    expected = _served_path(app, "generate_chapter_lesson").removeprefix(MOUNT_PREFIX)

    limiter.reset()
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _arq_pool()
    try:
        with patch("app.modules.content.router.get_supabase", return_value=MagicMock()):
            resp = TestClient(app, raise_server_exceptions=True).post(
                f"{MOUNT_PREFIX}/lessons",
                files={"file": ("c.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
                data={"tier": "T3"},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422
    assert expected in resp.json()["detail"], (
        f"upload's tier-422 must name the registered path {expected!r}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC2 — tier validated from the single source of truth, before any DB call
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_unknown_tier_is_422_and_never_touches_the_database() -> None:
    """`lessons.tier` has a CHECK constraint, so an unvalidated tier reaches
    Postgres and raises 23514 *after* the book and chapter lookups have already
    been paid for — and after an attacker has learned whether they exist."""
    resp, sb, pool = _post(_ok_scenario(), body={"tier": "T4"})

    assert resp.status_code == 422
    assert sb.table_calls == [], f"tier validation must precede any DB call, saw {sb.table_calls}"
    assert pool.enqueue_job.await_count == 0

    # Rejection happens in `GenerateLessonRequest`'s field_validator, i.e. in
    # FastAPI's request-validation layer, so `detail` is pydantic's error LIST
    # rather than a string. Only `loc` is pinned — the message text is pydantic's
    # to phrase and must stay free to change.
    detail = resp.json()["detail"]
    assert isinstance(detail, list), detail
    assert any(err.get("loc", [])[-1:] == ["tier"] for err in detail), detail


@pytest.mark.unit
def test_omitted_tier_defaults_to_the_shared_default() -> None:
    """A caller that omits tier must get DEFAULT_TIER, not a 422 and not None —
    `apps/web` sends no tier from the chapter card today."""
    from app.schemas.lesson import DEFAULT_TIER

    resp, sb, _ = _post(_ok_scenario(), body={})

    assert resp.status_code == 202
    assert resp.json()["tier"] == DEFAULT_TIER
    inserts = sb.of("lessons", "insert")
    assert inserts and inserts[0].payload["tier"] == DEFAULT_TIER


@pytest.mark.unit
def test_a_valid_non_default_tier_is_honoured_end_to_end() -> None:
    """If the body's tier were dropped, every student would silently get T2
    content regardless of the difficulty they picked — the exact silent-drop
    failure decision D-B exists to prevent."""
    non_default = next(t for t in sorted(_valid_tiers()) if t != _default_tier())
    resp, sb, _ = _post(_ok_scenario(), body={"tier": non_default})

    assert resp.status_code == 202
    assert resp.json()["tier"] == non_default
    assert sb.of("lessons", "insert")[0].payload["tier"] == non_default


def _valid_tiers() -> frozenset[str]:
    from app.schemas.lesson import VALID_TIERS

    return VALID_TIERS


def _default_tier() -> str:
    from app.schemas.lesson import DEFAULT_TIER

    return str(DEFAULT_TIER)


@pytest.mark.unit
def test_request_model_defaults_tier_from_the_shared_constant() -> None:
    """A hardcoded default on the model is a second source of truth: changing
    DEFAULT_TIER would then move the pipeline's default and not the API's."""
    from app.modules.content.schemas import GenerateLessonRequest
    from app.schemas.lesson import DEFAULT_TIER

    assert GenerateLessonRequest().tier == DEFAULT_TIER


@pytest.mark.unit
def test_router_defines_no_second_tier_set() -> None:
    """A local copy of the tier set drifts from `app.schemas.lesson` the first
    time a tier is added — a previous Blind Hunter review already rejected
    exactly this duplication once, in this exact file.

    Scans the EXECUTABLE source only (docstrings and comments unparsed away), so
    prose mentioning T1/T2/T3 can never trip or satisfy it.
    """
    valid = _valid_tiers()
    tree = _executable_tree(_router_path().read_text(encoding="utf-8"))

    offenders: list[str] = []
    for node in ast.walk(tree):
        literals: list[ast.expr] = []
        if isinstance(node, ast.Set | ast.List | ast.Tuple):
            literals = list(node.elts)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"frozenset", "set", "tuple", "list"}
            and node.args
            and isinstance(node.args[0], ast.Set | ast.List | ast.Tuple)
        ):
            literals = list(node.args[0].elts)

        strings = {
            e.value for e in literals if isinstance(e, ast.Constant) and isinstance(e.value, str)
        }
        if len(strings & valid) >= 2:
            offenders.append(ast.unparse(node))

    assert not offenders, (
        "router.py must import VALID_TIERS from app.schemas.lesson, not redefine "
        f"the tier set. Found: {offenders}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC4 / AC5 — authorization, gate order, and the enumeration oracle
# ══════════════════════════════════════════════════════════════════════════════
#
# The Supabase client is SERVICE-ROLE and bypasses RLS, and `chapters` has no
# user_id column at all. Application-layer filtering is the ONLY access control
# on this route, which makes it the most likely IDOR in the codebase.
#
# No timing padding is asserted anywhere below, deliberately: the 1-query /
# 2-query difference is only reachable AFTER the caller has proven ownership of
# the book, and it distinguishes states they can already enumerate for free via
# GET /books/{id}/chapters. Do not "fix" it.


@pytest.mark.unit
def test_chapter_in_another_users_book_is_404_book_not_found() -> None:
    """A 403, or a distinguishable 'chapter not found', turns this route into an
    oracle for other users' book ids: the ids are UUIDs, but a leak here would
    also confirm any id harvested from a shared link or a log."""
    resp, _, _ = _post(_Scenario(book_row=None, chapter_row=_chapter_row()))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Book not found"


@pytest.mark.unit
def test_foreign_book_404_costs_exactly_one_table_call() -> None:
    """Gate order, asserted structurally: any chapter/size/existence query issued
    before ownership is proven answers a question the caller has no right to ask,
    however carefully the response body is worded."""
    _, sb, _ = _post(_Scenario(book_row=None, chapter_row=_chapter_row()))

    assert sb.table_calls == ["books"], (
        f"ownership must be resolved before anything else; saw {sb.table_calls}"
    )


@pytest.mark.unit
def test_book_row_that_belongs_to_someone_else_is_still_404() -> None:
    """Defence in depth: this is what survives a refactor that drops the
    `.eq("user_id", ...)` predicate from the books query. With a service-role
    client there is no RLS underneath to catch it."""
    foreign = _book_row(user_id="99999999-9999-9999-9999-999999999999")
    resp, _, pool = _post(_Scenario(book_row=foreign, chapter_row=_chapter_row()))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Book not found"
    assert pool.enqueue_job.await_count == 0


@pytest.mark.unit
def test_books_query_filters_on_both_book_id_and_user_id() -> None:
    """The post-fetch ownership check is the second line of defence, not the
    first — without the predicate, every book in the table is one round-trip
    away from a service-role client."""
    _, sb, _ = _post(_ok_scenario())

    books_q = sb.of("books", "select")
    assert books_q, "no books SELECT was issued"
    assert books_q[0].value("book_id") == BOOK_ID
    assert books_q[0].value("user_id") == FAKE_USER["sub"]


@pytest.mark.unit
def test_chapter_of_a_different_book_is_404_chapter_not_found() -> None:
    """The caller owns book A and passes a chapter of book B. Without the
    book_id predicate this generates a lesson whose page bounds come from a
    different document — `extract_node` would catch the mismatch minutes later,
    after a 202, a lessons row, a lesson_jobs row and a burnt worker slot."""
    resp, _, pool = _post(_Scenario(book_row=_book_row(), chapter_row=None))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Chapter not found"
    assert pool.enqueue_job.await_count == 0


@pytest.mark.unit
def test_chapter_row_whose_book_id_disagrees_is_rejected_post_fetch() -> None:
    """Same failure as above, but reached when the `.eq("book_id", ...)`
    predicate is missing rather than when it filters. The re-check is what makes
    the two paths indistinguishable to a caller."""
    stray = _chapter_row(book_id=OTHER_BOOK_ID)
    resp, _, pool = _post(_Scenario(book_row=_book_row(), chapter_row=stray))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Chapter not found"
    assert pool.enqueue_job.await_count == 0


@pytest.mark.unit
def test_chapter_query_is_scoped_to_the_owned_book() -> None:
    _, sb, _ = _post(_ok_scenario())

    chapters_q = sb.of("chapters", "select")
    assert chapters_q, "no chapters SELECT was issued"
    assert chapters_q[0].value("chapter_id") == CHAPTER_ID
    assert chapters_q[0].value("book_id") == BOOK_ID


@pytest.mark.unit
@pytest.mark.parametrize(
    ("book_row", "chapter_row", "detail"),
    [
        (None, _chapter_row(), "Book not found"),
        (_book_row(), None, "Chapter not found"),
    ],
    ids=["foreign-book", "foreign-chapter"],
)
def test_no_404_body_leaks_chapter_or_book_metadata(
    book_row: dict[str, Any] | None,
    chapter_row: dict[str, Any] | None,
    detail: str,
) -> None:
    """A 404 that names the chapter title or the book filename is a 200 wearing a
    404's status code — the whole point of returning 404 instead of 403 is that
    the response carries no evidence the resource exists."""
    resp, _, _ = _post(_Scenario(book_row=book_row, chapter_row=chapter_row))
    body = resp.text

    assert resp.json()["detail"] == detail
    for leaked in (LEAKABLE_TITLE, LEAKABLE_FILENAME, "page_start", "page_end", "chapter_index"):
        assert leaked not in body, f"404 body leaked {leaked!r}"
    assert BOOK_ID not in body and CHAPTER_ID not in body


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["not-a-uuid", "1", "%20", "11111111-1111-1111-1111"])
def test_malformed_book_id_is_404_and_never_reaches_the_database(bad: str) -> None:
    """A non-UUID interpolated into a PostgREST filter is a 500 (22P02), which
    both leaks the query shape in logs and turns a probe into a distinguishable
    response class."""
    resp, sb, _ = _post(_ok_scenario(), book_id=bad)

    assert resp.status_code == 404
    assert sb.table_calls == []


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["not-a-uuid", "1", "%20", "44444444-4444-4444-4444"])
def test_malformed_chapter_id_is_404_and_never_reaches_the_database(bad: str) -> None:
    """`_validated_chapter_id` must be symmetric with `_validated_book_id`;
    validating only the first segment leaves the second one an open door."""
    resp, sb, _ = _post(_ok_scenario(), chapter_id=bad)

    assert resp.status_code == 404
    assert sb.table_calls == []


@pytest.mark.unit
def test_validated_chapter_id_rejects_and_returns_symmetrically() -> None:
    """Unit-level premise for the two route tests above: if the helper returned
    None or raised ValueError instead of HTTPException(404), the route would
    500 and the tests above would still be reading a 404 from somewhere else."""
    from fastapi import HTTPException

    from app.modules.content.router import _validated_chapter_id

    assert _validated_chapter_id(CHAPTER_ID) == CHAPTER_ID
    with pytest.raises(HTTPException) as exc:
        _validated_chapter_id("not-a-uuid")
    assert exc.value.status_code == 404
    assert "Chapter" in str(exc.value.detail)


@pytest.mark.unit
@pytest.mark.parametrize("book_status", ["processing", "failed"])
def test_book_that_is_not_ready_is_409(book_status: str) -> None:
    """Generating from a book still being chunked produces a lesson built from
    whatever fraction of the chapter happens to be embedded at that instant —
    silently, and only visible as a bad lesson days later."""
    sc = _Scenario(book_row=_book_row(status=book_status), chapter_row=_chapter_row())
    resp, sb, pool = _post(sc)

    assert resp.status_code == 409
    assert sb.of("lessons", "insert") == []
    assert pool.enqueue_job.await_count == 0


# ══════════════════════════════════════════════════════════════════════════════
# AC6 — the lessons INSERT names only real columns
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_lessons_insert_payload_has_exactly_the_expected_keys() -> None:
    """`lessons` has no `error`, `completed_at`, `session_id` or `subject`
    column. Naming one makes PostgREST reject the WHOLE statement with 42703 —
    the D9 outage shape — so every generation fails for every user at once.

    # MOCK-CONTRACT: this asserts on a Supabase double built in this file, which
    # has no Postgres catalog and cannot 42703. The real-dependency partner is
    # tests/unit/test_book_endpoints.py::
    #   test_the_generate_endpoints_lessons_insert_names_only_real_columns,
    # which checks THIS SAME key set against `supabase/migrations/` via
    # `_columns_of`. The set is imported from there rather than retyped, so the
    # marker cannot rot into a pointer at nothing: editing the expectation here
    # is impossible without moving the schema check too. Neither test is
    # sufficient alone — this one proves the payload, that one proves the schema.
    """
    from tests.unit.test_book_endpoints import LESSONS_INSERT_KEYS

    resp, sb, _ = _post(_ok_scenario(), body={"tier": _default_tier()})

    assert resp.status_code == 202
    inserts = sb.of("lessons", "insert")
    assert len(inserts) == 1, f"expected exactly one lessons insert, got {len(inserts)}"
    payload = inserts[0].payload
    assert isinstance(payload, dict)
    assert set(payload) == set(LESSONS_INSERT_KEYS)


@pytest.mark.unit
def test_lessons_insert_status_is_generating_not_queued() -> None:
    """`lessons_status_check` permits generating|ready|failed only. 'queued'
    inserts fine into a mock and raises 23514 in Postgres."""
    from app.schemas.lesson import LessonStatus

    _, sb, _ = _post(_ok_scenario())
    payload = sb.of("lessons", "insert")[0].payload

    assert payload["status"] == "generating"
    # Premise (binding rule 3): 'generating' is really in the shared status union.
    assert "generating" in getattr(LessonStatus, "__args__", ("generating",))


@pytest.mark.unit
def test_lessons_insert_carries_the_chapter_and_book_of_the_request() -> None:
    """This is the one write the entire story exists for: `content_pipeline_job`
    reads `chapter_id` and threads it to the PDF subprocess as page bounds. A
    null there makes `extract_node` raise, and the student sees a failed lesson
    with no explanation."""
    _, sb, _ = _post(_ok_scenario())
    payload = sb.of("lessons", "insert")[0].payload

    assert payload["chapter_id"] == CHAPTER_ID
    assert payload["book_id"] == BOOK_ID
    assert payload["user_id"] == FAKE_USER["sub"]


@pytest.mark.unit
def test_response_shape_is_exactly_the_documented_keys() -> None:
    """Dev 2 renders this response directly; an extra or missing key is a
    contract break for the chapter card."""
    resp, _, _ = _post(_ok_scenario())

    assert resp.status_code == 202
    assert set(resp.json()) == {
        "lesson_id",
        "chapter_id",
        "tier",
        "status",
        "job_id",
        "truncation_expected",
    }
    body = resp.json()
    assert body["lesson_id"] == NEW_LESSON_ID
    assert body["chapter_id"] == CHAPTER_ID
    assert body["job_id"] == ARQ_JOB_ID


@pytest.mark.unit
def test_the_202_response_status_and_the_db_status_are_different_fields() -> None:
    """These two values are NOT the same field and must not be conflated.

    `lessons.status` is constrained by `lessons_status_check` to
    generating|ready|failed (20260611000000_initial_schema.sql:88-89): writing
    "queued" there inserts cleanly into any Supabase mock and raises 23514
    against real Postgres — a mock-only truth of exactly the kind binding rule 2
    exists to catch. The response's `status` is the API's own word for "accepted,
    not started", and is deliberately "queued" on the 202.

    Pinning both in one place is what stops a future edit from "harmonising"
    them by pushing "queued" into the insert payload.
    """
    resp, sb, _ = _post(_ok_scenario())

    assert resp.status_code == 202
    assert resp.json()["status"] == "queued"
    assert sb.of("lessons", "insert")[0].payload["status"] == "generating"


# ══════════════════════════════════════════════════════════════════════════════
# AC7 — one helper owns the storage key layout, and it reconstructs byte-exactly
# ══════════════════════════════════════════════════════════════════════════════


def _upload_and_capture(filename: str) -> tuple[str, str, str]:
    """Drive a real upload and return (book_id, stored_filename, storage_key)
    as the production code actually produced them.

    Comparing two f-strings would prove nothing: both would be wrong together.
    The only meaningful assertion is that the helper reproduces the key that
    `upload_lesson` really handed to Supabase Storage, from the filename really
    written to `books.filename`.
    """
    from app.core.rate_limit import limiter
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    book_id = str(uuid.uuid4())

    books = MagicMock()
    books.insert.return_value.execute.return_value = _resp([{"book_id": book_id}])
    books.delete.return_value.eq.return_value.execute.return_value = _resp([])
    sb = MagicMock()
    sb.table.side_effect = lambda name: books if name == "books" else MagicMock()

    limiter.reset()
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    app.dependency_overrides[get_arq_redis] = lambda: _arq_pool()
    try:
        with patch("app.modules.content.router.get_supabase", return_value=sb):
            resp = TestClient(app, raise_server_exceptions=True).post(
                f"{MOUNT_PREFIX}/lessons",
                files={"file": (filename, io.BytesIO(MINIMAL_PDF), "application/pdf")},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 202, resp.text
    stored_filename = books.insert.call_args.args[0]["filename"]
    storage_key = sb.storage.from_.return_value.upload.call_args.kwargs["path"]
    return book_id, stored_filename, storage_key


@pytest.mark.unit
@pytest.mark.parametrize(
    "filename",
    ["my book (1).pdf", "../etc/passwd", "ünïcode.pdf", "a/b/c.pdf"],
    ids=["spaces-and-parens", "traversal", "non-ascii", "path-segments"],
)
def test_source_pdf_path_reconstructs_the_real_storage_key(filename: str) -> None:
    """A `source_file_path` that is one byte off does NOT fail here: the insert
    succeeds, the caller gets a 202, and the failure surfaces minutes later
    inside `extract_node` as a missing object — looking like a pipeline bug and
    costing a worker slot per attempt.

    The four names are the ones that survive sanitisation differently:
    parentheses/spaces, a traversal attempt, non-ASCII, and embedded separators.
    """
    from app.modules.content.router import _source_pdf_path

    book_id, stored_filename, storage_key = _upload_and_capture(filename)

    rebuilt = _source_pdf_path(FAKE_USER["sub"], book_id, stored_filename)
    assert rebuilt == storage_key, f"helper produced {rebuilt!r} but upload wrote {storage_key!r}"
    assert rebuilt.encode() == storage_key.encode()


@pytest.mark.unit
def test_source_pdf_path_produces_the_literal_layout_it_has_always_produced() -> None:
    """The byte-exactness test above compares `_source_pdf_path` against an
    upload path that now CALLS `_source_pdf_path` — both sides of that comparison
    are the same function, so it agrees with itself under any layout. Swapping
    the first two segments to `{book_id}/{user_id}/{filename}` passes it.

    What breaks in production: `books` has no path column, so every object
    already sitting in the `source-pdfs` bucket is addressable ONLY by
    recomputing this string. Change the layout and every PDF uploaded before the
    change is orphaned — new uploads keep working, so nothing looks broken until
    a student generates a lesson from a book they uploaded last week and
    `extract_node` dies on a missing object minutes after a 202.

    The docstring claims the pre-Phase-3 formula was identical and that legacy
    rows therefore reconstruct. This is the assertion behind that claim: a fixed
    triple with a hard-coded expected key, which no refactor of the helper can
    satisfy by accident.
    """
    from app.modules.content.router import _source_pdf_path

    assert (
        _source_pdf_path(
            "550e8400-e29b-41d4-a716-446655440000",
            "11111111-1111-1111-1111-111111111111",
            "ncert_xi_part1.pdf",
        )
        == "550e8400-e29b-41d4-a716-446655440000/11111111-1111-1111-1111-111111111111"
        "/ncert_xi_part1.pdf"
    )
    # Ordering pinned independently of the triple above, so a symmetric swap
    # cannot be hidden by look-alike arguments.
    assert _source_pdf_path("USER", "BOOK", "FILE") == "USER/BOOK/FILE"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("filename", "expected_stored"),
    [
        ("my book (1).pdf", "my_book__1_.pdf"),
        ("../etc/passwd", "passwd"),
        ("ünïcode.pdf", "_n_code.pdf"),
        ("a/b/c.pdf", "c.pdf"),
    ],
    ids=["spaces-and-parens", "traversal", "non-ascii", "path-segments"],
)
def test_upload_sanitises_the_filename_before_it_reaches_the_storage_key(
    filename: str, expected_stored: str
) -> None:
    """The four names above are advertised as "the ones that survive sanitisation
    differently", but the byte-exactness test asserts only that two computations
    agree — it passes unchanged if `upload_lesson`'s `re.sub`/`basename` pair is
    deleted outright. This test is what notices.

    What breaks in production without the sanitiser: `filename` is attacker-
    controlled and is interpolated straight into the storage key. `../etc/passwd`
    becomes the key `{user}/{book}/../etc/passwd`, which normalises OUT of the
    caller's own prefix — one user writing into another's key space, and a
    bucket whose object paths no longer correspond to any `books` row. It is
    stored into `books.filename` as well, so the damage is permanent: the key is
    reconstructed from that column at generation time forever after.
    """
    _, stored_filename, storage_key = _upload_and_capture(filename)

    assert stored_filename == expected_stored, (
        f"upload stored {stored_filename!r} for {filename!r}; sanitisation changed"
    )
    # The structural invariant, independent of the table above: the key has
    # exactly three segments and the last one cannot escape the prefix.
    segments = storage_key.split("/")
    assert len(segments) == 3, f"{storage_key!r} is not a three-segment key"
    assert ".." not in segments[2]
    assert "\\" not in storage_key


@pytest.mark.unit
def test_the_storage_key_layout_is_expressed_exactly_once_in_the_app() -> None:
    """AC7's other half: one helper OWNS the layout. The byte-exactness tests
    prove `_source_pdf_path` agrees with the upload path; they cannot prove a
    third site has not grown its own copy, because a second f-string that happens
    to be correct today agrees with everything.

    What breaks in production: two independent spellings of the key are two
    sources of truth for a value that has to be byte-exact across a gap of days —
    the upload writes the object, and generation recomputes the key from
    `books.filename` because `books` has no path column. When they diverge the
    `lessons` INSERT still succeeds and the caller still gets a 202; the failure
    surfaces minutes later inside `extract_node` as a missing object, looking
    like a PDF-parsing bug, and costs a worker slot per retry.

    Method (the technique in tests/unit/test_node_return_shape.py and
    test_pipeline_writes_no_books.py): scan the EXECUTABLE source — every module
    under `app/` parsed with `ast`, docstrings stripped, round-tripped through
    `ast.unparse` so comments are gone. Prose describing the layout therefore
    cannot match. That is exactly how the Story 1-10 guard first failed.
    """
    app_dir = _router_path().parents[2]
    assert app_dir.name == "app", f"expected the app package, got {app_dir}"

    sites: list[str] = []
    for path in sorted(app_dir.rglob("*.py")):
        try:
            tree = _executable_tree(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover — a syntax error fails CI elsewhere
            raise AssertionError(f"could not parse {path}: {exc}") from exc
        rel = path.relative_to(app_dir).as_posix()
        for node in ast.walk(tree):
            if _is_three_segment_slash_layout(node):
                sites.append(f"{rel}: {ast.unparse(node)}")

    assert len(sites) == 1, (
        "the `source-pdfs` key layout `{user_id}/{book_id}/{filename}` must be "
        f"expressed exactly ONCE in app/ (AC7). Found {len(sites)}: {sites}"
    )
    # ...and the one site must be the helper, not some other module that merely
    # happens to be the only one left.
    owner = _find_function(
        _executable_tree(_router_path().read_text(encoding="utf-8")), "_source_pdf_path"
    )
    assert any(_is_three_segment_slash_layout(n) for n in ast.walk(owner)), (
        "the single remaining layout site is not inside `_source_pdf_path`"
    )


@pytest.mark.unit
def test_the_layout_scanner_fires_on_every_spelling_it_claims_to_cover() -> None:
    """Premise (binding rule 3). A structural scanner that matched nothing would
    be indistinguishable from a clean codebase — and would report `len(sites) == 1`
    only by luck. Positive controls for each spelling, and negative controls for
    the shapes that must NOT count.
    """

    def hits(source: str) -> int:
        tree = _executable_tree(source)
        return sum(1 for n in ast.walk(tree) if _is_three_segment_slash_layout(n))

    # f-string — the real one
    assert hits('x = f"{user_id}/{book_id}/{filename}"\n') == 1
    # explicit join
    assert hits('x = "/".join([user_id, book_id, filename])\n') == 1
    # `+` concatenation
    assert hits('x = user_id + "/" + book_id + "/" + filename\n') == 1
    # printf-style
    assert hits('x = "%s/%s/%s" % (user_id, book_id, filename)\n') == 1
    # str.format
    assert hits('x = "{}/{}/{}".format(user_id, book_id, filename)\n') == 1

    # Negative: two segments is a different key (e.g. `lesson-audio`).
    assert hits('x = f"{lesson_id}/{segment}.mp3"\n') == 0
    # Negative: a literal path with no interpolation is not a layout expression.
    assert hits('x = "a/b/c"\n') == 0
    # Negative: prose. This is the Story 1-10 failure mode.
    assert hits('"""The key is f\\"{user_id}/{book_id}/{filename}\\"."""\n') == 0
    assert hits('x = 1  # f"{user_id}/{book_id}/{filename}"\n') == 0


@pytest.mark.unit
def test_generate_stores_the_source_path_rebuilt_from_the_books_row() -> None:
    """`user_id` and `filename` must come from the FETCHED books row, never from
    the JWT: they agree for the owner today, and the moment an admin or support
    path reuses this handler they stop agreeing and every path is wrong."""
    from app.modules.content.router import _source_pdf_path

    _, sb, _ = _post(_ok_scenario())
    payload = sb.of("lessons", "insert")[0].payload

    assert payload["source_file_path"] == _source_pdf_path(
        FAKE_USER["sub"], BOOK_ID, LEAKABLE_FILENAME
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC8 — lesson_jobs row, ARQ enqueue, and the false 409 removed
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_enqueue_uses_the_pipeline_job_name_and_retry_safe_key() -> None:
    """`_job_id=pipeline:{lesson_id}` is the retry-safety key the worker and
    CLAUDE.md's thread_id rule already reference. A chapter-keyed variant would
    collide across tiers and block a legitimate regeneration after a failure."""
    _, _, pool = _post(_ok_scenario())

    pool.enqueue_job.assert_awaited_once_with(
        "content_pipeline_job", NEW_LESSON_ID, _job_id=f"pipeline:{NEW_LESSON_ID}"
    )


@pytest.mark.unit
def test_lesson_jobs_row_is_created_before_the_enqueue() -> None:
    """The worker reads its checkpoint out of `lesson_jobs`. If ARQ picks the job
    up before the row exists, the first checkpoint write is an UPDATE of nothing
    and every retry restarts from node 1 — re-running LLM calls already paid for.
    """
    _, sb, _ = _post(_ok_scenario())

    jobs = sb.of("lesson_jobs", "insert")
    assert len(jobs) == 1
    assert jobs[0].payload["lesson_id"] == NEW_LESSON_ID
    assert jobs[0].payload["status"] == "pending"

    ordered = [q.table for q in sb.writes()]
    assert ordered.index("lessons") < ordered.index("lesson_jobs")


@pytest.mark.unit
def test_a_none_job_is_a_500_and_never_claims_the_lesson_is_already_queued() -> None:
    """`lesson_id` is minted by the INSERT immediately above, so a deduplicated
    _job_id is unreachable by construction — the old 409 'already queued' string
    is now a false statement to the client, and one that tells them to stop
    retrying a request that in fact produced nothing."""
    resp, _, _ = _post(_ok_scenario(), pool=_arq_pool(job_id=None))

    assert resp.status_code == 500
    assert "already queued" not in resp.text.lower()


# ══════════════════════════════════════════════════════════════════════════════
# AC9 — idempotent under the retry a 202 invites
# ══════════════════════════════════════════════════════════════════════════════
#
# Best-effort and deliberately TOCTOU-racy: two concurrent requests can both see
# nothing and both insert. There is no DB uniqueness to lean on — no UNIQUE
# exists on lessons.chapter_id or (chapter_id, tier) in any migration, and
# lessons_chapter_id_idx is non-unique on purpose. The durable fix is a partial
# unique index, a frozen-contract migration, registered rather than built here.


@pytest.mark.unit
@pytest.mark.parametrize("existing_status", ["generating", "ready"])
def test_existing_live_lesson_is_returned_200_with_no_second_pipeline(
    existing_status: str,
) -> None:
    """A 202 invites a retry, and a client that double-taps 'Generate' would
    otherwise pay for the same eleven-node pipeline twice — the single largest
    avoidable cost on the $3.00/lesson budget."""
    sc = _ok_scenario(
        existing_lessons=[
            {
                "lesson_id": EXISTING_LESSON_ID,
                "status": existing_status,
                "tier": _default_tier(),
                # NOT NULL DEFAULT now() in the schema — a row without one exists
                # only in a fixture, and the D53 staleness check reads it.
                "created_at": _fresh_iso(),
            }
        ]
    )
    from app.modules.content.router import _map_status

    resp, sb, pool = _post(sc, body={"tier": _default_tier()})

    assert resp.status_code == 200
    body = resp.json()
    assert body["lesson_id"] == EXISTING_LESSON_ID
    # The response speaks the CLIENT status vocabulary, not the DB column's.
    # `lessons.status` is generating|ready|failed; every lesson-facing response in
    # this API is queued|running|ready|failed (`LessonStatusResponse`,
    # `_row_to_status_response`). Asserting the raw column here would pin a
    # contract in which one field means "API acceptance state" on the 202 branch
    # and "DB lifecycle state" on the 200 branch — and would let `GET /lessons`
    # and this endpoint disagree about the same lesson.
    assert body["status"] == _map_status(existing_status)
    assert body["status"] in ("running", "ready")
    assert body["job_id"] is None, "the original ARQ id is not persisted; inventing one is a lie"
    assert pool.enqueue_job.await_count == 0
    assert sb.of("lessons", "insert") == []
    assert sb.of("lesson_jobs", "insert") == []


@pytest.mark.unit
def test_the_200_path_still_reports_truncation_expected_from_the_chapter() -> None:
    """`truncation_expected` describes the chapter, not this request. Defaulting
    it to false on the idempotent branch would make a client that retried see a
    75-page lesson advertised as complete, purely because it asked twice."""
    sc = _ok_scenario(
        existing_lessons=[
            {
                "lesson_id": EXISTING_LESSON_ID,
                "status": "ready",
                "tier": _default_tier(),
                "created_at": _fresh_iso(),
            }
        ]
    )
    sc.chapter_row = _chapter_row(page_start=100, page_end=174)  # span 75 > 40
    resp, _, _ = _post(sc, body={"tier": _default_tier()})

    assert resp.status_code == 200
    assert resp.json()["truncation_expected"] is True


@pytest.mark.unit
def test_only_a_failed_prior_lesson_generates_a_fresh_one() -> None:
    """If a failed lesson were treated as a match, the student could never retry
    a generation that broke — the chapter would be permanently unlearnable."""
    sc = _ok_scenario(
        existing_lessons=[
            {"lesson_id": EXISTING_LESSON_ID, "status": "failed", "tier": _default_tier()}
        ]
    )
    resp, sb, pool = _post(sc, body={"tier": _default_tier()})

    assert resp.status_code == 202
    assert resp.json()["lesson_id"] == NEW_LESSON_ID
    assert len(sb.of("lessons", "insert")) == 1
    assert pool.enqueue_job.await_count == 1


@pytest.mark.unit
def test_a_different_tier_always_produces_a_new_lesson() -> None:
    """One chapter at three tiers is a supported product state — the schema
    permits it deliberately (lessons_chapter_id_idx is non-unique). Collapsing
    tiers would hand a T3 student the T1 lesson they already watched."""
    other = next(t for t in sorted(_valid_tiers()) if t != _default_tier())
    sc = _ok_scenario(existing_lessons=[])  # the tier predicate filters the T2 row out
    resp, sb, pool = _post(sc, body={"tier": other})

    assert resp.status_code == 202
    assert resp.json()["tier"] == other
    assert len(sb.of("lessons", "insert")) == 1
    assert pool.enqueue_job.await_count == 1


@pytest.mark.unit
def test_duplicate_check_is_scoped_to_chapter_tier_and_user() -> None:
    """Without the user_id predicate the check reads across every user's lessons:
    one student generating a chapter would make that chapter return 200 with
    someone else's lesson_id to everyone — a cross-tenant content leak, not just
    a wrong cache hit."""
    _, sb, _ = _post(_ok_scenario(), body={"tier": _default_tier()})

    dup = [q for q in sb.of("lessons", "select") if q.has("chapter_id")]
    assert dup, "no (chapter_id, tier, user_id) duplicate check was issued"
    assert dup[0].value("chapter_id") == CHAPTER_ID
    assert dup[0].value("tier") == _default_tier()
    assert dup[0].value("user_id") == FAKE_USER["sub"]


# ══════════════════════════════════════════════════════════════════════════════
# AC10 — rollback touches only what this request created
# ══════════════════════════════════════════════════════════════════════════════
#
# chapters.lesson_id is ON DELETE CASCADE and chunks.chapter_id cascades from the
# chapter. So the "obvious" rollback — point the chapter at the lesson, then
# delete the lesson when the enqueue fails — DELETES THE CHAPTER AND EVERY CHUNK
# AND EMBEDDING UNDER IT. A whole book's ingestion destroyed by one failed
# generation. A Supabase mock has no FK engine and cannot show that, which is why
# the source scan below exists alongside the behavioural tests.


@pytest.mark.unit
def test_rollback_deletes_lesson_jobs_then_lessons_in_fk_order() -> None:
    """`lesson_jobs.lesson_id` references `lessons`. Deleting the parent first
    either errors or orphans the child, leaving a permanently 'pending' job row
    the admin dashboard counts as live work."""
    pool = _arq_pool()
    pool.enqueue_job = AsyncMock(side_effect=RuntimeError("redis down"))
    resp, sb, _ = _post(_ok_scenario(), pool=pool)

    assert resp.status_code == 500
    deletes = [q.table for q in sb.queries if q.op == "delete"]
    assert deletes == ["lesson_jobs", "lessons"], f"rollback order was {deletes}"


@pytest.mark.unit
def test_rollback_never_touches_books_chapters_or_storage() -> None:
    """The pre-Phase-3 code deleted the books row and removed the PDF from
    storage on failure — correct then, because upload and generation were one
    call. Carried forward, a failed *generation* now destroys the uploaded book
    and every other chapter's ability to ever be generated."""
    pool = _arq_pool()
    pool.enqueue_job = AsyncMock(side_effect=RuntimeError("redis down"))
    _, sb, _ = _post(_ok_scenario(), pool=pool)

    touched = {(q.table, q.op) for q in sb.writes()}
    for table in ("books", "chapters"):
        assert not any(t == table for t, _ in touched), f"generate wrote to {table}: {touched}"
    sb.storage.from_.assert_not_called()


@pytest.mark.unit
def test_generate_handler_source_contains_no_books_chapters_or_storage_write() -> None:
    """Structural guard for the CASCADE hazard above. The behavioural test only
    covers the paths this file happens to drive; the scan covers every branch,
    including ones added later.

    Runs over the EXECUTABLE source (docstrings stripped, comments dropped by
    `ast.unparse`), so the prose warning against these writes cannot match — the
    technique in tests/unit/test_pipeline_writes_no_books.py.
    """
    tree = _executable_tree(_router_path().read_text(encoding="utf-8"))
    fn = _find_function(tree, "generate_chapter_lesson")

    offenders: list[str] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr in _WRITE_METHODS and _selected_table(func.value) in {"books", "chapters"}:
            offenders.append(ast.unparse(node))
    assert not offenders, f"generate_chapter_lesson writes to books/chapters: {offenders}"

    storage_refs = [
        ast.unparse(n) for n in ast.walk(fn) if isinstance(n, ast.Attribute) and n.attr == "storage"
    ]
    assert not storage_refs, (
        "generate_chapter_lesson must never touch Supabase Storage — the PDF "
        f"belongs to the book, not to this request. Found: {storage_refs}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC11 — page-span gate with a warn band
# ══════════════════════════════════════════════════════════════════════════════
#
# The $3.00 cost ceiling does NOT protect against a 1,151-page chapter:
# structure_max_sections=15 x _get_section_body(max_chars=6000) means ~90,000
# characters is the entire LLM-visible window regardless of page count. A
# whole-book chapter therefore produces a CHEAP WRONG lesson, never trips the
# ceiling, and today emits only a logger.warning. These are the two numbers that
# actually gate it.
#
# 138 is the largest real chapter measured across the 8-book Phase 1 corpus
# (D2L Appendix A; medians 10-44), which is why the cap is 200 and not 80 — an
# 80-page cap would refuse a legitimate chapter. 1151 is the R5 whole-document
# case: a single "chapter" spanning the entire book, the exact failure this
# effort exists to fix.


@pytest.mark.unit
def test_span_gate_constants_are_the_decided_numbers() -> None:
    """Premise: if the cap were misconfigured to 2000 the parametrised cases
    below would still pass for every accepted span and only the rejections would
    fail — with a confusing message. Assert the decision directly."""
    from app.config import get_settings
    from app.modules.content.router import _TRUNCATION_WARN_PAGES

    assert get_settings().max_chapter_pages == 200
    assert _TRUNCATION_WARN_PAGES == 40


@pytest.mark.unit
@pytest.mark.parametrize("span", [35, 40, 41, 138, 200])
def test_spans_within_the_cap_are_accepted(span: int) -> None:
    """138 is a real chapter in the corpus. A cap that refused it would break the
    project's one success criterion — a 1,000-page book runs to completion."""
    sc = _ok_scenario()
    sc.chapter_row = _chapter_row(page_start=100, page_end=100 + span - 1)
    resp, sb, pool = _post(sc)

    assert resp.status_code == 202, resp.text
    assert len(sb.of("lessons", "insert")) == 1
    assert pool.enqueue_job.await_count == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("span", "expected"), [(35, False), (40, False), (41, True), (138, True), (200, True)]
)
def test_truncation_expected_flags_the_quality_cliff(span: int, expected: bool) -> None:
    """~90,000 LLM-visible characters / 2,296-2,816 measured chars per page is
    32-39 pages. Above that the lesson is genuinely built from part of the
    chapter, and a client shown no warning presents it as complete."""
    sc = _ok_scenario()
    sc.chapter_row = _chapter_row(page_start=100, page_end=100 + span - 1)
    resp, _, _ = _post(sc)

    assert resp.status_code == 202
    assert resp.json()["truncation_expected"] is expected


@pytest.mark.unit
@pytest.mark.parametrize("span", [201, 1151])
def test_spans_over_the_cap_are_422_with_a_structured_detail(span: int) -> None:
    """Without this gate an R5 whole-document 'chapter' generates a cheap, wrong,
    plausible-looking lesson built from 4% of the book — and the cost ceiling
    never fires, so nothing anywhere reports a problem."""
    sc = _ok_scenario()
    sc.chapter_row = _chapter_row(page_start=1, page_end=span)
    resp, sb, pool = _post(sc)

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, dict), "the client needs the numbers, not a prose sentence"
    assert detail["code"] == "chapter_too_large"
    assert detail["page_span"] == span
    assert detail["max_page_span"] == 200
    assert detail["boundary_confidence"] == "toc"
    assert sb.of("lessons", "insert") == []
    assert pool.enqueue_job.await_count == 0


@pytest.mark.unit
def test_span_is_computed_from_the_db_row_inclusively() -> None:
    """`page_end - page_start + 1`, from the DB row, never from client input. An
    off-by-one here lets a 201-page chapter through and refuses a 200-page one,
    and a client-supplied span would let the gate be bypassed entirely."""
    sc = _ok_scenario()
    sc.chapter_row = _chapter_row(page_start=1, page_end=201)  # inclusive span 201 > 200
    resp, _, _ = _post(sc, body={"page_span": 1})

    assert resp.status_code == 422
    assert resp.json()["detail"]["page_span"] == 201


# ══════════════════════════════════════════════════════════════════════════════
# AC12 — per-user concurrency cap
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_at_the_concurrency_cap_the_request_is_429_with_retry_after() -> None:
    """A rate limit is not a cost control — a caller can stay under 3/minute
    forever and still hold fifty pipelines open. This is the gate that actually
    bounds spend, and `Retry-After` is what stops a well-behaved client from
    hot-looping against it."""
    from app.config import get_settings

    cap = get_settings().max_concurrent_generations_per_user
    sc = _ok_scenario(concurrent_generating=cap)
    resp, sb, pool = _post(sc)

    assert resp.status_code == 429
    assert "retry-after" in {k.lower() for k in resp.headers}
    assert sb.of("lessons", "insert") == []
    assert sb.of("lesson_jobs", "insert") == []
    assert pool.enqueue_job.await_count == 0


@pytest.mark.unit
def test_just_below_the_concurrency_cap_is_still_accepted() -> None:
    """An off-by-one that makes the cap exclusive would refuse a user's very
    first generation once they had cap-1 running — the gate must bite AT the
    cap, not below it."""
    from app.config import get_settings

    cap = get_settings().max_concurrent_generations_per_user
    sc = _ok_scenario(concurrent_generating=cap - 1)
    resp, sb, _ = _post(sc)

    assert resp.status_code == 202
    assert len(sb.of("lessons", "insert")) == 1


@pytest.mark.unit
def test_concurrency_count_is_scoped_to_the_caller() -> None:
    """A global count turns one heavy user into a denial of service for every
    other student on the platform."""
    _, sb, _ = _post(_ok_scenario(concurrent_generating=1))

    counting = [q for q in sb.of("lessons", "select") if not q.has("chapter_id")]
    assert counting, "no per-user concurrency count was issued"
    assert counting[0].value("user_id") == FAKE_USER["sub"]
    assert counting[0].value("status") == "generating"


# ══════════════════════════════════════════════════════════════════════════════
# AC13 — rate limit sized for an endpoint that spends money
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_handler_declares_a_parameter_literally_named_request() -> None:
    """slowapi reaches into the handler's kwargs for `request` by NAME and raises
    at call time if it is absent — so this fails as a 500 on the first real
    request, not at import, and not in any test that mocks the limiter away."""
    from app.modules.content.router import generate_chapter_lesson

    params = inspect.signature(generate_chapter_lesson).parameters
    assert "request" in params, (
        "slowapi's @limiter.limit requires a parameter literally named `request`"
    )


@pytest.mark.unit
def test_generate_route_is_rate_limited_at_three_per_minute() -> None:
    """5/minute is the UPLOAD number; here it authorises roughly $900/hour of
    LLM spend per user. Asserted on the decorator rather than by exhausting the
    limiter, so it cannot be satisfied by a limiter that is configured but never
    consulted.

    Note the limiter's storage_uri defaults to `memory://`
    (core/rate_limit.py:51), so this cap multiplies by replica count — a
    registered defect, not one fixed here.
    """
    tree = _executable_tree(_router_path().read_text(encoding="utf-8"))
    fn = _find_function(tree, "generate_chapter_lesson")

    limits = [
        d.args[0].value
        for d in fn.decorator_list
        if isinstance(d, ast.Call)
        and isinstance(d.func, ast.Attribute)
        and d.func.attr == "limit"
        and d.args
        and isinstance(d.args[0], ast.Constant)
        and isinstance(d.args[0].value, str)
    ]
    assert limits, "generate_chapter_lesson carries no @limiter.limit decorator"
    assert any("3/minute" in limit for limit in limits), limits


def _limit_decorators(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    return [
        d
        for d in fn.decorator_list
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "limit"
    ]


@pytest.mark.unit
def test_generate_route_also_carries_the_hourly_cap() -> None:
    """AC13's limit is `3/minute;20/hour` — two numbers, and the hourly one is
    the load-bearing half. The minute cap alone permits 180 generations an hour
    from one user; at up to `max_lesson_cost_usd` each that is the difference
    between a bounded bill and an unbounded one. The test above pins only
    `3/minute`, so deleting `;20/hour` passes it.
    """
    tree = _executable_tree(_router_path().read_text(encoding="utf-8"))
    fn = _find_function(tree, "generate_chapter_lesson")

    limits = [
        d.args[0].value
        for d in _limit_decorators(fn)
        if d.args and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str)
    ]
    assert any("20/hour" in limit for limit in limits), (
        f"the hourly cap is missing from generate_chapter_lesson's limits: {limits}"
    )


@pytest.mark.unit
def test_generate_route_keys_its_bucket_on_the_user_not_the_request_ip() -> None:
    """The decorator must pass `key_func=_get_user_key` explicitly.

    What breaks if this is dropped: the bucket stops being pinned at the call
    site and silently inherits whatever `Limiter(...)` in `core/rate_limit.py`
    happens to default to. Today that default is `_get_user_key` too, so the
    change is behaviour-neutral RIGHT NOW — which is exactly why nothing notices
    it. The day someone changes the module default (or adds a second Limiter for
    an anonymous route), this route silently becomes IP-keyed and every
    authenticated user behind one egress IP shares a 3/minute bucket on the
    endpoint that spends money. That is D52, which reached production once
    already through precisely this kind of implicitness.

    Asserted on the decorator's KEYWORDS: the existing limit test walks
    `d.args[0]` only and never looks at `d.keywords`, so it passes with the
    kwarg deleted.
    """
    tree = _executable_tree(_router_path().read_text(encoding="utf-8"))
    fn = _find_function(tree, "generate_chapter_lesson")

    keyed = [kw for d in _limit_decorators(fn) for kw in d.keywords if kw.arg == "key_func"]
    assert keyed, (
        "generate_chapter_lesson's @limiter.limit does not pass key_func — the "
        "bucket key is then whatever the module-level Limiter defaults to"
    )
    names = {ast.unparse(kw.value) for kw in keyed}
    assert names == {"_get_user_key"}, (
        f"expected key_func=_get_user_key on the generate route, found {names}"
    )


@pytest.mark.unit
def test_the_fourth_generate_request_in_a_minute_is_really_429() -> None:
    """The two source scans above prove the decorator SAYS 3/minute. This proves
    the limiter is actually consulted on this route.

    What breaks in production if this fails: the cap is configured and inert —
    a caller can hold the generate endpoint open and start pipelines as fast as
    HTTP allows. Every other test in this file calls `limiter.reset()` on the way
    in (deliberately, so the cap never colours an unrelated assertion), which
    means nothing here exercises the limiter end to end. This is the one test
    that does, and it uses its own JWT `sub` so its bucket cannot be disturbed by
    — or disturb — anything else.

    The `Retry-After` header is asserted because the client is expected to back
    off on it rather than spin.
    """
    import jwt as pyjwt

    from app.core.rate_limit import limiter
    from app.dependencies import get_arq_redis, get_current_user
    from app.main import app

    sub = "generate-rate-limit-unique-sub-for-429"
    token = pyjwt.encode(
        {"sub": sub, "exp": 9999999999},
        "test-jwt-secret-that-is-long-enough-32-bytes",
        algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {token}"}

    limiter.reset()
    app.dependency_overrides[get_current_user] = lambda: {**FAKE_USER, "sub": sub}
    app.dependency_overrides[get_arq_redis] = lambda: _arq_pool()
    try:
        with patch(
            "app.modules.content.router.get_supabase",
            # A fresh double per request: the endpoint is otherwise idempotent
            # and the 2nd call would take the 200 branch off a stale scenario.
            # `user_id` matches this test's own JWT sub so `_fetch_owned_book`
            # resolves — the bucket key and the row owner are the same person.
            side_effect=lambda: _FakeSupabase(
                _Scenario(book_row=_book_row(user_id=sub), chapter_row=_chapter_row())
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            statuses = [client.post(_url(), json={}, headers=headers).status_code for _ in range(3)]
            fourth = client.post(_url(), json={}, headers=headers)
    finally:
        app.dependency_overrides.clear()
        limiter.reset()

    assert statuses == [202, 202, 202], f"the first three requests were not accepted: {statuses}"
    assert fourth.status_code == 429, "the 4th generate request in a minute was not rate limited"
    assert "Retry-After" in fourth.headers


@pytest.mark.unit
def test_a_stale_generating_lesson_does_not_block_regeneration() -> None:
    """D53. Nothing but the worker moves a lesson out of `generating`, so a worker
    killed mid-run (OOM, deploy, eviction) leaves a row that never clears. Without
    a staleness bound that chapter+tier can NEVER be generated again — the
    idempotency check keeps returning 200 with the dead lesson, and `?force=true`
    (D54) does not exist. The user's only escape would be a support ticket.
    """
    from app.config import get_settings

    stale = get_settings().arq_job_timeout_s + 60
    sc = _ok_scenario(
        existing_lessons=[
            {
                "lesson_id": EXISTING_LESSON_ID,
                "status": "generating",
                "tier": _default_tier(),
                "created_at": _fresh_iso(age_s=stale),
            }
        ]
    )
    resp, sb, pool = _post(sc, body={"tier": _default_tier()})

    assert resp.status_code == 202, "a stale generating lesson must not block a fresh one"
    assert resp.json()["lesson_id"] == NEW_LESSON_ID
    assert pool.enqueue_job.await_count == 1


@pytest.mark.unit
def test_a_stale_ready_lesson_is_still_returned_never_regenerated() -> None:
    """The staleness bound must apply to `generating` ONLY. A `ready` lesson is
    idempotent forever — ageing it out would regenerate, and charge for, a lesson
    the user already has. Age is evidence that a RUN died, not that a finished
    lesson expired.
    """
    ancient = _fresh_iso(age_s=90 * 24 * 3600)
    sc = _ok_scenario(
        existing_lessons=[
            {
                "lesson_id": EXISTING_LESSON_ID,
                "status": "ready",
                "tier": _default_tier(),
                "created_at": ancient,
            }
        ]
    )
    resp, sb, pool = _post(sc, body={"tier": _default_tier()})

    assert resp.status_code == 200
    assert resp.json()["lesson_id"] == EXISTING_LESSON_ID
    assert pool.enqueue_job.await_count == 0, "a 90-day-old ready lesson must not be regenerated"
