"""Guard: chapter_context wiring contract in the content-generation pipeline.

Why this file exists
--------------------
Story 249 (2026-09-25) wired ``chapter_context`` into ``slide_generator_node``
and ``narration_generator_node`` and added the ``chapter_context_truncated`` flag
to ``PipelineState``. Its full behavioural test suite
(``tests/test_249_context_wiring.py``) lives in the ``tests/`` root — the
**advisory** CI bucket (``continue-on-error: true``). CLAUDE.md is explicit: a
green checkmark on a PR does NOT mean the advisory bucket is clean.

The critical structural invariants were therefore ungated. A developer who
removes ``"chapter_context"`` from ``_FAN_OUT_STATE_KEYS``, or renames the
``merge_chapter_context`` import, would not see a CI gate failure — only an
advisory warning that is easy to miss in code review.

This file guards five specific structural invariants at import-level or via a
source-text pattern scan. It never runs the actual pipeline (no async node
execution, no mocking, no DB), so it belongs in ``tests/unit/``.

Registered gap: Story 5-14, 2026-09-28.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_type_hints

import pytest

# ---------------------------------------------------------------------------
# Source paths (resolved once at module import time)
# ---------------------------------------------------------------------------

_PIPELINE_DIR = Path(__file__).resolve().parents[2] / "app" / "modules" / "content" / "pipeline"
_GRAPH_SRC: str = (_PIPELINE_DIR / "graph.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# _FAN_OUT_STATE_KEYS membership — AC2, AC3
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fan_out_state_keys_includes_chapter_context() -> None:
    """'chapter_context' must be in _FAN_OUT_STATE_KEYS.

    narration_generator_node is Send()-dispatched after lesson_planner_node
    completes. Its only receive path for context values is _FAN_OUT_STATE_KEYS
    — if 'chapter_context' is absent, the node silently operates with no
    chapter context regardless of any other wiring in graph.py. Story 249 AC 7.
    """
    from app.modules.content.pipeline.graph import _FAN_OUT_STATE_KEYS  # noqa: PLC0415

    assert "chapter_context" in _FAN_OUT_STATE_KEYS, (
        "'chapter_context' is missing from _FAN_OUT_STATE_KEYS.\n"
        "narration_generator_node will NOT receive chapter context — the student's\n"
        "named doubt, skip-list, and depth preference will be silently ignored in\n"
        "narration. Re-add it following the book_context/onboarding_context pattern.\n"
        "Story 249 AC 7 / DEFECT-REGISTER.md D189."
    )


@pytest.mark.unit
def test_fan_out_state_keys_includes_chapter_context_truncated() -> None:
    """'chapter_context_truncated' must travel through the fan-out alongside
    'chapter_context' so that narration_generator_node can read it and apply the
    same Send()-safe suppression as book_context_truncated (Story 249 AC 8).

    Without this key, narration_generator_node always reads the flag as the
    TypedDict default (False) — so a chapter context that was actually truncated
    appears un-truncated to narration, defeating the explicit-degradation guarantee.
    """
    from app.modules.content.pipeline.graph import _FAN_OUT_STATE_KEYS  # noqa: PLC0415

    assert "chapter_context_truncated" in _FAN_OUT_STATE_KEYS, (
        "'chapter_context_truncated' is missing from _FAN_OUT_STATE_KEYS.\n"
        "narration_generator_node's truncation-warning suppression guard becomes\n"
        "dead code without this key (same failure class as D206 for book_context_truncated).\n"
        "Story 249 AC 8."
    )


# ---------------------------------------------------------------------------
# PipelineState field declarations — AC4
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pipeline_state_declares_chapter_context() -> None:
    """PipelineState must declare 'chapter_context: str', mirroring book_context.

    Uses typing.get_type_hints() rather than __annotations__ because the file
    uses 'from __future__ import annotations', which turns all annotations into
    string ForwardRefs that __annotations__ leaves unresolved. Story 249 AC 1.
    """
    from app.modules.content.pipeline.graph import PipelineState  # noqa: PLC0415

    hints = get_type_hints(PipelineState)
    assert "chapter_context" in hints, (
        "PipelineState is missing the 'chapter_context' field.\n"
        "This field is required for chapter_context to travel from\n"
        "lesson_planner_node through to slide_generator_node. Story 249 AC 1."
    )


@pytest.mark.unit
def test_pipeline_state_declares_chapter_context_truncated() -> None:
    """PipelineState must declare 'chapter_context_truncated: bool'.

    Without this field the explicit-degradation flag has no persistent home in
    the graph state, so lesson_planner_node, slide_generator_node, and
    package_builder_node cannot coordinate on it. Story 249 AC 1.
    """
    from app.modules.content.pipeline.graph import PipelineState  # noqa: PLC0415

    hints = get_type_hints(PipelineState)
    assert "chapter_context_truncated" in hints, (
        "PipelineState is missing the 'chapter_context_truncated' field.\n"
        "The explicit-degradation flag cannot be set or read across nodes.\n"
        "Story 249 AC 1."
    )


# ---------------------------------------------------------------------------
# merge_chapter_context callable — AC6
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_merge_chapter_context_is_importable_and_callable() -> None:
    """prompt_context.merge_chapter_context must exist and be callable.

    This function implements the explicit-degradation truncation contract for
    chapter_context (AC 3). If it is removed or renamed, every call site in
    graph.py will fail at import time. Story 249 AC 3.
    """
    from app.modules.content.pipeline.prompt_context import (  # noqa: PLC0415
        merge_chapter_context,
    )

    assert callable(merge_chapter_context), (
        "merge_chapter_context is not callable — Story 249 AC 3."
    )


# ---------------------------------------------------------------------------
# _CHAPTER_CONTEXT_MAX_CHARS constant value — AC5
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_chapter_context_max_chars_is_1300() -> None:
    """_CHAPTER_CONTEXT_MAX_CHARS must equal 1_300.

    This constant is derived from chapter_context's field set:
        2 free-text fields × 500 chars (Pydantic max_length, enforced at the
        API boundary) + MCQ/bool labels + '[Chapter Instructions]' header
        ≈ 1_219 chars worst case → rounded up to 1_300.

    Changing this constant without re-deriving the arithmetic is the
    inherited-cap trap that Scale Contract Q5 exists to name. If you need a
    different value, update:
      1. The derivation comment in prompt_context.py next to the constant.
      2. The Scale & Load section (Q5) of docs/stories/249-context-wiring.md.
      3. The Pydantic max_length validators in schemas.py that the derivation
         depends on (schemas.ChapterContextRequest.specific_doubt, .goal_and_skip).

    Story 249 AC 4.
    """
    from app.modules.content.pipeline.prompt_context import (  # noqa: PLC0415
        _CHAPTER_CONTEXT_MAX_CHARS,
    )

    assert _CHAPTER_CONTEXT_MAX_CHARS == 1_300, (
        f"_CHAPTER_CONTEXT_MAX_CHARS is {_CHAPTER_CONTEXT_MAX_CHARS}, expected 1_300.\n"
        "See the docstring of this test for the re-derivation steps required\n"
        "before changing this value. Story 249 AC 4."
    )


# ---------------------------------------------------------------------------
# graph.py call-site count — AC7
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_graph_calls_merge_chapter_context_at_least_twice() -> None:
    """graph.py must call merge_chapter_context() at least twice.

    The two mandatory call sites are:
      - lesson_planner_node  (Story 249 AC 5 — replaces raw '+ chapter_context')
      - slide_generator_node (Story 249 AC 6 — new call site)

    narration_generator_node is a third call site but its removal is already
    detected by the _FAN_OUT_STATE_KEYS guard above (the fan-out key is the
    structural invariant; the call inside the node is the consequence).

    Source-text scan rather than AST so that an accidental rename from
    merge_chapter_context to _merge_cc (or similar) is caught here without
    importing the full graph module.
    """
    calls = re.findall(r"\bmerge_chapter_context\s*\(", _GRAPH_SRC)
    assert len(calls) >= 2, (
        f"graph.py has only {len(calls)} call(s) to merge_chapter_context() —\n"
        "expected ≥ 2 (lesson_planner_node + slide_generator_node).\n"
        "Story 249 AC 5 + AC 6 / DEFECT-REGISTER.md D189."
    )
