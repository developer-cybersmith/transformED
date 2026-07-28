"""Story 2-28 AC-2/AC-4: LangGraph nodes must return ONLY the keys they own.

Why this test exists
--------------------
`PipelineState` declares six Phase-1 channels as concatenating reducers
(`Annotated[list[...], operator.add]`). LangGraph *merges* a node's returned
dict into state, and for a reducer channel "merge" means **append**. So a node
returning `{**state, ...}` re-appends everything already accumulated in those
channels — doubling them.

Four nodes run after the Phase-1 fan-in (`lesson_planner`, `slide_generator`,
`tts_node`, `image_generator`). With all four spreading state that is
2**4 = 16x duplication **in a single clean run**, no ARQ retry involved.
Observed in production 2026-07-27: 48 quiz questions for a segment that should
have had 3.

The AST scan below is the standing guard. It walks the whole pipeline package
rather than being pinned to `graph.py`, because `pipeline/nodes/` already
exists and CLAUDE.md mandates future node extraction into it — a
filename-pinned guard would silently stop guarding the day a node moves.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_PIPELINE_DIR = Path(__file__).resolve().parents[2] / "app" / "modules" / "content" / "pipeline"


def _returns_spreading_state(tree: ast.AST) -> list[tuple[str, int]]:
    """Return [(function_name, lineno)] for every `return {**state, ...}`.

    A dict literal with a `None` key is Python's AST representation of `**x`
    unpacking, so `{**state, "a": 1}` has keys `[None, Constant('a')]`.
    """
    offenders: list[tuple[str, int]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Return) or not isinstance(sub.value, ast.Dict):
                continue
            for key, value in zip(sub.value.keys, sub.value.values, strict=True):
                # key is None => `**something` unpacking
                if key is None and isinstance(value, ast.Name) and value.id == "state":
                    offenders.append((node.name, sub.lineno))
    return offenders


@pytest.mark.unit
def test_no_pipeline_node_returns_spread_of_state() -> None:
    """AC-2: no function in the pipeline package returns `{**state, ...}`."""
    assert _PIPELINE_DIR.is_dir(), f"pipeline dir not found: {_PIPELINE_DIR}"

    all_offenders: list[str] = []
    scanned = 0
    for py_file in sorted(_PIPELINE_DIR.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        scanned += 1
        # utf-8-sig: graph.py carries a UTF-8 BOM. Python's own import machinery
        # strips it, but ast.parse() on an already-decoded str sees a literal
        # U+FEFF and raises SyntaxError. Same convention as test_lesson_schema.py.
        tree = ast.parse(py_file.read_text(encoding="utf-8-sig"), filename=str(py_file))
        for func_name, lineno in _returns_spreading_state(tree):
            rel = py_file.relative_to(_PIPELINE_DIR.parents[3])
            all_offenders.append(f"{rel}:{lineno} in {func_name}()")

    assert scanned > 0, "guard scanned no files — path is wrong, test is vacuous"
    assert not all_offenders, (
        "LangGraph nodes must return ONLY the keys they own. A `return "
        "{**state, ...}` re-appends every operator.add channel (Story 2-28).\n"
        + "\n".join(f"  - {o}" for o in all_offenders)
    )


@pytest.mark.unit
def test_guard_detects_a_planted_violation() -> None:
    """The guard must actually fire — a scan that can never fail is worthless."""
    planted = ast.parse(
        "async def bad_node(state):\n"
        "    return {**state, 'quiz_questions': []}\n"
        "async def good_node(state):\n"
        "    return {'quiz_questions': []}\n"
    )
    offenders = _returns_spreading_state(planted)
    assert [name for name, _ in offenders] == ["bad_node"]


# ── AC-4: per-node return-key assertions ──────────────────────────────────────


def _fake_supabase() -> MagicMock:
    """Supabase double whose node_outputs read always misses (forces the real path)."""
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value
    chain.single.return_value.execute.return_value.data = {"node_outputs": {}}
    chain.maybe_single.return_value.execute.return_value.data = {"node_outputs": {}}
    return sb


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tts_node_returns_only_its_own_keys() -> None:
    """AC-4: tts_node owns audio_assets + progress_pct and nothing else.

    If this ever grows `quiz_questions`/`segment_summaries`/etc., a `**state`
    spread has been reintroduced and the 16x duplication is back.
    """
    from app.modules.content.pipeline import graph as g

    state: dict[str, Any] = {
        "lesson_id": "11111111-1111-1111-1111-111111111111",
        "narration_scripts": [],
        # Planted accumulator values: if the node spreads state, these come back
        # out and get re-appended by the reducer.
        "quiz_questions": [{"segment_id": "s1", "data": {"question_id": "q1"}}],
        "segment_summaries": [{"segment_id": "s1", "summary": "x"}],
        "glossary": [{"term": "t", "definition": "d"}],
    }

    with (
        patch("app.core.db.get_supabase", return_value=_fake_supabase()),
        patch("app.core.redis.get_redis", return_value=MagicMock()),
        patch.object(g, "_update_job_progress", new=AsyncMock(return_value=None)),
    ):
        result = await g.tts_node(state)  # type: ignore[arg-type]

    assert set(result) == {"audio_assets", "progress_pct"}, (
        f"tts_node returned {sorted(result)} — expected exactly "
        "{'audio_assets', 'progress_pct'}. Extra reducer keys mean state is "
        "being spread back out (Story 2-28)."
    )
