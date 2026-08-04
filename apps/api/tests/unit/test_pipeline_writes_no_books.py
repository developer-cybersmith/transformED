"""Guard (Story 1-11, AC8): the content pipeline never writes to `books`.

`book_ingest_job` (`app/workers/jobs/book_ingest.py`) is the single writer of the
`books` row — it owns `status` and `page_count` and writes them together. Before
this story `extract_node` also wrote `page_count` and `embed_node` re-asserted
`status='ready'`, so one row had three writers with no ordering between them.

Scope note: this guard covers `books` ONLY. The `chapters` upsert in `chunk_node`
is still load-bearing (`chunks.chapter_id` is NOT NULL and nothing else supplies
a `chapter_id` until Phase 5), so including `chapters` here would produce a guard
that fails on day one — which is a guard that gets commented out on day two.
Extend to `chapters` in Phase 5, when the writer can actually go.

Method note: the scan runs over the EXECUTABLE source, not the raw file text.
Each module is parsed with `ast`, its docstrings are stripped, and it is round-
tripped through `ast.unparse` (which drops comments). A plain substring scan
matches the prose explaining what the code avoids — including this very
docstring — which is exactly how the equivalent guard in Story 1-10 first failed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PIPELINE_DIR = Path(__file__).resolve().parents[2] / "app" / "modules" / "content" / "pipeline"

# Supabase-py table selectors and the methods that mutate the selected table.
_TABLE_SELECTORS = frozenset({"table", "from_"})
_WRITE_METHODS = frozenset({"insert", "update", "upsert", "delete"})

# Story 1-11 scoped this to `books` alone, because the pipeline still had to write
# `chapters` — chunk_node manufactured a chapter row and `chunks.chapter_id` is NOT NULL.
# Story 1-13 (AC4) deleted that writer once a real chapter_id reached PipelineState, so the
# guard now covers both. `book_ingest_job` is the sole writer of either table.
FORBIDDEN_TABLES = frozenset({"books", "chapters"})


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
            # Keep the body non-empty — an empty body is not unparseable-safe.
            node.body = body[1:] or [ast.Pass()]
    return tree


def _selected_table(node: ast.expr) -> str | None:
    """Return the table name if *node* is (or chains back to) `.table("name")`."""
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


def _books_writes(source: str) -> list[str]:
    """Return `table("books"|"chapters").<write>()` call descriptions found in *source*."""
    tree = ast.parse(source)
    # Round-trip through unparse so only executable code survives (no comments).
    executable = ast.unparse(_strip_docstrings(tree))
    findings: list[str] = []
    for node in ast.walk(ast.parse(executable)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in _WRITE_METHODS:
            continue
        if _selected_table(func.value) in FORBIDDEN_TABLES:
            findings.append(f"{ast.unparse(func)}(...)")
    return findings


def _pipeline_modules() -> list[Path]:
    return sorted(p for p in PIPELINE_DIR.rglob("*.py") if p.is_file())


@pytest.mark.unit
def test_pipeline_dir_is_where_we_think_it_is() -> None:
    """Premise: a guard pointed at an empty directory passes forever."""
    assert PIPELINE_DIR.is_dir(), f"pipeline dir not found at {PIPELINE_DIR}"
    modules = _pipeline_modules()
    assert len(modules) >= 5, f"expected the pipeline package, found {len(modules)} modules"
    assert any(p.name == "graph.py" for p in modules)


@pytest.mark.unit
def test_scanner_detects_a_forbidden_write() -> None:
    """Premise: the detector fires on the exact statement it is meant to catch.

    Without this, a scanner that silently matches nothing looks identical to a
    clean codebase.
    """
    positive = 'supabase.table("books").update({"page_count": 3}).eq("book_id", b).execute()\n'
    assert _books_writes(positive), "scanner failed to flag a real books write"

    # Story 1-13 AC8 widened the guard: a chapters write is forbidden too, so the
    # scanner MUST fire on it now. Until Story 1-13 this asserted the opposite,
    # because chunk_node still had to manufacture a chapter row.
    assert _books_writes('supabase.table("chapters").upsert(payload).execute()\n'), (
        "scanner failed to flag a chapters write"
    )

    # ...and does not fire on a READ of either table.
    assert not _books_writes('supabase.table("books").select("book_id").execute()\n')
    assert not _books_writes('supabase.table("chapters").select("chapter_id").execute()\n')

    # ...and does not fire on prose, which is the Story 1-10 failure mode.
    prose = '"""Never call supabase.table(\\"books\\").update(...) from here."""\n'
    assert not _books_writes(prose), "scanner matched a docstring"


@pytest.mark.unit
def test_no_pipeline_module_writes_to_books_or_chapters() -> None:
    """AC8: nothing under `pipeline/` may insert/update/upsert/delete `books`."""
    offenders: dict[str, list[str]] = {}
    for path in _pipeline_modules():
        found = _books_writes(path.read_text(encoding="utf-8"))
        if found:
            offenders[str(path.relative_to(PIPELINE_DIR))] = found

    assert not offenders, (
        "The content pipeline must never write to `books` — `book_ingest_job` is "
        f"the single writer (Story 1-11 AC7/AC8). Found: {offenders}"
    )
