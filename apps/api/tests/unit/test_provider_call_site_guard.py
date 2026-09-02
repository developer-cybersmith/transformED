"""Guard (Story 5-8b, AC6): each image provider is instantiated from exactly
ONE call site in `graph.py` — `_generate_image_with_fallback`.

Why this exists: the whole point of a fallback CHAIN is that exactly one
function decides which provider to try in which order. If a future change
accidentally instantiates `NanoBananaProvider` or `OpenAIImageProvider` from
a second location (a copy-pasted helper, a debug shortcut, a new node that
reaches for a provider directly instead of going through the chain), that
second call site bypasses the circuit breaker/cost-ceiling/fallback
semantics the chain exists to enforce — silently, since nothing else in this
suite checks WHERE a provider is constructed, only what happens once it is.

Detection is pure AST: walk `graph.py` for every `ast.Call` whose `func` is
either a bare `Name` or a module-qualified `Attribute` matching one of the
two provider class names, then climb the tree (via a parent-lookup map, same
technique as `test_unbounded_queries.py`'s `_parents`/`_outermost_chain`) to
the nearest enclosing function and assert its name is
`_generate_image_with_fallback`. No docstring/comment stripping is needed
here (unlike the query-boundedness guard) — a plain string literal never
parses as an `ast.Call`, so prose can never produce a false positive the way
it can for substring-based scanners.

Known, accepted scope limit (review finding, matching this repo's own
convention of stating a guard's boundary rather than pretending it is
complete): arbitrary indirection — aliasing the class to a variable, then
calling the variable, or calling via `getattr` — evades this scanner. Only a
full data-flow analysis catches those, which is out of proportion to the
realistic risk here: a copy-pasted or newly-added call site looks like
`ClassName(...)` or `module.ClassName(...)`, not a deliberately obfuscated
indirection. If that changes, widen the scanner; do not weaken this test to
make a red run green.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_GRAPH_PATH = (
    Path(__file__).resolve().parents[2] / "app" / "modules" / "content" / "pipeline" / "graph.py"
)
_EXPECTED_CALL_SITE = "_generate_image_with_fallback"
_PROVIDER_CLASS_NAMES = frozenset({"NanoBananaProvider", "OpenAIImageProvider"})


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    return {
        id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
    }


def _enclosing_function_name(node: ast.AST, parents: dict[int, ast.AST]) -> str | None:
    """Climb from *node* to the nearest enclosing function def's name, or
    None if *node* is at module scope (not inside any function)."""
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
            return current.name
        current = parents.get(id(current))
    return None


def _provider_instantiation_sites(source: str) -> list[tuple[str, str | None]]:
    """`(provider_class_name, enclosing_function_name_or_None)` for every
    direct instantiation call found anywhere in *source* — both the bare-name
    form (`NanoBananaProvider(...)`, matching this repo's actual `from ...
    import NanoBananaProvider` style) and the module-qualified form
    (`some_module.NanoBananaProvider(...)`, review finding: the original
    version only matched `ast.Name`, missing this shape entirely).

    Known, accepted limitation (same honesty this repo's other AST guards —
    e.g. test_unbounded_queries.py — document about their own scope): this
    cannot catch arbitrary indirection such as aliasing the class to a
    variable (`cls = NanoBananaProvider; cls(...)`) or calling it via
    `getattr`. Those require full data-flow analysis, not a syntax-level
    scan, and are a materially less likely accidental-reintroduction shape
    than a straightforward second `ClassName(...)` or `module.ClassName(...)`
    call — which is exactly what a copy-pasted call site looks like.
    """
    tree = ast.parse(source)
    parents = _parents(tree)
    sites: list[tuple[str, str | None]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in _PROVIDER_CLASS_NAMES:
            sites.append((func.id, _enclosing_function_name(node, parents)))
        elif isinstance(func, ast.Attribute) and func.attr in _PROVIDER_CLASS_NAMES:
            sites.append((func.attr, _enclosing_function_name(node, parents)))
    return sites


@pytest.mark.unit
def test_the_scan_is_not_vacuous() -> None:
    """If this ever returns zero sites, the AST matching itself is broken
    (e.g. graph.py stopped importing/calling these classes some other way) —
    a guard with nothing to check is not a guard."""
    source = _GRAPH_PATH.read_text(encoding="utf-8")
    sites = _provider_instantiation_sites(source)
    assert sites, (
        "expected to find at least one NanoBananaProvider/OpenAIImageProvider "
        "instantiation in graph.py — the scan itself may be broken"
    )


@pytest.mark.unit
def test_scanner_detects_a_planted_second_call_site() -> None:
    """Proves the scanner actually fires on a violation, not just that it
    passes on today's correct code — the same discipline
    test_node_return_shape.py's `test_guard_detects_a_planted_violation`
    already established for a different guard in this repo."""
    planted = (
        "async def some_other_node(state):\n"
        "    provider = NanoBananaProvider(lesson_id='x')\n"
        "    return {'x': provider}\n"
    )
    sites = _provider_instantiation_sites(planted)
    assert sites == [("NanoBananaProvider", "some_other_node")]


@pytest.mark.unit
def test_scanner_detects_a_module_qualified_second_call_site() -> None:
    """Review finding (test-coverage): the first version of this scanner only
    matched the bare-name call shape (`NanoBananaProvider(...)`), missing the
    module-qualified shape (`some_module.NanoBananaProvider(...)`) entirely —
    a real, plausible way a second call site could be introduced (a `import
    app.providers.image.nano_banana as nb` style import, unlike this repo's
    actual `from ... import NanoBananaProvider` convention)."""
    planted = (
        "import app.providers.image.nano_banana as nb\n\n"
        "async def some_other_node(state):\n"
        "    provider = nb.NanoBananaProvider(lesson_id='x')\n"
        "    return {'x': provider}\n"
    )
    sites = _provider_instantiation_sites(planted)
    assert sites == [("NanoBananaProvider", "some_other_node")]


@pytest.mark.unit
def test_both_providers_are_instantiated_only_inside_the_fallback_function() -> None:
    """The real assertion: every real instantiation site in graph.py, for
    BOTH provider classes, resolves to `_generate_image_with_fallback` and
    nothing else."""
    source = _GRAPH_PATH.read_text(encoding="utf-8")
    sites = _provider_instantiation_sites(source)

    found_classes = {cls for cls, _fn in sites}
    assert _PROVIDER_CLASS_NAMES <= found_classes, (
        f"expected both {sorted(_PROVIDER_CLASS_NAMES)} to be instantiated somewhere "
        f"in graph.py, found only {sorted(found_classes)}"
    )

    misplaced = [(cls, fn) for cls, fn in sites if fn != _EXPECTED_CALL_SITE]
    assert not misplaced, (
        f"found provider instantiation(s) outside {_EXPECTED_CALL_SITE!r}: {misplaced} — "
        "a provider must only ever be constructed inside the one function that "
        "owns the fallback chain's circuit-breaker/cost-ceiling semantics"
    )
