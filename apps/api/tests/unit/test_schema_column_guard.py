"""D22 — every Supabase column named in app code must exist in the migrations.

Why this file exists
--------------------
On 2026-07-29, Story 2-31 narrowed a `select("*")` and named `completed_at` — a column on
`lesson_jobs`, NOT on `lessons`. Under `select("*")` that was harmless; naming it explicitly
makes PostgREST reject the whole query with `42703`, so `GET /lessons` would have failed for
every user on every request.

**All four tests for that endpoint mocked Supabase and asserted the select STRING.** A mock
has no Postgres catalog, so it cannot 42703. The bug was invisible to a green suite, and was
caught by a human reading `supabase/migrations/`.

The fix shipped with a guard covering `lessons` only. A root-cause analysis then replanted
the same defect on `sessions` and the suite stayed green — **776 passed, 0 failed**. The
class was live at 43 other call sites.

This test closes the class rather than the instance. It is the RC-1 counter-measure that
needs no infrastructure: it reconciles the consumer (our code) against the producer (the
migrations) without a database.

Scope and honest limits
-----------------------
This checks *column existence*, which is what `42703` is. It does NOT check types,
nullability, RLS, or whether a query is semantically right — only a real database can do
that, which is why `docs/DEFECT-REGISTER.md` BD-3 (a real-dependency CI job) remains the
higher-leverage fix. This is the cheap 80%.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_API_ROOT = Path(__file__).resolve().parents[2]
_APP = _API_ROOT / "app"
_MIGRATIONS = _API_ROOT.parents[1] / "supabase" / "migrations"

# PostgREST verbs whose first string argument names a column (or comma-list of them).
_COLUMN_VERBS = {"select", "eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "order", "is_"}

# PostgREST select-list syntax we must strip before checking a name:
#   "alias:col->path->>leaf"  → col      (JSONB path selector)
#   "table!inner(a,b)"        → embedded resource, skipped entirely
#   "count"                   → aggregate
_AGGREGATES = {"count", "*"}


def _true_schema() -> dict[str, set[str]]:
    """Build {table: {columns}} from the migrations — the producer side of the contract."""
    tables: dict[str, set[str]] = {}
    sql = "\n".join(p.read_text(encoding="utf-8") for p in sorted(_MIGRATIONS.glob("*.sql")))

    for m in re.finditer(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?(\w+)\s*\((.*?)\n\)\s*;",
        sql,
        re.S | re.I,
    ):
        table, body = m.group(1), m.group(2)
        cols: set[str] = set()
        for raw in body.split("\n"):
            line = raw.strip().rstrip(",")
            if not line or line.startswith("--"):
                continue
            first = line.split()[0].strip('"')
            # Skip table-level constraint clauses, which are not columns.
            if first.upper() in {
                "PRIMARY",
                "FOREIGN",
                "UNIQUE",
                "CHECK",
                "CONSTRAINT",
                "EXCLUDE",
                "LIKE",
            }:
                continue
            if re.fullmatch(r"[a-z_][a-z0-9_]*", first):
                cols.add(first)
        tables[table] = cols

    # Later migrations add columns. NOTE: a single statement may add several —
    # `ALTER TABLE t ADD COLUMN a ..., ADD COLUMN b ..., ADD COLUMN c ...;` — and only
    # the first clause carries the table name. Matching per-clause instead of
    # per-statement was a real bug in this guard: it reported chunks.embedding and
    # chunks.token_count as missing when 20260625000000 adds both in one statement.
    for stmt in re.finditer(
        r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:public\.)?(\w+)(.*?);",
        sql,
        re.S | re.I,
    ):
        table, body = stmt.group(1), stmt.group(2)
        for col in re.finditer(r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", body, re.I):
            tables.setdefault(table, set()).add(col.group(1))

    return tables


def _chain_calls(node: ast.Call) -> list[tuple[str, ast.Call]]:
    """Unwind `sb.table("x").select(...).eq(...)` into [(method, call), ...]."""
    out: list[tuple[str, ast.Call]] = []
    cur: ast.expr = node
    while isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute):
        out.append((cur.func.attr, cur))
        cur = cur.func.value
    return out


def _columns_in_select(arg: str) -> list[str]:
    """Extract bare column names from a PostgREST select list.

    Embedded resources — `lessons(user_id)`, `lessons!inner(a,b)` — name columns on a
    DIFFERENT table and are skipped: verifying them needs the FK graph, not just the
    column map. Getting this wrong produced phantom findings like `lesson_jobs.lessons)`.
    """
    cols: list[str] = []
    buf = ""
    depth = 0
    embedded = False

    for ch in arg:
        if ch == "(":
            depth += 1
            embedded = True
            continue
        if ch == ")":
            depth -= 1
            continue
        if ch == "," and depth == 0:
            if not embedded:
                cols.append(buf)
            buf = ""
            embedded = False
            continue
        if depth == 0:
            buf += ch
    if not embedded:
        cols.append(buf)

    out: list[str] = []
    for spec in cols:
        spec = spec.strip()
        if not spec or "!" in spec:  # `!inner` etc. is an embedded-resource modifier
            continue
        if ":" in spec:  # alias:source
            spec = spec.split(":", 1)[1]
        spec = spec.split("->", 1)[0].strip()  # JSONB path selector → root column
        if spec and spec not in _AGGREGATES:
            out.append(spec)
    return out


def _module_str_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"` bindings, so `.select(_LIST_COLUMNS)` is checkable.

    This is not a nicety. The first version of this guard only resolved `ast.Constant`
    arguments, so it skipped `content/router.py`'s `.select(_LIST_COLUMNS)` — the exact
    call site D9 broke. Replanting D9 there passed the guard. A guard blind to the most
    important call site is worse than none, because it certifies.
    """
    consts: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                consts[t.id] = value.value
    return consts


def _collect_usages() -> list[tuple[Path, int, str, str]]:
    """Return [(file, lineno, table, column)] for every column named against a table."""
    found: list[tuple[Path, int, str, str]] = []

    for py in sorted(_APP.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8-sig"), filename=str(py))
        consts = _module_str_constants(tree)

        def _as_str(node: ast.expr, consts: dict[str, str] = consts) -> str | None:
            # consts bound as a default: it is a loop variable, and a late-binding
            # closure here would resolve every file's constants against the LAST
            # file parsed (ruff B023).
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.Name):
                return consts.get(node.id)
            return None

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            chain = _chain_calls(node)
            table_call = next((c for name, c in chain if name == "table" and c.args), None)
            if table_call is None:
                continue
            table = _as_str(table_call.args[0])
            if table is None:
                continue  # dynamic table name — cannot check statically

            for method, call in chain:
                if method not in _COLUMN_VERBS or not call.args:
                    continue
                arg = _as_str(call.args[0])
                if arg is None:
                    continue
                if method == "select":
                    names = _columns_in_select(arg)
                else:
                    # A dotted name in a filter/order refers to an EMBEDDED resource
                    # (`.gte("lessons.created_at", ...)`), not a column on the base
                    # table. Valid PostgREST; out of scope without the FK graph.
                    names = [] if "." in arg else [arg]
                for col in names:
                    found.append((py, call.lineno, table, col))
    return found


@pytest.mark.unit
def test_migrations_parse_into_a_usable_schema() -> None:
    """Guard the guard: if the SQL parser silently returns nothing, every other
    assertion in this file becomes vacuous."""
    schema = _true_schema()
    assert len(schema) >= 10, f"expected the full table set, parsed only {sorted(schema)}"
    # Spot-check the exact fact D9 turned on.
    assert "completed_at" in schema["lesson_jobs"]
    assert "completed_at" not in schema["lessons"], (
        "if this ever passes, the premise of D9 changed — re-read the migrations"
    )


@pytest.mark.unit
def test_every_column_named_in_app_code_exists_in_the_migrations() -> None:
    """D22. The instance (D9) was guarded for `lessons` only; this closes the class."""
    schema = _true_schema()
    usages = _collect_usages()

    assert usages, "found no .table(...) usages — the AST walker is broken, not the code"

    bad: list[str] = []
    for path, lineno, table, col in usages:
        if table not in schema:
            continue  # not a table we own (or a view) — out of scope, not a failure
        if col not in schema[table]:
            rel = path.relative_to(_API_ROOT)
            bad.append(f"  {rel}:{lineno} — {table}.{col} does not exist")

    assert not bad, (
        "Column(s) referenced that the migrations do not define. PostgREST answers this "
        "with 42703 and fails the WHOLE query — a mocked Supabase client cannot:\n"
        + "\n".join(sorted(bad))
    )
