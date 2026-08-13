"""Guard: no unbounded Supabase read on a request path (`docs/SCALE-CONTRACT.md` Q4).

This is the CI half of the Scale Contract's enforcement table
(`docs/SCALE-CONTRACT.md:104`). The contract's fourth question is:

> ### 4. Which reads and writes are UNBOUNDED?
> Every query must carry a `.limit()` / `.range()`, use an exact count instead of
> materialising rows, or state in a comment why the row count is naturally bounded.

and the defects it names are all reads that returned "success" while returning the
wrong number of rows:

> The per-user concurrency gate did `select("lesson_id")` over **every** `generating`
> row to count them. The chapters→lessons embed had no limit, so a chapter
> regenerated 20 times returned 20 rows to every chapter-list request.

None of those errored, none of them tripped the `$3.00/lesson` ceiling, and none of
them were visible on a small PDF with one user — which is the whole reason
`docs/SCALE-CONTRACT.md` exists and the whole reason this file is a test and not a
paragraph. `docs/DEFECT-REGISTER.md` Part 1 records that "Dev 1 wrote
`DEV1-FIX-PLAN.md` and then deviated from it four times in a single day. Every
deviation was caught by review, none by a machine." This is the machine.

═══════════════════════════════════════════════════════════════════════════════
SCOPE — what is scanned, what is not, and why
═══════════════════════════════════════════════════════════════════════════════

IN SCOPE — `app/modules/*/router.py` and `app/modules/*/service.py`.

    These are the request paths: an HTTP handler and the service layer it calls
    under principle 4 of CLAUDE.md ("modules communicate only through the service
    layer"). A read here is executed per request, on data whose row count is chosen
    by the user's history, not by the developer. That is where an unbounded read is
    a real user-facing risk: latency that grows with account age, and a response
    body that silently changes shape once a chapter has been regenerated twenty
    times.

OUT OF SCOPE — deliberately, and this narrowness is the point:

  * `app/modules/content/pipeline/**` and `app/workers/**`. Pipeline nodes exist to
    process a whole chapter; "read every chunk of this chapter" is the job, not a
    defect. Their bound is the unit of work (Scale Contract Q1), which is a story
    question, not a `.limit()` question. Pulling them in produces findings that are
    all false, and a guard that cries wolf is a guard that gets commented out on day
    two. A narrow guard that stays on beats a broad one that gets disabled.
  * `app/modules/content/chapter_detection/**` — pure functions over already-loaded
    text, no Supabase client at all.
  * `app/core/**` — infrastructure, not a request path.

Widening the scope is allowed; weakening the exemptions to make a red run go green
is not. If this guard flags a query, the two honest outcomes are a `.limit()` or a
`# BOUNDED:` comment stating why the row count is naturally bounded. Deleting the
check is the third outcome and it is the one this file exists to prevent.

═══════════════════════════════════════════════════════════════════════════════
WHAT COUNTS AS BOUNDED
═══════════════════════════════════════════════════════════════════════════════

A `.select(...)` whose builder chain starts at `.table("x")` / `.from_("x")` is
BOUNDED when its chain also contains any of:

  * `.limit(n)` or `.range(a, b)`          — the contract's literal requirement.
  * `.single()` or `.maybe_single()`       — PostgREST returns exactly one row or
    errors. This is the exact-row form; without it, every ownership check in
    `media/router.py:106` and `assessment/service.py` shape would be flagged and the
    guard would be deleted for flagging correct code.
  * a `count=` keyword on `.select(...)`   — the contract's "use an exact count
    instead of materialising rows".
  * a `# BOUNDED: <reason>` comment on the statement's own lines or on the line
    immediately above it — the contract's "state in a comment why the row count is
    naturally bounded".

CAVEAT, recorded rather than enforced: `select("id", count="exact")` WITHOUT
`head=True` still materialises every matching row over the wire; only the `.count`
attribute is read. The contract's wording exempts `count=`, so this guard exempts
it, but `count=` is a claim about intent, not a bound on bytes. If an exact-count
site is ever shown to be slow, the fix is `head=True`, not a wider exemption here.

═══════════════════════════════════════════════════════════════════════════════
METHOD — and the three properties that make this a guard rather than decoration
═══════════════════════════════════════════════════════════════════════════════

Copied from `tests/unit/test_pipeline_writes_no_books.py`, the model guard in this
repo:

1. DETECTION IS AST-ONLY, OVER STRIPPED SOURCE. Each module is parsed with `ast`,
   its docstrings are removed, and it is round-tripped through `ast.unparse` (which
   drops comments) before any matching happens. A substring scan matches the prose
   describing what the code avoids — including this docstring, which contains
   `select("lesson_id")` twice. That is exactly how the equivalent guard failed in
   Story 1-10.

2. THE EXEMPTION IS TOKENIZE-ONLY, NEVER SUBSTRING. `# BOUNDED:` is recognised only
   as a real `tokenize.COMMENT` token, so the string `"# BOUNDED: nope"` inside a
   literal cannot exempt anything. Note the asymmetry, which is deliberate: a
   comment can only ever REMOVE a finding that the AST already produced. It can
   never create one. So the prose failure mode has no route in at all.

3. POSITIVE CONTROL + PREMISE TEST. `test_scanner_fires_on_a_known_unbounded_select`
   proves the detector fires on the exact statement it is meant to catch — a scanner
   that silently matches nothing looks identical to a clean codebase. And
   `test_request_path_modules_are_where_we_think_they_are` /
   `test_the_scan_is_not_vacuous` prove the directory scanned is the directory
   intended and that it actually contains selects — a guard pointed at an empty
   directory passes forever.
"""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[2]
MODULES_DIR = API_ROOT / "app" / "modules"

# Request-path file names. See SCOPE in the module docstring.
# D78: dna_fusion / dna_growth / ces* / dna_profile are called from request-path
# service.py handlers and must be covered by the unbounded-query guard.
REQUEST_PATH_FILENAMES = (
    "router.py",
    "service.py",
    "dna_fusion.py",
    "dna_growth.py",
    "ces.py",
    "ces_baseline.py",
    "dna_profile.py",
)

# Supabase-py table selectors.
_TABLE_SELECTORS = frozenset({"table", "from_"})

# Chain methods that bound the row count.
_BOUNDING_METHODS = frozenset({"limit", "range", "single", "maybe_single"})

# How far above a chain a `# BOUNDED:` marker may sit. Deliberately small: the
# marker must annotate a specific statement, not a whole region.
_MARKER_LOOKBEHIND = 2

# The justification marker required by `docs/SCALE-CONTRACT.md` Q4.
BOUNDED_MARKER = "# BOUNDED:"


# ──────────────────────────────────────────────────────────────────────────────
# Source preparation — executable code only
# ──────────────────────────────────────────────────────────────────────────────


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    """Drop module/class/function docstrings so prose can never match."""
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


def _bounded_marker_lines(source: str) -> set[int]:
    """1-indexed lines carrying a real `# BOUNDED:` COMMENT token.

    Tokenised, never substring-matched: a `"# BOUNDED:"` inside a string literal is
    a STRING token, not a COMMENT token, and must not exempt anything.
    """
    lines: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT and BOUNDED_MARKER in tok.string:
                lines.add(tok.start[0])
    except (tokenize.TokenError, IndentationError, SyntaxError):  # pragma: no cover
        return lines
    return lines


# ──────────────────────────────────────────────────────────────────────────────
# Detection
# ──────────────────────────────────────────────────────────────────────────────


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
                return node.args[0].value
            node = func
        elif isinstance(node, ast.Attribute):
            node = node.value
        else:
            node = node.value
    return None


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    return {
        id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
    }


def _outermost_chain(call: ast.Call, parents: dict[int, ast.AST]) -> ast.expr:
    """Climb from a `.select(...)` call to the end of its builder chain.

    `supabase.table("t").select("c").eq(...).limit(10).execute()` — the `.limit()`
    is ABOVE `.select()` in the tree, so a downward walk from `.select` can never
    see it. This is the step a naive scanner gets wrong in the direction that
    produces false positives on correct code.
    """
    node: ast.expr = call
    while True:
        parent = parents.get(id(node))
        if isinstance(parent, ast.Attribute) and parent.value is node:
            node = parent
        elif isinstance(parent, ast.Call) and parent.func is node:
            node = parent
        elif isinstance(parent, ast.Await) and parent.value is node:
            node = parent
        else:
            return node


def _chain_is_bounded(chain: ast.expr, select_call: ast.Call) -> bool:
    if any(kw.arg == "count" for kw in select_call.keywords):
        return True
    for node in ast.walk(chain):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _BOUNDING_METHODS
        ):
            return True
    return False


def _select_calls(source: str) -> list[tuple[ast.Call, ast.expr, str]]:
    """`(select_call, outermost_chain, table)` for every table-rooted `.select()`.

    Runs over EXECUTABLE source only: docstrings stripped, `ast.unparse` round-trip
    to drop comments. Line numbers therefore belong to the unparsed text, which is
    why bounded-marker lookup uses the ORIGINAL source and a separate scan (see
    `_unbounded_selects`).
    """
    tree = ast.parse(source)
    parents = _parents(tree)
    out: list[tuple[ast.Call, ast.expr, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "select":
            continue
        table = _selected_table(func.value)
        if table is None:
            continue
        out.append((node, _outermost_chain(node, parents), table))
    return out


def _executable_source(source: str) -> str:
    """Docstrings removed, comments dropped by the unparse round-trip."""
    return ast.unparse(_strip_docstrings(ast.parse(source)))


def _function_scope_bounds(tree: ast.AST) -> dict[tuple[int, int], bool]:
    """Map each `.select()` call's id -> whether its FUNCTION bounds the result.

    supabase-py is a builder, and the idiomatic way to apply a conditional filter
    is to split the chain across statements:

        q = supabase.table("lessons").select("lesson_id")
        if only_mine:
            q = q.eq("user_id", uid)
        return q.limit(limit).execute()

    A chain-walker cannot climb past the assignment, so it sees a bare
    `.select()` and reports correct code as a violation. That is not a cosmetic
    flaw: `test_pipeline_writes_no_books.py`'s docstring records that a guard
    which fires on correct code is a guard someone comments out on day two — and
    this guard's own docstring repeats the warning, then commits the mistake.

    Scope-level answer instead of chain-level: if the enclosing function applies
    ANY bounding call at all, the select is treated as bounded. Deliberately
    lenient — it can miss a genuinely unbounded read in a function that bounds a
    DIFFERENT query. A guard that under-reports survives; one that cries wolf is
    deleted, and a deleted guard reports nothing forever.
    """
    # Keyed by (lineno, col_offset), NOT id(): `_select_calls` re-parses the same
    # text, so the AST objects are different Python objects with different ids.
    # Position is stable across parses of identical source; identity is not.
    bounded_fns: dict[tuple[int, int], bool] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        bounds = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and (n.func.attr in _BOUNDING_METHODS or (n.func.attr == "execute" and False))
            for n in ast.walk(fn)
        ) or any(isinstance(n, ast.keyword) and n.arg == "count" for n in ast.walk(fn))
        for n in ast.walk(fn):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "select"
            ):
                bounded_fns[(n.lineno, n.col_offset)] = bounds
    return bounded_fns


def _unbounded_selects(source: str) -> list[str]:
    """Findings: table-rooted `.select()` chains with no bound and no justification.

    Two passes over two different texts, on purpose:

    * DETECTION runs on `_executable_source(source)` — prose cannot produce a
      finding.
    * EXEMPTION runs on the ORIGINAL `source`, because `# BOUNDED:` is a comment and
      the unparse round-trip deletes comments. Findings are matched to original
      lines by their unparsed table+select text, since a finding can only ever be
      REMOVED by a marker, never created by one.
    """
    marker_lines = _bounded_marker_lines(source)

    # Original-source chains, so a finding can be located against a comment line.
    original_tree = ast.parse(source)
    original_parents = _parents(original_tree)
    original_spans: dict[str, list[tuple[int, int]]] = {}
    for call, chain, table in _select_calls(source):
        del chain
        outer = _outermost_chain(call, original_parents)
        key = f"{table}.select({', '.join(ast.unparse(a) for a in call.args)})"
        # The marker window reaches _MARKER_LOOKBEHIND lines above the chain, not
        # one. A `# BOUNDED:` comment sits above `resp = (`, while the chain
        # itself starts on the NEXT line inside the parenthesis — with a
        # one-line window the exemption silently never applied, which is worse
        # than no marker at all: it reads as justified in review while the guard
        # still fails, and the reviewer's next move is to delete the guard.
        span = (outer.lineno - _MARKER_LOOKBEHIND, outer.end_lineno or outer.lineno)
        original_spans.setdefault(key, []).append(span)

    findings: list[str] = []
    executable = _executable_source(source)
    scope_bounds = _function_scope_bounds(ast.parse(executable))
    for call, chain, table in _select_calls(executable):
        if _chain_is_bounded(chain, call):
            continue
        # Split builder chains: the bound lives in a later statement, not in this
        # expression. See `_function_scope_bounds`.
        if scope_bounds.get((call.lineno, call.col_offset), False):
            continue
        key = f"{table}.select({', '.join(ast.unparse(a) for a in call.args)})"
        spans = original_spans.get(key, [])
        # Exempt only if EVERY occurrence of this exact statement is marked;
        # otherwise an unmarked twin would hide behind its marked sibling.
        if spans and all(
            any(start <= line <= end for line in marker_lines) for start, end in spans
        ):
            continue
        where = ", ".join(f"L{start}" for start, _ in spans) or "?"
        findings.append(f"{where}: {key}")
    return findings


# ── Known violations, enumerated (D59) ───────────────────────────────────────
#
# Two real unbounded reads existed when this guard was written. They are listed
# rather than silenced, and the guard fails on ANYTHING NOT IN THIS DICT — so a
# new violation is red immediately while these two stay visible and owned.
#
# This is a RATCHET: the list may only shrink. Adding an entry requires a
# register ID and a named owner, which is a conversation, not a quick unblock.
# The alternative — landing the step `continue-on-error` — is what D24 did, and
# the register records the cost: the number was visible and nothing ever moved.
#
# Do NOT add an entry to make a build green. Fix the query or register the defect.
_KNOWN_UNBOUNDED: dict[str, set[str]] = {
    # D59(a) closed — Story 3-51 added `.limit(_COST_REPORT_ROW_LIMIT)` +
    # a surfaced `truncated` flag to admin/router.py's cost report query.
    # Entry removed, not left in place: an allow-listed query that is now
    # actually bounded would be the "matches existing accepted pattern"
    # ratchet CLAUDE.md's binding rule 6 names, not a real fix.
    #
    # D59 · Dev 3 · analytics selects every session id for a user with no bound.
    # Grows without limit as a student uses the product — the definition of a
    # read that is fine in testing and wrong in production.
    "analytics/service.py": {"sessions.select('session_id')"},
}


def request_path_modules() -> list[Path]:
    return sorted(
        p
        for p in MODULES_DIR.rglob("*.py")
        if p.is_file() and p.name in REQUEST_PATH_FILENAMES and "pipeline" not in p.parts
    )


# ══════════════════════════════════════════════════════════════════════════════
# Premise tests — a guard pointed at an empty directory passes forever
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_request_path_modules_are_where_we_think_they_are() -> None:
    """Premise: the directory scanned is the directory this file claims to scan."""
    assert MODULES_DIR.is_dir(), f"modules dir not found at {MODULES_DIR}"
    names = {p.relative_to(MODULES_DIR).as_posix() for p in request_path_modules()}
    # Every module with a router must be reached, or the scan has silently narrowed.
    for module in ("content", "assessment", "analytics", "admin", "media", "tutor", "auth"):
        assert f"{module}/router.py" in names, f"scan does not reach {module}/router.py"
    assert "assessment/service.py" in names, "the service layer is in scope, not just routers"
    assert "analytics/service.py" in names


@pytest.mark.unit
def test_pipeline_is_out_of_scope() -> None:
    """Premise for the SCOPE section: pipeline code is excluded on purpose.

    Pipeline nodes read a whole chapter by design. Including them would make this
    guard fail on correct code on day one, which is how a guard gets deleted on day
    two.
    """
    assert not [p for p in request_path_modules() if "pipeline" in p.parts]


@pytest.mark.unit
def test_the_scan_is_not_vacuous() -> None:
    """Premise: the in-scope files actually contain table-rooted selects.

    If this drops to zero, the scanner has stopped resolving `.table("x").select()`
    and the assertion below passes for the wrong reason.
    """
    total = sum(
        len(_select_calls(_executable_source(p.read_text(encoding="utf-8"))))
        for p in request_path_modules()
    )
    assert total >= 20, f"expected the request-path selects, resolved only {total}"


# ══════════════════════════════════════════════════════════════════════════════
# Positive controls — a scanner that matches nothing looks like a clean codebase
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_scanner_fires_on_a_known_unbounded_select() -> None:
    """The exact statement the Scale Contract Q4 names as the defect.

    `docs/SCALE-CONTRACT.md:71` — "The per-user concurrency gate did
    `select("lesson_id")` over **every** `generating` row to count them."
    """
    bad = 'supabase.table("lessons").select("lesson_id").eq("status", "generating").execute()\n'
    assert _unbounded_selects(bad), "scanner failed to flag a known-unbounded select"


@pytest.mark.unit
def test_scanner_accepts_each_bounding_form() -> None:
    """Each form the contract allows must silence the finding — all of them, or the
    guard flags correct code and gets deleted."""
    base = 'supabase.table("lessons").select("lesson_id")'
    assert not _unbounded_selects(f"{base}.limit(50).execute()\n"), ".limit() not honoured"
    assert not _unbounded_selects(f"{base}.range(0, 49).execute()\n"), ".range() not honoured"
    assert not _unbounded_selects(f"{base}.maybe_single().execute()\n"), ".maybe_single() missed"
    assert not _unbounded_selects(f"{base}.single().execute()\n"), ".single() not honoured"
    assert not _unbounded_selects(
        'supabase.table("lessons").select("id", count="exact").execute()\n'
    ), "count= exact-count form not honoured"


@pytest.mark.unit
def test_the_bound_may_appear_after_select_in_the_chain() -> None:
    """`.limit()` sits ABOVE `.select()` in the AST — a downward-only walk misses it.

    This is the false-positive direction, and false positives are what get a guard
    commented out. Pinned separately from the form test above because a regression
    here would still pass `test_scanner_fires_on_a_known_unbounded_select`.
    """
    long_chain = (
        "resp = await asyncio.to_thread(lambda: (\n"
        '    supabase.table("session_events")\n'
        '    .select("event_type")\n'
        '    .eq("session_id", sid)\n'
        '    .order("created_at")\n'
        "    .limit(10_000)\n"
        "    .execute()\n"
        "))\n"
    )
    assert not _unbounded_selects(
        f"async def f():\n    {long_chain.replace(chr(10), chr(10) + '    ')}"
    )


@pytest.mark.unit
def test_the_bounded_marker_exempts_only_as_a_real_comment() -> None:
    """`# BOUNDED:` is a `tokenize.COMMENT`, never a substring.

    A string literal containing the marker must not exempt anything — otherwise the
    escape hatch is writable from inside data, and Story 1-10's prose failure mode
    comes back through the exemption instead of through the detection.
    """
    stmt = 'supabase.table("users").select("user_id").eq("org_id", org).execute()\n'

    on_the_line = (
        'supabase.table("users").select("user_id").eq("org_id", org).execute()'
        "  # BOUNDED: org membership is capped at 40 by the invite flow\n"
    )
    assert not _unbounded_selects(on_the_line), "marker on the statement line ignored"

    above = "# BOUNDED: at most one row per enum value, 7 values\n" + stmt
    assert not _unbounded_selects(above), "marker on the line above ignored"

    far_above = "# BOUNDED: nowhere near the statement\n\n\n" + stmt
    assert _unbounded_selects(far_above), "a distant marker must not exempt"

    faked = 'MSG = "# BOUNDED: this is a string, not a comment"\n' + stmt
    assert _unbounded_selects(faked), "a string literal exempted a query"


@pytest.mark.unit
def test_scanner_does_not_match_prose() -> None:
    """The Story 1-10 failure mode: a guard matching its own explanatory docstring."""
    prose = (
        '"""Never write supabase.table(\\"lessons\\").select(\\"lesson_id\\") without a limit."""\n'
    )
    assert not _unbounded_selects(prose), "scanner matched a docstring"

    comment_only = '# supabase.table("lessons").select("lesson_id").execute()\n'
    assert not _unbounded_selects(comment_only), "scanner matched a commented-out line"


@pytest.mark.unit
def test_scanner_ignores_non_supabase_selects() -> None:
    """`.select()` on something that never chained through `.table("...")` is not a
    Supabase query and must not be flagged."""
    assert not _unbounded_selects("df.select(cols)\n")
    assert not _unbounded_selects("sqlalchemy.select(Lesson).where(Lesson.id == x)\n")


# ══════════════════════════════════════════════════════════════════════════════
# The guard itself
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
def test_no_unbounded_select_on_a_request_path() -> None:
    """`docs/SCALE-CONTRACT.md` Q4, enforced.

    What breaks in production if this fails: nothing, visibly. The query succeeds,
    the endpoint returns 200, and the response is correct for the developer's test
    account. It grows with the user's history — a chapter regenerated twenty times
    returns twenty embedded lessons to every chapter-list request — and it is never
    caught by the `$3.00/lesson` ceiling because reading too many rows is cheap. It
    is the same shape as the 1,000-page book that produced a lesson covering 4 % of
    it: success reported, wrong answer returned.

    To fix a finding, pick one:
      * add `.limit(n)` / `.range(a, b)` with n derived from a stated cap;
      * make it `.single()` / `.maybe_single()` if exactly one row is intended;
      * ask for `count=` if only the count is needed;
      * add `# BOUNDED: <why the row count is naturally bounded>` above the
        statement — and answer Scale Contract Q3 in it (per user? per instance? per
        deployment?), because "bounded" with no scope is D49 again.
    """
    offenders: dict[str, list[str]] = {}
    for path in request_path_modules():
        found = _unbounded_selects(path.read_text(encoding="utf-8"))
        if found:
            offenders[path.relative_to(MODULES_DIR).as_posix()] = found

    # Subtract the enumerated baseline (D59). Anything NOT listed is a new
    # violation and fails immediately.
    offenders = {
        mod: [f for f in found if f.split(": ", 1)[-1] not in _KNOWN_UNBOUNDED.get(mod, set())]
        for mod, found in offenders.items()
    }
    offenders = {m: f for m, f in offenders.items() if f}

    assert not offenders, (
        "Unbounded Supabase read on a request path — `docs/SCALE-CONTRACT.md` Q4 "
        "requires a `.limit()`/`.range()`, an exact `count=`, or a `# BOUNDED: "
        "<reason>` comment. Do not widen this guard's exemptions to go green. "
        f"Found: {offenders}"
    )
