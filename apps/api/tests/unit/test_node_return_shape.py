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

D63 (2026-08-11): widened to also scan `tutor/state_machine` — that graph's 7 nodes all
returned `{**state, ...}` too, found harmless only because `TutorMachineState` declares no
`operator.add` channel (unlike `PipelineState`). Harmless today is not guarded; CLAUDE.md bans
the pattern repo-wide, "applies to every StateGraph in the repo, not just the content pipeline."
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_APP_DIR = Path(__file__).resolve().parents[2] / "app"
_PIPELINE_DIR = _APP_DIR / "modules" / "content" / "pipeline"
_TUTOR_GRAPH_DIR = _APP_DIR / "modules" / "tutor" / "state_machine"
_SCAN_DIRS = (_PIPELINE_DIR, _TUTOR_GRAPH_DIR)


def _returns_spreading_state(tree: ast.AST) -> list[tuple[str, int]]:
    """Return [(function_name, lineno)] for every return that re-emits state.

    A dict literal with a `None` key is Python's AST representation of `**x`
    unpacking, so `{**state, "a": 1}` has keys `[None, Constant('a')]`.

    Deliberately broader than the literal `{**state, ...}` spelling, because the
    Story 2-28 review demonstrated five equivalent evasions of the narrow form:

      state["slides"] = []; return state     # reproduces 16x exactly
      return dict(state, slides=[])
      s = state; return {**s, ...}           # a node moved to pipeline/nodes/
                                             # may well rename its parameter
      out = {**state}; out["x"] = 1; return out
      return {**state.copy(), ...}

    Strategy: track names bound to the state parameter (direct aliases and
    dict-spread copies), then flag any return of `**<tracked name>`, a bare
    `return <tracked name>`, or `dict(<tracked name>, ...)`.
    """
    offenders: list[tuple[str, int]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue

        params = {a.arg for a in node.args.args} | {a.arg for a in node.args.kwonlyargs}
        if "state" not in params:
            continue

        # Names that alias, copy, or spread the state parameter.
        tainted: set[str] = {"state"}
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Assign) or len(sub.targets) != 1:
                continue
            target = sub.targets[0]
            if not isinstance(target, ast.Name):
                continue
            val = sub.value
            # s = state   /   out = state.copy()   /   out = dict(state)
            if isinstance(val, ast.Name) and val.id in tainted:
                tainted.add(target.id)
            elif (
                isinstance(val, ast.Call)
                and isinstance(val.func, ast.Attribute)
                and val.func.attr == "copy"
                and isinstance(val.func.value, ast.Name)
                and val.func.value.id in tainted
            ):
                tainted.add(target.id)
            elif isinstance(val, ast.Dict) and _spreads_any(val, tainted):
                tainted.add(target.id)
            elif (
                isinstance(val, ast.Call)
                and isinstance(val.func, ast.Name)
                and val.func.id == "dict"
                and any(isinstance(a, ast.Name) and a.id in tainted for a in val.args)
            ):
                tainted.add(target.id)

        for sub in ast.walk(node):
            if not isinstance(sub, ast.Return) or sub.value is None:
                continue
            val = sub.value
            if isinstance(val, ast.Dict) and _spreads_any(val, tainted):
                offenders.append((node.name, sub.lineno))
            elif isinstance(val, ast.Name) and val.id in tainted:
                offenders.append((node.name, sub.lineno))
            elif (
                isinstance(val, ast.Call)
                and isinstance(val.func, ast.Name)
                and val.func.id == "dict"
                and any(isinstance(a, ast.Name) and a.id in tainted for a in val.args)
            ):
                offenders.append((node.name, sub.lineno))
    return offenders


def _spreads_any(node: ast.Dict, names: set[str]) -> bool:
    """True if the dict literal `**`-unpacks any of *names* (or `x.copy()`)."""
    for key, value in zip(node.keys, node.values, strict=True):
        if key is not None:  # not a `**` unpacking
            continue
        if isinstance(value, ast.Name) and value.id in names:
            return True
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == "copy"
            and isinstance(value.func.value, ast.Name)
            and value.func.value.id in names
        ):
            return True
    return False


@pytest.mark.unit
def test_no_pipeline_node_returns_spread_of_state() -> None:
    """AC-2 (Story 2-28) / AC-6+7 (Story 4-24, D63): no function in EITHER scanned StateGraph
    package returns `{**state, ...}` — the content pipeline AND the tutor state machine.

    CLAUDE.md: "Applies to every StateGraph in the repo, not just the content pipeline."
    """
    all_offenders: list[str] = []
    scanned = 0
    per_dir_scanned: dict[Path, int] = dict.fromkeys(_SCAN_DIRS, 0)

    for scan_dir in _SCAN_DIRS:
        assert scan_dir.is_dir(), f"scan dir not found: {scan_dir}"
        for py_file in sorted(scan_dir.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            scanned += 1
            per_dir_scanned[scan_dir] += 1
            # utf-8-sig: graph.py carries a UTF-8 BOM. Python's own import machinery
            # strips it, but ast.parse() on an already-decoded str sees a literal
            # U+FEFF and raises SyntaxError. Same convention as test_lesson_schema.py.
            tree = ast.parse(py_file.read_text(encoding="utf-8-sig"), filename=str(py_file))
            for func_name, lineno in _returns_spreading_state(tree):
                rel = py_file.relative_to(_APP_DIR.parent)
                all_offenders.append(f"{rel}:{lineno} in {func_name}()")

    assert scanned > 0, "guard scanned no files — path is wrong, test is vacuous"
    for scan_dir, count in per_dir_scanned.items():
        assert count > 0, f"guard scanned 0 files in {scan_dir} — widened path is wrong"
    assert not all_offenders, (
        "LangGraph nodes must return ONLY the keys they own. A `return "
        "{**state, ...}` re-appends every operator.add channel (Story 2-28) and is banned "
        "repo-wide regardless of whether the channel is currently a reducer (D63).\n"
        + "\n".join(f"  - {o}" for o in all_offenders)
    )


@pytest.mark.unit
def test_guard_scans_the_tutor_state_machine_directory_for_real() -> None:
    """AC-7 (D63): the widened scan must actually walk `tutor/state_machine`'s files, not
    merely have the path configured. Proves the widen isn't vacuous."""
    py_files = [f for f in sorted(_TUTOR_GRAPH_DIR.rglob("*.py")) if "__pycache__" not in f.parts]
    assert py_files, f"no .py files found under {_TUTOR_GRAPH_DIR} — guard would scan nothing"
    assert any(f.name == "graph.py" for f in py_files), (
        "graph.py (the file with the 7 FSM nodes) is not in the widened scan set"
    )


@pytest.mark.unit
def test_scan_dirs_actually_includes_the_tutor_graph_dir() -> None:
    """Review finding (2026-08-11, PR #129 six-layer review, Test Coverage layer): the previous
    two tests above only prove files exist under `_TUTOR_GRAPH_DIR` and derive their per-dir
    counts FROM `_SCAN_DIRS` itself — neither can detect `_SCAN_DIRS` being reverted to
    `(_PIPELINE_DIR,)` only, which is EXACTLY the D63 regression this file exists to guard
    against. This is the one assertion that actually pins the tuple's membership."""
    assert _TUTOR_GRAPH_DIR in _SCAN_DIRS, (
        "_TUTOR_GRAPH_DIR must be a member of _SCAN_DIRS — if it isn't, the guard has silently "
        "reverted to scanning only the content pipeline, and every other test in this file would "
        "still pass because they all derive their expectations from _SCAN_DIRS rather than an "
        "independent source of truth."
    )
    assert _PIPELINE_DIR in _SCAN_DIRS, "the original Story 2-28 guard must not be dropped either"


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


@pytest.mark.unit
@pytest.mark.parametrize(
    ("label", "body"),
    [
        ("mutate_then_return_state", "    state['quiz_questions'] = []\n    return state\n"),
        ("dict_constructor", "    return dict(state, quiz_questions=[])\n"),
        ("aliased_param", "    s = state\n    return {**s, 'quiz_questions': []}\n"),
        ("assign_then_return", "    out = {**state}\n    out['q'] = 1\n    return out\n"),
        ("copy_spread", "    return {**state.copy(), 'quiz_questions': []}\n"),
    ],
)
def test_guard_catches_equivalent_evasions(label: str, body: str) -> None:
    """Story 2-28 review: the original matcher only caught the literal
    `{**state, ...}` spelling. Each of these reproduces the same 16x
    duplication while evading that narrow form — a node moved into
    `pipeline/nodes/` is exactly the case most likely to rename its parameter.
    """
    planted = ast.parse(f"async def bad_node(state):\n{body}")
    offenders = _returns_spreading_state(planted)
    assert offenders, f"guard failed to catch evasion: {label}"


@pytest.mark.unit
def test_guard_does_not_flag_legitimate_returns() -> None:
    """False positives would make the guard get disabled — verify it stays quiet
    on the shapes the codebase legitimately uses."""
    ok = ast.parse(
        "async def good(state):\n"
        "    cached = state.get('x')\n"
        "    return {'quiz_questions': cached, 'progress_pct': 1.0}\n"
        "async def also_good(state):\n"
        "    out = {'a': 1}\n"
        "    return out\n"
        "def helper(entries):\n"
        "    return {**entries}\n"  # not a node: no `state` param
    )
    assert _returns_spreading_state(ok) == []


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
