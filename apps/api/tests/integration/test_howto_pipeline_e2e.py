"""
Story 2-24: REAL-graph end-to-end integration test on a step-numbered how-to.

The audit's #1 gap was that no test runs the actual graph — every test mocks node
boundaries with clean fixtures, and the boundaries are where the bug class lives.
This test drives `run_pipeline()` through the real compiled LangGraph on
step-numbered how-to text (the failure class), mocking ONLY external providers,
and asserts the produced LessonPackage is JSON-schema-valid and free of the whole
bug class (over-segmentation, unsafe/space/newline segment_ids, empty timestamps,
whole-segment drop). Would have caught Stories 2-16/2-18/2-19/2-20/2-21/2-22.

Reusable harness: `_StatefulSupabaseFake` + `_dispatching_provider`.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Force the submodule into sys.modules so patch("app.providers.llm.openai...")
# resolves (graph.py uses lazy in-function imports).
import app.providers.llm.openai  # noqa: E402,F401  # isort: skip

# ── Input: a step-numbered how-to (the exact document shape that broke prod) ──
# Each numbered step is detected as a heading by the rule-based detector; the
# body paragraph keeps sections above the coalesce min-floor so the ~20 steps
# exercise the MAX-count cap (bounding to structure_max_sections), not just the
# min-floor merge. One title contains an embedded newline (the "5.\nJobs" prod bug).
_BODY = (
    "Follow the on-screen instruction carefully and confirm the result before you "
    "continue to the next step. This paragraph gives the step enough body text to "
    "stay above the coalesce minimum-length floor so it is treated as a real section."
)
_STEPS = [
    "Start",
    "Open Task Manager",
    "Processes",
    "End\nProcess",
    "Confirm",
    "Details",
    "Performance",
    "Startup",
    "Services",
    "Users",
    "Restart",
    "Sign Out",
    "Refresh",
    "Sort",
    "Filter",
    "Search",
    "Export",
    "Import",
    "Settings",
    "Close",
]
HOWTO_TEXT = "\n\n".join(
    f"{i}. Click the {name} button\n{_BODY}" for i, name in enumerate(_STEPS, start=1)
)
FAKE_LESSON_ID = "aaaaaaaa-1111-2222-3333-444444444444"
FAKE_BOOK_ID = "bbbbbbbb-1111-2222-3333-444444444444"


# ── Stateful Supabase fake ────────────────────────────────────────────────────
class _Query:
    def __init__(self, fake: _StatefulSupabaseFake, table: str) -> None:
        self._fake = fake
        self._table = table
        self._op = "select"
        self._payload: Any = None

    def select(self, *a: Any, **k: Any) -> _Query:
        self._op = "select"
        return self

    def insert(self, payload: Any) -> _Query:
        self._op, self._payload = "insert", payload
        return self

    def upsert(self, payload: Any, **k: Any) -> _Query:
        self._op, self._payload = "upsert", payload
        return self

    def update(self, payload: Any) -> _Query:
        self._op, self._payload = "update", payload
        return self

    # chainable no-op filters
    def eq(self, *a: Any) -> _Query:
        return self

    def is_(self, *a: Any) -> _Query:
        return self

    def in_(self, *a: Any) -> _Query:
        return self

    def single(self) -> _Query:
        return self

    def maybe_single(self) -> _Query:
        return self

    def range(self, *a: Any) -> _Query:
        return self

    def order(self, *a: Any, **k: Any) -> _Query:
        return self

    def limit(self, *a: Any) -> _Query:
        return self

    def neq(self, *a: Any) -> _Query:
        return self

    def execute(self) -> SimpleNamespace:
        t, op = self._table, self._op
        if t == "lesson_jobs" and op == "select":
            return SimpleNamespace(data={"node_outputs": self._fake.node_outputs})
        if t == "lesson_jobs" and op == "update":
            if isinstance(self._payload, dict) and "node_outputs" in self._payload:
                self._fake.node_outputs = self._payload["node_outputs"]
            return SimpleNamespace(data=[{}])
        if t == "chapters" and op == "insert":
            return SimpleNamespace(data=[{"chapter_id": "cccccccc-1111-2222-3333-444444444444"}])
        # chunks: return [] so embed_node no-ops (chunks feed RAG, not generation)
        if t == "chunks":
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=[{}])


class _Storage:
    def from_(self, *a: Any) -> _Storage:
        return self

    def upload(self, *a: Any, **k: Any) -> SimpleNamespace:
        return SimpleNamespace(data={})


class _StatefulSupabaseFake:
    """Minimal stateful Supabase client: accumulates lesson_jobs.node_outputs
    across nodes; chapters.insert returns an id; chunks return [] (embed no-ops);
    lessons/books/storage no-op. The actual generated data flows via LangGraph
    state reducers, so node_outputs only needs to carry the chunk chapter_id +
    idempotency records."""

    def __init__(self) -> None:
        self.node_outputs: dict[str, Any] = {}
        self.storage = _Storage()

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    def rpc(self, *a: Any, **k: Any) -> SimpleNamespace:  # phase-1 atomic checkpoint RPC
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[{}]))


class _AsyncRedis:
    """get_redis() is SYNC and returns a client whose methods (expire/publish/
    sadd/...) are async — every attribute resolves to an awaitable no-op."""

    def __getattr__(self, name: str) -> Any:
        return AsyncMock(return_value=0)


# ── Dispatching LLM provider mock ─────────────────────────────────────────────
def _segment_ids_from_messages(messages: list[dict[str, str]]) -> list[str]:
    user = messages[1]["content"] if len(messages) > 1 else ""
    return [
        line.split("segment_id=")[1].split(":")[0].strip()
        for line in user.splitlines()
        if line.strip().startswith("- segment_id=")
    ]


def _make_dispatch() -> Any:
    from app.modules.content.pipeline.graph import (
        _JargonEntryLLM,
        _JargonListLLM,
        _LessonPlanLLM,
        _LessonPlanSegmentLLM,
        _NarrationScriptLLM,
        _QuizQuestionLLM,
        _SegmentComplexityLLM,
        _SegmentInterventionsLLM,
        _SegmentSlidesLLM,
        _SegmentSummaryLLM,
        _SlideDeckLLM,
        _SlideLLM,
    )
    from app.schemas import DocumentStructure, SectionBoundary

    async def complete_structured(
        messages: list[dict[str, str]], model: str, response_format: type, **k: Any
    ) -> Any:
        name = response_format.__name__
        if name == "DocumentStructure":
            # tiny body -> < 90% coverage -> rejected -> REAL rule-based path runs
            return DocumentStructure(
                sections=[
                    SectionBoundary(
                        id="s0", title="x", level="chapter", body="x", page_start=1, page_end=1
                    )
                ]
            )
        if name == "_SegmentSummaryLLM":
            return _SegmentSummaryLLM(
                summary="A concise summary of this how-to step for the learner."
            )
        if name == "_QuizQuestionLLM":
            return _QuizQuestionLLM(
                question="What does this step do?",
                options=["Opens it", "Closes it", "Nothing", "Restarts"],
                correct_index=0,
                explanation="It opens the named item.",
                difficulty="medium",
            )
        if name == "_SegmentComplexityLLM":
            return _SegmentComplexityLLM(
                level="medium",
                cognitive_load="moderate",
                abstraction_level="concrete",
                prerequisite_concepts=[],
                narration_style="conversational",
                quiz_difficulty="medium",
                intervention_sensitivity=0.4,
            )
        if name == "_JargonListLLM":
            return _JargonListLLM(
                terms=[_JargonEntryLLM(term="Task Manager", definition="A system tool.")]
            )
        if name == "_SegmentInterventionsLLM":
            return _SegmentInterventionsLLM(
                distraction=["Focus up.", "Stay with it.", "Keep going."],
                confusion=["Slow down.", "Re-read it.", "Pause a moment."],
                fatigue=["Deep breath.", "Almost done.", "Stretch."],
            )
        if name == "_NarrationScriptLLM":
            return _NarrationScriptLLM(
                narration_style="conversational",
                script="In this step you perform the described action carefully and then continue.",
            )
        if name == "_LessonPlanLLM":
            ids = _segment_ids_from_messages(messages)
            return _LessonPlanLLM(
                title="How-To Lesson",
                subject="Software",
                objectives=["Learn the steps", "Apply them"],
                complexity_level="medium",
                segments=[
                    _LessonPlanSegmentLLM(segment_id=i, title=f"Step {n}", duration_min=2.0)
                    for n, i in enumerate(ids)
                ],
            )
        if name == "_SlideDeckLLM":
            ids = _segment_ids_from_messages(messages)
            return _SlideDeckLLM(
                segments=[
                    _SegmentSlidesLLM(
                        segment_id=i,
                        slides=[
                            _SlideLLM(
                                title=f"Slide for {i}"[:60],
                                bullets=["Do the action", "Then continue"],
                            )
                        ],
                    )
                    for i in ids
                ]
            )
        raise AssertionError(f"unmocked response_format {name}")

    provider = MagicMock()
    provider.complete_structured = AsyncMock(side_effect=complete_structured)
    return provider


@pytest.mark.integration
@pytest.mark.asyncio
async def test_howto_runs_through_real_graph_and_produces_valid_package() -> None:
    from app.modules.content.pipeline.graph import _SAFE_SEGMENT_ID_RE, run_pipeline

    provider = _make_dispatch()
    fake = _StatefulSupabaseFake()
    _redis = _AsyncRedis()
    # Seed the extract checkpoint so extract_node cache-hits and feeds the real
    # how-to text into the REAL structure detection (bypasses the PDF subprocess).
    fake.node_outputs = {
        "extract": {
            "raw_text": HOWTO_TEXT,
            "extracted_images": [],
            "font_blocks": [],
            "page_count": 3,
        }
    }

    with (
        patch("app.core.db.get_supabase", return_value=fake),
        patch("app.providers.llm.factory.get_llm_provider", return_value=provider),
        patch("app.providers.llm.openai.OpenAILLMProvider", return_value=provider),
        patch("app.core.cost_tracker.check_ceiling", new=AsyncMock(return_value=False)),
        patch("app.core.cost_tracker.accumulate_cost", new=AsyncMock(return_value=0.0)),
        patch(
            "app.modules.content.pipeline.graph._synthesize_with_fallback",
            new=AsyncMock(return_value=(b"fake-audio", "sarvam", 0.0)),
        ),
        patch(
            "app.modules.content.pipeline.graph._generate_image_with_fallback",
            new=AsyncMock(return_value=("data:image/png;base64,AAAA", "imagen")),
        ),
        patch("app.core.redis.get_redis", return_value=_redis),
    ):
        package = await run_pipeline(
            FAKE_LESSON_ID, chapter_content=HOWTO_TEXT, book_id=FAKE_BOOK_ID
        )

    # ── AC-2: valid against the FROZEN JSON schema (real Dev1->Dev2 contract) ──
    schema_path = (
        Path(__file__).resolve().parents[4] / "packages" / "shared" / "lesson_package.schema.json"
    )
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(
        instance=package, schema=json.loads(schema_path.read_text(encoding="utf-8-sig"))
    )

    # ── AC-3: the bug class is regression-guarded end to end ──────────────────
    segments = package["segments"]
    # RC-1: ~20 step-sections bounded to structure_max_sections (not the raw 20,
    # not collapsed to 1) — a real multi-segment lesson with a bounded count.
    assert 2 <= len(segments) <= 15, f"over-segmentation not bounded: {len(segments)} segments"
    ids = [s["segment_id"] for s in segments]
    assert len(set(ids)) == len(ids), "segment_ids must be unique (no collisions)"
    for seg in segments:
        assert _SAFE_SEGMENT_ID_RE.match(seg["segment_id"]), f"unsafe id {seg['segment_id']!r}"
        ts = seg["narration"]["timestamps"]
        assert ts, "narration.timestamps must be non-empty (player slide-sync)"
        assert ts[0]["start_ms"] == 0
        for a, b in zip(ts, ts[1:], strict=False):
            assert a["end_ms"] == b["start_ms"], "timestamps must be contiguous"
        assert len(seg["slides"]) >= 1
