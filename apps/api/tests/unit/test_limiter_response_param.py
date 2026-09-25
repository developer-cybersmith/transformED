"""Guard: every `@limiter.limit(...)`-decorated endpoint must declare a
`response: Response` parameter (D183).

slowapi's `async_wrapper` only calls `response.headers.append(...)` directly
when the endpoint's OWN return value is itself a `starlette.responses.Response`
instance. Otherwise it falls back to `kwargs.get("response")` to find something
to attach the rate-limit headers to — and if the endpoint has no parameter
named `response` at all, that lookup returns `None`, and `_inject_headers`
raises `Exception("parameter response must be an instance of
starlette.responses.Response")` on every successful (non-Response-returning)
call. Confirmed live in production on `PUT .../chapters/{id}/context` and
(latent, same bug) `GET .../chapters/{id}/context`.

A source-level AST scan catches this class of bug the way
`test_node_return_shape.py` catches `return {**state, ...}` -- structurally,
repo-wide, not just at the two sites that happened to be found by hand
(binding rule 6: "wrong at site 19 means wrong at site 1").
"""

from __future__ import annotations

import ast
import pathlib

import pytest

APP_ROOT = pathlib.Path(__file__).parent.parent.parent / "app"


def _is_limiter_limit_call(node: ast.expr) -> bool:
    """Matches `@limiter.limit(...)` (or `@<anything>.limit(...)`)."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "limit"
    )


def _param_names(fn: ast.AsyncFunctionDef | ast.FunctionDef) -> set[str]:
    args = fn.args
    return {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}


def _rate_limited_functions_missing_response_param() -> list[str]:
    offenders: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            if not any(_is_limiter_limit_call(dec) for dec in node.decorator_list):
                continue
            if "response" not in _param_names(node):
                offenders.append(f"{path.relative_to(APP_ROOT.parent)}::{node.name}")
    return offenders


@pytest.mark.unit
def test_every_rate_limited_endpoint_declares_a_response_parameter() -> None:
    offenders = _rate_limited_functions_missing_response_param()
    assert not offenders, (
        "these @limiter.limit(...) endpoints have no `response` parameter -- "
        "slowapi's header injection falls back to `kwargs.get('response')` "
        "and raises on every call whose own return value isn't itself a "
        f"Response (D183): {offenders}"
    )


@pytest.mark.unit
def test_the_scan_itself_actually_catches_the_bug_shape() -> None:
    """Premise check: a synthetic function missing `response` IS flagged, so a
    passing scan above means "nothing found", not "the scan never runs"."""
    tree = ast.parse(
        "import fakelimiter as limiter\n"
        "@limiter.limit('1/minute')\n"
        "async def broken(request: Request, book_id: str) -> None: ...\n"
        "@limiter.limit('1/minute')\n"
        "async def fixed(request: Request, response: Response) -> None: ...\n"
    )
    flagged = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and any(_is_limiter_limit_call(dec) for dec in node.decorator_list)
        and "response" not in _param_names(node)
    ]
    assert flagged == ["broken"]
