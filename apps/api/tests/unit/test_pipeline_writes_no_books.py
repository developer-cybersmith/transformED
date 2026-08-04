"""Guard: `book_ingest_job` is the sole writer of `books` and `chapters`.

`book_ingest_job` (`app/workers/jobs/book_ingest.py`) is the single writer of the
`books` row — it owns `status` and `page_count` and writes them together. Before
Story 1-11 `extract_node` also wrote `page_count` and `embed_node` re-asserted
`status='ready'`, so one row had three writers with no ordering between them.

Scope, and why it is now two different scopes (Story 1-14, AC14):

* `books` + `chapters` are forbidden across `app/modules/content/pipeline/` —
  unchanged from Story 1-13. (Story 1-11 could only scope this to `books`,
  because `chunk_node` still manufactured a chapter row to satisfy the NOT NULL
  `chunks.chapter_id`; Story 1-13 AC4 deleted that writer once a real
  `chapter_id` reached `PipelineState`.)

* `chapters` is ADDITIONALLY forbidden across all of `app/modules/content/`,
  which now includes `router.py`. Phase 6's generate endpoint lives there, and
  the "obvious" implementation — insert the lesson, point `chapters.lesson_id`
  at it, roll the lesson back when the enqueue fails — is destructive, not
  merely wrong: that FK is ON DELETE CASCADE
  (`20260611000000_initial_schema.sql:132`, preserved by `20260803000000:52-58`)
  and `chunks.chapter_id` cascades from the chapter, so one failed generation
  deletes the chapter and every chunk and embedding under it. A Supabase mock
  has no FK engine and cannot show you this. `chapters.lesson_id` is dead and
  stays dead.

* `books` stays PIPELINE-scoped and is deliberately NOT widened to the module.
  `router.py`'s upload path legitimately inserts a `books` row (`:464`) and
  deletes it on two rollback paths (`:507`, `:525`) — widening `books` would
  make this guard fail on day one, which is how a guard gets commented out on
  day two.

* `lessons` is not forbidden anywhere. Phase 6's endpoint exists to write it.

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

CONTENT_DIR = Path(__file__).resolve().parents[2] / "app" / "modules" / "content"
PIPELINE_DIR = CONTENT_DIR / "pipeline"

# Supabase-py table selectors and the methods that mutate the selected table.
_TABLE_SELECTORS = frozenset({"table", "from_"})
_WRITE_METHODS = frozenset({"insert", "update", "upsert", "delete"})

# Forbidden inside `pipeline/` — unchanged behaviour from Story 1-13.
FORBIDDEN_TABLES = frozenset({"books", "chapters"})

# Forbidden across the WHOLE content module, `router.py` included (Story 1-14 AC14).
# `books` is absent here on purpose: see the module docstring.
MODULE_FORBIDDEN_TABLES = frozenset({"chapters"})


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


def _books_writes(source: str, forbidden: frozenset[str] = FORBIDDEN_TABLES) -> list[str]:
    """Return `table(<forbidden>).<write>()` call descriptions found in *source*."""
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
        if _selected_table(func.value) in forbidden:
            findings.append(f"{ast.unparse(func)}(...)")
    return findings


def _pipeline_modules() -> list[Path]:
    return sorted(p for p in PIPELINE_DIR.rglob("*.py") if p.is_file())


def _content_modules() -> list[Path]:
    return sorted(p for p in CONTENT_DIR.rglob("*.py") if p.is_file())


@pytest.mark.unit
def test_pipeline_dir_is_where_we_think_it_is() -> None:
    """Premise: a guard pointed at an empty directory passes forever."""
    assert PIPELINE_DIR.is_dir(), f"pipeline dir not found at {PIPELINE_DIR}"
    modules = _pipeline_modules()
    assert len(modules) >= 5, f"expected the pipeline package, found {len(modules)} modules"
    assert any(p.name == "graph.py" for p in modules)


@pytest.mark.unit
def test_content_dir_scan_actually_reaches_the_router() -> None:
    """Premise (Story 1-14 AC14): the whole point of widening the scan is that it
    now covers `router.py`, where Phase 6's generate endpoint lives. A widened
    scan that still only walked `pipeline/` would pass for the wrong reason."""
    assert CONTENT_DIR.is_dir(), f"content module not found at {CONTENT_DIR}"
    names = {p.relative_to(CONTENT_DIR).as_posix() for p in _content_modules()}
    assert "router.py" in names, "the widened scan must include the content router"
    assert "pipeline/graph.py" in names
    assert len(names) > len(_pipeline_modules()), "widened scan is no wider than the old one"


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
def test_scanner_honours_the_narrower_module_scope() -> None:
    """Positive control for the WIDER scan (Story 1-14 AC14).

    `MODULE_FORBIDDEN_TABLES` must fire on a `chapters` write and must NOT fire
    on a `books` write — otherwise the module-wide test below would flag
    `router.py`'s legitimate upload-path `books` insert/delete and get deleted.
    """
    chapters_write = 'supabase.table("chapters").update({"lesson_id": lid}).execute()\n'
    assert _books_writes(chapters_write, MODULE_FORBIDDEN_TABLES), (
        "module-scope scanner failed to flag a chapters write"
    )
    books_write = 'supabase.table("books").delete().eq("book_id", book_id).execute()\n'
    assert not _books_writes(books_write, MODULE_FORBIDDEN_TABLES), (
        "`books` must stay pipeline-scoped — router.py writes it legitimately"
    )
    # `lessons` writes are what Phase 6 exists to do; never forbidden.
    lessons_write = 'supabase.table("lessons").insert(payload).execute()\n'
    assert not _books_writes(lessons_write, MODULE_FORBIDDEN_TABLES)
    assert not _books_writes(lessons_write, FORBIDDEN_TABLES)


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


@pytest.mark.unit
def test_no_content_module_writes_to_chapters() -> None:
    """Story 1-14 AC14: `chapters.lesson_id` is dead and stays dead.

    Widened from `pipeline/` to the whole content module so it covers
    `router.py`. Writing that column is destructive, not merely wrong — the FK
    is ON DELETE CASCADE and `chunks.chapter_id` cascades from the chapter, so
    rolling back a lesson that a chapter points at destroys the chapter, its
    chunks and their embeddings. `book_ingest_job` remains the sole writer.
    """
    offenders: dict[str, list[str]] = {}
    for path in _content_modules():
        found = _books_writes(path.read_text(encoding="utf-8"), MODULE_FORBIDDEN_TABLES)
        if found:
            offenders[path.relative_to(CONTENT_DIR).as_posix()] = found

    assert not offenders, (
        "Nothing in `app/modules/content/` may write `chapters` — `book_ingest_job` "
        "is the sole writer, and `chapters.lesson_id` carries an ON DELETE CASCADE "
        f"that would destroy the chapter and its chunks. Found: {offenders}"
    )
