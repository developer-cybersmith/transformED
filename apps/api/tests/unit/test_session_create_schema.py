"""Story 3-55 — D102 (was D92) and D104 (was D94) enforcement tests.

D102 (was D92) — `session_events` SELECT in `dna_fusion.py` must carry `.limit()`.
D104 (was D94) — `SessionCreate.lesson_id` must validate UUID format before the DB cast.

D103 (was D93, CI scan scope) lives in `test_unbounded_queries.py` alongside the other
premise tests for the scanner.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

# ── Shared paths ──────────────────────────────────────────────────────────────

_API_ROOT = Path(__file__).resolve().parents[2]
_MODULES_DIR = _API_ROOT / "app" / "modules"
_DNA_FUSION = _MODULES_DIR / "assessment" / "dna_fusion.py"

# ── AST helpers (mirrors the scanner in test_unbounded_queries.py) ────────────

_BOUNDING_METHODS = frozenset({"limit", "range", "single", "maybe_single"})


def _selected_table(node: ast.expr) -> str | None:
    while isinstance(node, ast.Call | ast.Attribute | ast.Subscript):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in {"table", "from_"}
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
    return {id(c): p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}


def _outermost_chain(call: ast.Call, parents: dict[int, ast.AST]) -> ast.expr:
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
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in _BOUNDING_METHODS
        for n in ast.walk(chain)
    )


# ── D102 (was D92) — session_events bounded ─────────────────────────────────────────────


@pytest.mark.unit
def test_dna_fusion_session_events_is_bounded() -> None:
    """D102 (was D92) — the `session_events` SELECT in `dna_fusion.py` must carry `.limit()`.

    A student can generate many events in a single session (jargon hovers, skips,
    help requests). Without a limit, the session-end fusion call materialises every
    event row, growing without bound as the student uses the product.

    Scale Contract Q4: every read on a request path is bounded or explicitly justified.
    """
    source = _DNA_FUSION.read_text(encoding="utf-8")
    tree = ast.parse(source)
    parents = _parents(tree)

    bounded_session_events = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "select"):
            continue
        if _selected_table(func.value) != "session_events":
            continue
        chain = _outermost_chain(node, parents)
        if _chain_is_bounded(chain, node):
            bounded_session_events = True

    assert bounded_session_events, (
        "D102 (was D92): the `session_events` SELECT in dna_fusion.py has no .limit() — "
        "add .limit(10_000) to cap event rows per session. "
        "Scale Contract Q4 requires every request-path read to be bounded."
    )


# ── D104 (was D94) — SessionCreate.lesson_id UUID validation ────────────────────────────


@pytest.mark.unit
def test_session_create_validates_uuid_format() -> None:
    """D104 (was D94) — `SessionCreate.lesson_id` must reject non-UUID strings at Pydantic.

    Without a validator, any non-UUID string (including a typo like "x") passes
    Pydantic validation, reaches the DB UUID cast, and 500s with a Postgres error
    that returns no actionable information to the caller.

    After the fix: invalid strings raise `ValidationError` immediately, and a
    valid UUID string is accepted unchanged (string type preserved for downstream).
    """
    from app.modules.assessment.schemas import SessionCreate

    # Invalid strings — all must raise ValidationError
    invalid_inputs = [
        "not-a-uuid",
        "x",
        "123",
        "00000000-0000-0000-0000-00000000000",   # too short (35 chars)
        "00000000-0000-0000-0000-0000000000000",  # too long (37 chars)
        "gggggggg-gggg-gggg-gggg-gggggggggggg",  # invalid hex chars
    ]
    for bad in invalid_inputs:
        with pytest.raises(ValidationError):
            SessionCreate(lesson_id=bad)

    # Empty string — must also be rejected
    with pytest.raises(ValidationError):
        SessionCreate(lesson_id="")

    # Valid UUID string — must be accepted
    valid_uuid = "123e4567-e89b-12d3-a456-426614174000"
    sc = SessionCreate(lesson_id=valid_uuid)
    # Type preserved as str so router.py's `body.lesson_id` needs no changes
    assert isinstance(sc.lesson_id, str)
    assert sc.lesson_id == valid_uuid


@pytest.mark.unit
def test_session_create_accepts_uppercase_uuid() -> None:
    """UUID case-insensitivity: both upper and lower case hex are valid RFC 4122.

    Python's `uuid.UUID.__str__` always returns lowercase, so the validator
    normalises the stored value to lowercase regardless of input casing.
    """
    from app.modules.assessment.schemas import SessionCreate

    upper = "123E4567-E89B-12D3-A456-426614174000"
    sc = SessionCreate(lesson_id=upper)
    assert isinstance(sc.lesson_id, str)
    # str(uuid.UUID(upper)) normalises to lowercase
    assert sc.lesson_id == upper.lower()
