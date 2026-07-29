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


def _supabase() -> MagicMock:
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value
    payload = {"node_outputs": {}}
    chain.single.return_value.execute.return_value.data = payload
    chain.maybe_single.return_value.execute.return_value.data = payload
    return sb


async def _run(raw_text: str, font_blocks: list[dict[str, Any]]) -> tuple[Any, MagicMock]:
    """Run structure_node with a provider spy. Returns (result, provider_spy)."""
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
        result = await structure_node(state)  # type: ignore[arg-type]

    return result, provider


# ── AC-1: no LLM call, on BOTH sides of the old ~6,667-char threshold ─────────


async def test_structure_node_makes_no_llm_call_on_a_long_document() -> None:
    """The real-document case: the old code called the LLM and always discarded it."""
    result, provider = await _run(RAW, FONT_BLOCKS)

    assert len(RAW) > 6667, "fixture must exceed the old acceptance threshold to be meaningful"
    provider.complete_structured.assert_not_awaited()
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

    _, provider = await _run(
        short, [{"text": "Chapter 1: Cells", "font": {"size": 18.0, "bold": True}}]
    )

    provider.complete_structured.assert_not_awaited()


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

    result, _ = await _run(RAW, FONT_BLOCKS)
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
    result, provider = await _run("", [])

    provider.complete_structured.assert_not_awaited()
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
