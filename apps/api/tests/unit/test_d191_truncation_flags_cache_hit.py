"""Guard: D191 — cache-hit paths must return *_truncated flags (Story 5-16).

lesson_planner_node and slide_generator_node both implement idempotency by
returning cached output when their key is already in lesson_jobs.node_outputs.
D191: neither path returned book_context_truncated / chapter_context_truncated /
onboarding_context_truncated — package_builder_node always wrote False even when
the original run had truncated the context.

This guard source-scans graph.py and confirms the cache-hit return blocks for
both nodes include all three *_truncated keys. Source-scan only — no DB, no
mocks, no imports of application code.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_GRAPH_FILE = (
    Path(__file__).resolve().parents[4]
    / "apps"
    / "api"
    / "app"
    / "modules"
    / "content"
    / "pipeline"
    / "graph.py"
)
_GRAPH_SRC: str = _GRAPH_FILE.read_text(encoding="utf-8")

_TRUNCATED_FLAGS = (
    "book_context_truncated",
    "chapter_context_truncated",
    "onboarding_context_truncated",
)


def _extract_cache_hit_block(node_key: str) -> str:
    """Return the text of the ``if "{node_key}" in node_outputs:`` block.

    Finds the first occurrence of the pattern, then captures lines until the
    block closes (detected by dedentation back to the ``if`` indent level).
    Returns the captured text, or empty string if the pattern is not found.
    """
    marker = f'if "{node_key}" in node_outputs:'
    start = _GRAPH_SRC.find(marker)
    if start == -1:
        return ""
    block_start = start
    # Find indent level of the if-line
    line_start = _GRAPH_SRC.rfind("\n", 0, start) + 1
    indent = start - line_start
    indent_str = " " * indent

    # Walk forward line by line until we hit an unindented (same or less) line
    # that is not blank and not the if-line itself.
    rest = _GRAPH_SRC[start:]
    lines = rest.split("\n")
    block_lines: list[str] = [lines[0]]
    for line in lines[1:]:
        stripped = line.lstrip()
        if stripped == "":
            block_lines.append(line)
            continue
        current_indent = len(line) - len(line.lstrip())
        if current_indent <= indent:
            break
        block_lines.append(line)

    return "\n".join(block_lines)


@pytest.mark.unit
def test_lesson_planner_cache_hit_returns_book_context_truncated() -> None:
    """D191/AC1: lesson_planner_node cache-hit block must set book_context_truncated."""
    block = _extract_cache_hit_block("lesson_planner")
    assert block, "lesson_planner cache-hit block not found in graph.py"
    assert "book_context_truncated" in block, (
        "lesson_planner_node cache-hit return is missing 'book_context_truncated'.\n"
        "D191 / Story 5-16 AC1."
    )


@pytest.mark.unit
def test_lesson_planner_cache_hit_returns_chapter_context_truncated() -> None:
    """D191/AC1: lesson_planner_node cache-hit block must set chapter_context_truncated."""
    block = _extract_cache_hit_block("lesson_planner")
    assert block, "lesson_planner cache-hit block not found in graph.py"
    assert "chapter_context_truncated" in block, (
        "lesson_planner_node cache-hit return is missing 'chapter_context_truncated'.\n"
        "D191 / Story 5-16 AC1."
    )


@pytest.mark.unit
def test_lesson_planner_cache_hit_returns_onboarding_context_truncated() -> None:
    """D191/AC1: lesson_planner_node cache-hit block must set onboarding_context_truncated."""
    block = _extract_cache_hit_block("lesson_planner")
    assert block, "lesson_planner cache-hit block not found in graph.py"
    assert "onboarding_context_truncated" in block, (
        "lesson_planner_node cache-hit return is missing 'onboarding_context_truncated'.\n"
        "D191 / Story 5-16 AC1."
    )


@pytest.mark.unit
def test_slide_generator_cache_hit_returns_book_context_truncated() -> None:
    """D191/AC2: slide_generator_node cache-hit block must set book_context_truncated."""
    block = _extract_cache_hit_block("slide_generator")
    assert block, "slide_generator cache-hit block not found in graph.py"
    assert "book_context_truncated" in block, (
        "slide_generator_node cache-hit return is missing 'book_context_truncated'.\n"
        "D191 / Story 5-16 AC2."
    )


@pytest.mark.unit
def test_slide_generator_cache_hit_returns_chapter_context_truncated() -> None:
    """D191/AC2: slide_generator_node cache-hit block must set chapter_context_truncated."""
    block = _extract_cache_hit_block("slide_generator")
    assert block, "slide_generator cache-hit block not found in graph.py"
    assert "chapter_context_truncated" in block, (
        "slide_generator_node cache-hit return is missing 'chapter_context_truncated'.\n"
        "D191 / Story 5-16 AC2."
    )


@pytest.mark.unit
def test_slide_generator_cache_hit_returns_onboarding_context_truncated() -> None:
    """D191/AC2: slide_generator_node cache-hit block must set onboarding_context_truncated."""
    block = _extract_cache_hit_block("slide_generator")
    assert block, "slide_generator cache-hit block not found in graph.py"
    assert "onboarding_context_truncated" in block, (
        "slide_generator_node cache-hit return is missing 'onboarding_context_truncated'.\n"
        "D191 / Story 5-16 AC2."
    )
