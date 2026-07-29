"""Story 2-34: `structure_node` makes no LLM call.

Why this file exists
--------------------
The node showed the LLM only `raw_text[:6000]` but accepted its output only when
that output covered >= 90% of the WHOLE document. The LLM can only describe what
it was shown, so the guard passed only for `len(raw_text) <= ~6,667` characters.
A textbook chapter is 30,000-100,000. On every real document we paid for the call
and always discarded the result.

This was already known — `graph.py` carried a "KNOWN LIMITATION (Story 2-16 RC-2,
deferred to Story 2-17)" comment saying exactly this. Story 2-34 is the decision
to act on it rather than the discovery of it.

Removing the call does NOT improve structure detection. Headings are still found
by font-size + boldness thresholds and a regex. That limitation is recorded in
the node and in the tracker, with the Sprint 3 docling direction.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_BASELINE = Path(__file__).resolve().parents[1] / "fixtures" / "structure_rule_based_baseline.json"

# Same input used to capture the baseline on the pre-deletion code.
RAW = "\n\n".join(
    [
        "Chapter 1: Cell Structure",
        "The cell is the basic unit of life. " * 40,
        "1.1 The Cell Membrane",
        "The membrane regulates what enters and leaves the cell. " * 40,
        "1.2 The Nucleus",
        "The nucleus contains the genetic material of the cell. " * 40,
        "Chapter 2: Cell Division",
        "Cells divide to produce new cells. " * 40,
        "2.1 Mitosis",
        "Mitosis produces two identical daughter cells. " * 40,
    ]
)

FONT_BLOCKS = [
    {"text": "Chapter 1: Cell Structure", "font": {"size": 18.0, "bold": True}},
    {"text": "1.1 The Cell Membrane", "font": {"size": 14.0, "bold": True}},
    {"text": "1.2 The Nucleus", "font": {"size": 14.0, "bold": True}},
    {"text": "Chapter 2: Cell Division", "font": {"size": 18.0, "bold": True}},
    {"text": "2.1 Mitosis", "font": {"size": 14.0, "bold": True}},
]


# ── D14: the golden test must not depend on the environment ──────────────────
#
# `structure_max_sections` (default 15) and `structure_min_section_chars`
# (default 200) both reshape the output. With STRUCTURE_MAX_SECTIONS=3 in the
# environment, the baseline comparison goes red with the message "detection
# itself moved" — which is a MISDIAGNOSIS: nothing moved, the cap merged
# sections. The neighbouring structure tests already pin these; this one didn't.

_PINNED_STRUCTURE_SETTINGS = {
    "structure_max_sections": 15,
    "structure_min_section_chars": 200,
}


@contextlib.contextmanager
def _temporarily_set(obj: Any, values: dict[str, Any]) -> Any:  # noqa: ANN401
    """Set attributes on the cached settings object and restore them after."""
    previous = {k: getattr(obj, k) for k in values}
    for k, v in values.items():
        object.__setattr__(obj, k, v)
    try:
        yield obj
    finally:
        for k, v in previous.items():
            object.__setattr__(obj, k, v)


def _supabase() -> MagicMock:
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value
    payload = {"node_outputs": {}}
    chain.single.return_value.execute.return_value.data = payload
    chain.maybe_single.return_value.execute.return_value.data = payload
    return sb


async def _run(
    raw_text: str,
    font_blocks: list[dict[str, Any]],
    *,
    settings_overrides: dict[str, Any] | None = None,
) -> tuple[Any, MagicMock, MagicMock]:
    """Run structure_node with a spy. Returns (result, provider_spy, factory_spy).

    **Review round 2, D12.** This used to return only the provider spy, and every
    "no LLM call" assertion was `provider.complete_structured.assert_not_awaited()`.
    That watches ONE method. A regression that called `provider.complete()` — or
    any other method on the same provider — passed all six tests.

    The factory spy is strictly stronger: if `get_llm_provider` is never called,
    no method on any provider can be. Every node in `graph.py` imports the
    factory lazily *inside* the function (`from app.providers.llm.factory import
    get_llm_provider`), so patching the factory module does intercept it.
    """
    from app.modules.content.pipeline.graph import structure_node

    provider = MagicMock()
    provider.complete_structured = AsyncMock(return_value=MagicMock(sections=[]))
    factory = MagicMock(return_value=provider)

    state = {
        "lesson_id": "11111111-2222-3333-4444-555555555555",
        "raw_text": raw_text,
        "font_blocks": font_blocks,
        "page_count": 12,
    }

    with (
        patch("app.core.db.get_supabase", return_value=_supabase()),
        patch("app.providers.llm.factory.get_llm_provider", new=factory),
        patch(
            "app.modules.content.pipeline.graph._update_job_progress",
            new=AsyncMock(return_value=None),
        ),
    ):
        if settings_overrides:
            from app.config import get_settings

            settings = get_settings()
            with _temporarily_set(settings, settings_overrides):
                result = await structure_node(state)  # type: ignore[arg-type]
        else:
            result = await structure_node(state)  # type: ignore[arg-type]

    return result, provider, factory


# ── AC-1: no LLM call, on BOTH sides of the old ~6,667-char threshold ─────────


async def test_structure_node_makes_no_llm_call_on_a_long_document() -> None:
    """The real-document case: the old code called the LLM and always discarded it."""
    result, provider, factory = await _run(RAW, FONT_BLOCKS)

    assert len(RAW) > 6667, "fixture must exceed the old acceptance threshold to be meaningful"
    provider.complete_structured.assert_not_awaited()
    factory.assert_not_called()  # D12: no provider is even OBTAINED
    assert result.get("sections"), "rule-based detection must still produce sections"


async def test_structure_node_makes_no_llm_call_on_a_short_document() -> None:
    """The short case matters MORE than the long one for this AC.

    Under the old code a document below ~6,667 chars was the ONLY input whose LLM
    output could actually be adopted. It is therefore exactly where a partial
    deletion would hide — remove the call from the long path only and every
    real-document test still passes.
    """
    short = "Chapter 1: Cells\n\nThe cell is the basic unit of life. " * 8
    assert len(short) < 6667, "fixture must sit BELOW the old threshold"

    _, provider, factory = await _run(
        short, [{"text": "Chapter 1: Cells", "font": {"size": 18.0, "bold": True}}]
    )

    provider.complete_structured.assert_not_awaited()
    factory.assert_not_called()  # D12: no provider is even OBTAINED


# ── AC-2: rule-based output is byte-identical to the pre-deletion baseline ────


async def test_sections_are_identical_to_the_pre_deletion_baseline() -> None:
    """Captured from the CURRENT code before the LLM block was removed, with the
    LLM mocked to return output the 90% guard rejects — i.e. exactly what every
    real document produced in production.

    A 'still returns sections' shape check would pass even if detection changed.
    This is a direct comparison, which is the only version that can fail for the
    right reason.
    """
    assert _BASELINE.exists(), (
        f"baseline fixture missing at {_BASELINE} — it must be captured on the "
        "pre-deletion code, or this assertion proves nothing"
    )
    expected = json.loads(_BASELINE.read_text(encoding="utf-8"))

    result, _provider, _factory = await _run(
        RAW, FONT_BLOCKS, settings_overrides=_PINNED_STRUCTURE_SETTINGS
    )
    actual = result.get("sections", [])

    assert actual == expected, (
        "rule-based sections changed. Removing an inert call must be behaviour-"
        "preserving; a difference here means detection itself moved."
    )


# ── AC-4: empty input still behaves ──────────────────────────────────────────


async def test_empty_raw_text_does_not_crash() -> None:
    """The old code special-cased empty raw_text because the `< 90%` proxy is
    vacuously false for an empty string, so hallucinated LLM sections would have
    been adopted. With no LLM there is nothing to hallucinate — but the node must
    still degrade rather than raise."""
    result, provider, factory = await _run("", [])

    provider.complete_structured.assert_not_awaited()
    factory.assert_not_called()  # D12: no provider is even OBTAINED
    assert isinstance(result.get("sections", []), list)


# ── AC-3: no orphaned prompt scaffolding left behind ─────────────────────────


async def test_no_orphaned_structure_prompt_scaffolding() -> None:
    """Dead prompt builders invite someone to 'reconnect' them later, which would
    silently restore a call that can never be adopted."""
    from app.modules.content.pipeline import graph

    for name in ("_STRUCTURE_SYSTEM_PROMPT", "_build_structure_prompt"):
        assert not hasattr(graph, name), (
            f"{name} is orphaned after Story 2-34 — remove it, or document why it stays"
        )


async def test_document_structure_schema_is_deliberately_retained() -> None:
    """`DocumentStructure` is NOT orphaned: it lives in `app.schemas`, is exported
    in `__all__`, and is referenced by three test modules. AC-3 allows keeping a
    symbol with a stated reason — this test is that reason, made executable, so a
    future cleanup does not delete it on the assumption it was structure_node's."""
    from app import schemas

    assert hasattr(schemas, "DocumentStructure")
    assert "DocumentStructure" in schemas.__all__


# ═══════════════════════════════════════════════════════════════════════════
# Review round 2 (2026-07-29) — D13: the `chapter` branch was never exercised
# ═══════════════════════════════════════════════════════════════════════════
#
# With FONT_BLOCKS above, `detect_headings` computes median=14.0, threshold=17.5,
# and the chapter band starts at threshold*1.15 = 20.125. The largest block is
# 18.0pt. **No input in this file ever reached the `chapter` branch**, so the
# golden baseline pinned a hierarchy in which every level came from somewhere
# else — and the branch itself was free to be deleted or inverted without a
# single test noticing.
#
# These sizes were derived, not guessed: median=12.0 -> threshold=15.00,
# chapter >= 17.25, section >= 15.75. 24.0/17.0/15.2 lands one heading cleanly
# in each of the three bands.

_THREE_LEVEL_FONT_BLOCKS = [
    {"text": "Chapter 1: Cell Structure", "font": {"size": 24.0, "bold": True}},
    {"text": "1.1 The Cell Membrane", "font": {"size": 17.0, "bold": True}},
    {"text": "1.2 The Nucleus", "font": {"size": 15.2, "bold": True}},
    {"text": "The cell is the basic unit", "font": {"size": 12.0, "bold": False}},
    {"text": "The membrane regulates", "font": {"size": 12.0, "bold": False}},
    {"text": "The nucleus contains", "font": {"size": 12.0, "bold": False}},
    {"text": "Cells divide to produce", "font": {"size": 12.0, "bold": False}},
    {"text": "Mitosis produces two", "font": {"size": 12.0, "bold": False}},
]


async def test_all_three_heading_levels_are_reachable_from_font_metadata() -> None:
    """D13. `detect_headings` has three level branches; the fixtures above reach
    exactly one of them, so two were unpinned dead code as far as the suite knew.

    Asserted on `detect_headings` directly rather than through `structure_node`,
    because `coalesce_sections` and `structure_max_sections` can merge sections
    away and would make a failure here ambiguous.
    """
    from app.modules.content.pipeline.nodes.structure_detection import detect_headings

    raw = "\n\n".join(b["text"] for b in _THREE_LEVEL_FONT_BLOCKS)
    candidates = detect_headings(raw, _THREE_LEVEL_FONT_BLOCKS)
    by_text = {c["text"]: c["level"] for c in candidates}

    assert by_text.get("Chapter 1: Cell Structure") == "chapter", (
        f"the chapter branch is still unreachable — got {by_text}"
    )
    assert by_text.get("1.1 The Cell Membrane") == "section"
    assert by_text.get("1.2 The Nucleus") == "topic"

    assert {"chapter", "section", "topic"} <= set(by_text.values()), (
        "all three level branches must be exercised by at least one fixture"
    )


async def test_font_strategy_wins_over_the_chapter_regex_inverting_the_hierarchy() -> None:
    """D28 — a REAL defect, pinned here as current behaviour, NOT fixed.

    `detect_headings` populates `candidates` keyed by text and every writer is
    guarded by `if text not in candidates`, so **the font strategy always wins**
    over the regex strategies that run after it. An explicit "Chapter N:" prefix
    is a far stronger signal than a relative font-size band, and it loses.

    The consequence is visible in `structure_rule_based_baseline.json`:

        topic    Chapter 1: Cell Structure     <- the chapter
        section  1.1 The Cell Membrane         <- ranked ABOVE its own chapter
        section  1.2 The Nucleus

    `_LEVEL_RANK = {"chapter": 0, "section": 1, "topic": 2}`, so a chapter sits
    BELOW its own subsections.

    **Deliberately not fixed in Story 2-34.** That story's premise is that
    removing an inert LLM call must be behaviour-PRESERVING, and its golden
    baseline asserts exactly that. Changing precedence here is a detection
    behaviour change and belongs with the Sprint 3 docling migration, per the
    2026-07-29 decision to park structure detection. Registered as D28 with that
    trigger; this test pins the wrong behaviour so the fix cannot land silently.
    """
    from app.modules.content.pipeline.nodes.structure_detection import detect_headings

    candidates = detect_headings(RAW, FONT_BLOCKS)
    by_text = {c["text"]: c["level"] for c in candidates}

    assert by_text.get("Chapter 1: Cell Structure") == "topic", (
        "If this now reads 'chapter', D28 has been fixed — good. Update this test, "
        "re-capture structure_rule_based_baseline.json, and close D28 in the register."
    )
    assert by_text.get("1.1 The Cell Membrane") == "section"
