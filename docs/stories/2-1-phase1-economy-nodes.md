# Story 2-1 — Phase 1 Economy Nodes (parallel, `settings.llm_mini`)

**Status:** not started
**Sprint:** 2
**Owner:** Dev 1
**Branch:** `sprint2/phase-b-generation-nodes` (shared Sprint 2 branch — see dev note below)
**Source:** `learning-docs/CONTEXT-NEW-CHAT-SPRINT2.md` §7, §15 (S2-1..S2-6); `CLAUDE.md` §9 (Content Generation Pipeline)

## Context

Sprint 1 + hardening (Stories 2-0, 2-0b) shipped a fully working Phase A ingestion pipeline (`extract → structure → chunk → embed`), live-validated at three scales. Phase B (the 11 generation nodes) has not started — `graph.py` has nodes 5-15 as stub placeholders (`return []` / `{}`).

This story implements the six Phase 1 "economy" nodes, all running on `settings.llm_mini` and designed to fan out in parallel per segment via LangGraph `Send()`:

- S2-1 `summarise_segment`
- S2-2 `segment_complexity`
- S2-3 `quiz_generator`
- S2-4 `jargon_extractor`
- S2-5 `intervention_messages`
- S2-6 `narration_generator`

**Critical architectural finding (must be fixed here, not deferred):** the current stub graph wires `lesson_planner`/`slide_generator` directly after `embed`, running BEFORE any economy node executes (`graph.py` lines ~1024-1026). This means `lesson_planner` currently has zero segment summaries available — the exact 5×-cost-overrun violation `CLAUDE.md` warns against. AC-0 below re-wires the graph so all six Phase 1 nodes fan out and complete (barrier) before Phase 2 (`lesson_planner`) starts.

**Segment definition decision:** Phase 1 nodes need a "segment" unit to fan out over, but `lesson_planner` (Phase 2) is what actually produces the lesson's pedagogical segments. Per this story: **"segment" pre-lesson_planner = each entry in `state["sections"]`** (produced by `structure_node`, already available after Phase A). Each Phase 1 node runs once per section. `lesson_planner` later consumes the resulting per-section summaries/complexity/etc. and organizes them into the final lesson plan's segments — it is free to merge, split, or reorder sections into pedagogical segments, but Phase 1 always operates on the Phase A section boundary. Flag this decision explicitly in the 5-agent review (Process Integrity layer) since it's an interpretation of an ambiguous PRD phrase, not a stated fact.

## Acceptance Criteria

### AC-0 Graph re-architecture (prerequisite for all other ACs)
- `graph.py` DAG reordered: `embed` → `[Send() fan-out: summarise_segment, quiz_generator, segment_complexity, jargon_extractor, intervention_messages, narration_generator]` → barrier → `lesson_planner` → `slide_generator` → `tts_node` → `image_generator` → `package_builder`.
- Each Phase 1 node is invoked once per `state["sections"]` entry via LangGraph `Send()`, not once for the whole chapter.
- `lesson_planner_node`'s input assembly reads `state["segment_summaries"]` (list, one per section) — it must NOT read `state["raw_text"]` or `state["chunks"]` for content generation (only `sections` metadata like title/page range is permitted for structural context).
- Module docstring node-order comment at the top of `graph.py` updated to reflect the corrected order.
- **Test:** a graph-shape test asserting `lesson_planner` has zero incoming state dependency on `raw_text`/`chunks` content and only reads `segment_summaries`; a fan-out test asserting all 6 economy nodes are invoked once per section for a 3-section fixture and their outputs are all present before `lesson_planner_node` runs (ordering assertion via call-order mock).

### AC-1 `summarise_segment` (S2-1)
- Model: `settings.llm_mini`. One call per section via `complete_structured()` (or `complete()` + parse) against a small `SegmentSummary` schema (`segment_id`, `summary`).
- Summary is 2-3 sentences, **≤100 words** (validated, not just prompted — reject/truncate/retry on violation, log if truncated).
- Output written to `state["segment_summaries"]`, keyed by section index/id so `lesson_planner` can align it back to structure.
- Wrapped in `_safe_trace()` (Langfuse), `is_circuit_open("openai_mini")` checked before the call, `cost_tracker.accumulate_cost()` called immediately after each response.
- **Test:** word-count enforcement (accepts ≤100, rejects/handles >100); per-section fan-out produces exactly N summaries for N sections; cost tracker invoked once per call.

### AC-2 `segment_complexity` (S2-2)
- Model: `settings.llm_mini`. Output validates against `app.schemas.lesson.SegmentComplexity` exactly (`level`, `cognitive_load`, `abstraction_level`, `prerequisite_concepts`, `narration_style`, `quiz_difficulty`, `intervention_sensitivity`).
- `intervention_sensitivity` constrained to `[0.0, 1.0]` — enforced by the Pydantic model's `Field(ge=0.0, le=1.0)`, plus a node-level guard that clamps/rejects out-of-range LLM output rather than trusting the model config alone.
- **Test:** valid LLM output round-trips through `SegmentComplexity.model_validate`; out-of-range `intervention_sensitivity` (e.g. 1.4) is rejected, not silently clamped without logging.

### AC-3 `quiz_generator` (S2-3)
- Model: `settings.llm_mini`. Output validates against `app.schemas.lesson.QuizQuestion` list — **exactly 4 options** per question (`Field(min_length=4)` on `options`, and the node must also cap at 4, not just floor), `correct_index` in `range(len(options))`, `min_length=4` enforced on `question`/`explanation` text (per AC wording — treat "min_length=4" as the non-empty-content guard, not just the options-count rule already covered above).
- **Test:** malformed LLM output (`correct_index` out of range, <4 or >4 options) is rejected/retried, not silently passed through to the lesson package.

### AC-4 `jargon_extractor` (S2-4)
- Model: `settings.llm_mini`. Output validates against `app.schemas.lesson.JargonEntry` list. No empty `term` or `definition` strings survive into `state["glossary"]`.
- **Test:** LLM output containing an empty-string term/definition is filtered out before being written to state.

### AC-5 `intervention_messages` (S2-5) — CRITICAL, closes Dev 4's tutor gap
- Model: `settings.llm_mini`. Output validates against `app.schemas.lesson.SegmentInterventions` — **exactly 3 messages each** for `distraction`, `confusion`, `fatigue` (`min_length=3, max_length=3` per the frozen schema).
- Messages are generated **once, at pipeline build time** — this node's output is the entire supply of intervention text for a lesson; there must be no code path anywhere in the runtime tutor flow that calls an LLM for intervention text (verify no such call exists in Dev 4's `modules/tutor/` — flag, don't fix, if found).
- Output shape must be assignable directly into `Segment.interventions` (per `app/schemas/lesson.py`) with no reshaping needed by `package_builder` later — this is what unblocks Dev 4's currently-`{}` `_segment_intervention_messages`.
- **Test:** output validates against `SegmentInterventions.model_validate` with exactly 3+3+3 messages; a snapshot test asserting the dict shape matches what `package_builder_node` (S2-11, future) will assign verbatim to `Segment.interventions`.

### AC-6 `narration_generator` (S2-6)
- Model: `settings.llm_mini`. One narration script per section/segment.
- Pacing: **≤15 words/sec** — the node estimates spoken duration from word count (`word_count / 2.5` words/sec average speech rate, or equivalent) and rejects/regenerates scripts whose word count would exceed 15 words/sec against a target duration if one is supplied; at minimum, log and flag any script whose implied pacing exceeds the cap.
- Narration tone/style matches `SegmentComplexity.narration_style` (from AC-2's output for the same section) — the prompt must include the corresponding complexity's `narration_style` field, not generate narration blind to complexity.
- **Test:** pacing guard rejects/flags a script that is too dense for its word budget; narration prompt construction includes `narration_style` sourced from the matching section's complexity output.

### AC-7 Cost ceiling + circuit breaker wiring (cross-cutting, S2-13 partial)
- Every provider call across all 6 nodes: `is_circuit_open("openai_mini")` checked before the call; `cost_tracker.accumulate_cost()` called immediately after; `cost_tracker.check_ceiling()` checked before each node's batch of calls begins.
- On ceiling breach mid-node: downshift is not available for `llm_mini` (already the cheapest tier) — the node must complete the lesson using best-effort/degraded output (e.g. skip remaining sections) and cause the pipeline to terminate with `status="failed"`, error prefixed `"cost_ceiling_exceeded: "` (never a bare `"cost_limit_exceeded"` literal — rule 25, CLAUDE.md).
- **Test:** simulated ceiling breach mid-fan-out results in a `failed` status with the correct error prefix, not a stranded `running` row.

## Dev Notes — cross-module flags (do not fix here)

- **→ Dev 4:** once AC-5 lands, `apps/api/app/modules/tutor/.../_segment_intervention_messages` should stop returning `{}` as soon as `package_builder` (S2-11, a later story) wires `segments[].interventions` from this node's output. This story only produces the data; S2-11 closes the loop. Do not attempt to patch the tutor-side consumer here.
- **Branch note:** per explicit user correction (2026-07-13), all Sprint 2 tasks (S2-1 through S2-14) share the single branch `sprint2/phase-b-generation-nodes` rather than one branch per task. Story-first gate still applies per task (this story file is committed alone and pushed before any implementation commit), but no new branch is created for S2-2 onward.
