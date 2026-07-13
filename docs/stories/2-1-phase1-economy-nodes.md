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
- Calls go through `OpenAILLMProvider(lesson_id).complete_structured(...)` — this already internally checks `is_circuit_open("openai")` (the provider's hardcoded circuit key, not per-model) and accumulates cost via `response.usage` before returning. **Nodes must NOT re-implement circuit-breaker or cost-accumulation checks themselves** — that would duplicate (and could diverge from) the provider's own logic. `_safe_trace()`-wrapped Langfuse spans are also already handled inside the provider.
- **Test:** word-count enforcement (accepts ≤100, rejects/handles >100); per-section fan-out produces exactly N summaries for N sections; cost tracker invoked once per call.

### AC-2 `segment_complexity` (S2-2)
- Model: `settings.llm_mini`. Output validates against `app.schemas.lesson.SegmentComplexity` exactly (`level`, `cognitive_load`, `abstraction_level`, `prerequisite_concepts`, `narration_style`, `quiz_difficulty`, `intervention_sensitivity`).
- `intervention_sensitivity` constrained to `[0.0, 1.0]` — enforced by the Pydantic model's `Field(ge=0.0, le=1.0)`, plus a node-level guard that clamps/rejects out-of-range LLM output rather than trusting the model config alone.
- **Test:** valid LLM output round-trips through `SegmentComplexity.model_validate`; out-of-range `intervention_sensitivity` (e.g. 1.4) is rejected, not silently clamped without logging.

### AC-3 `quiz_generator` (S2-3)
- Model: `settings.llm_mini`. Output validates against `app.schemas.lesson.QuizQuestion` list.
- **Schema gap to guard against:** `QuizQuestion.options` is `Field(min_length=4)` in `app/schemas/lesson.py` — a **minimum only**, no maximum. Pydantic validation alone will NOT reject a 5- or 6-option response. The node must independently enforce **exactly 4 options** (truncate/reject/retry on LLM output with ≠4), since the PRD and tracker both require exactly 4 and the frozen schema doesn't close that gap.
- `correct_index` must be in `range(len(options))` after the exactly-4 guard is applied (validate range against the final 4-item list, not a pre-truncation list).
- `question` and `explanation` must be non-empty strings — reject/regenerate on blank content.
- **Test:** LLM output with 5+ options is rejected or truncated to exactly 4 (not silently passed through with 5); `correct_index` out of range is rejected/retried; blank `question`/`explanation` is rejected.

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

### AC-7 Cost ceiling wiring (cross-cutting, S2-13 partial)
- Circuit-breaker checks and per-call cost accumulation are **already handled inside `OpenAILLMProvider.complete_structured()`** (verified: `apps/api/app/providers/llm/openai.py` — `is_circuit_open("openai")` at the top of the method, `_maybe_accumulate_cost()` after a successful response) — nodes do not call these directly. The only node-level responsibility is `cost_tracker.check_ceiling(lesson_id)` checked before each node's batch of per-section calls begins, so a lesson that's already over budget doesn't start a 6th (or Nth) fan-out call.
- On ceiling breach mid-node: downshift is not available for `llm_mini` (already the cheapest tier) — the node must complete the lesson using best-effort/degraded output (e.g. skip remaining sections) and cause the pipeline to terminate with `status="failed"`, error prefixed `"cost_ceiling_exceeded: "` (never a bare `"cost_limit_exceeded"` literal — rule 25, CLAUDE.md).
- **Test:** simulated ceiling breach mid-fan-out results in a `failed` status with the correct error prefix, not a stranded `running` row; a node never calls `is_circuit_open`/`accumulate_cost` itself (regression guard against re-duplicating provider-layer logic).

## Tracker Cross-Reference Notes (`docs/dev1-tracker.md`)

- **File layout — tracker is stale, follow the actual Sprint 1 convention instead.** The tracker's "Files to Create" table (lines 72-82) lists one file per node (`nodes/summarise_segment.py`, `nodes/segment_complexity.py`, etc.). That's not what Sprint 1 actually did: all 15 node functions (`extract_node` through `package_builder_node`) are defined directly in `apps/api/app/modules/content/pipeline/graph.py` (1121 lines). `nodes/` only holds extracted helper modules (`chunking.py`, `extract_subprocess.py`, `structure_detection.py`) for logic too large to inline. **This story adds the six economy-node functions directly to `graph.py`**, consistent with the established pattern — do not create six new files under `nodes/` on the tracker's say-so.
- **AC-0 (graph reordering) has no corresponding tracker task.** The tracker's Sprint 2 section correctly states the required architecture ("Phase 1 ... ALL must complete before Phase 2 starts") but doesn't call out that the current stub graph violates it. That's addressed here as AC-0 since it blocks S2-1 through S2-6 from being meaningful; no tracker edit needed since the underlying tasks (S2-1..S2-6) aren't yet checked off.
- **S2-1's own AC as written in the tracker** ("Summary ≤100 words; lesson_planner (S2-7) consumes summaries not raw text") is a forward-reference to S2-7 — S2-7 is out of scope for this story; AC-0 here only guarantees the wiring is in place for S2-7 to consume correctly later, it does not implement `lesson_planner` itself.

## Dev Notes — cross-module flags (do not fix here)

- **→ Dev 4:** once AC-5 lands, `apps/api/app/modules/tutor/.../_segment_intervention_messages` should stop returning `{}` as soon as `package_builder` (S2-11, a later story) wires `segments[].interventions` from this node's output. This story only produces the data; S2-11 closes the loop. Do not attempt to patch the tutor-side consumer here.
- **Branch note:** per explicit user correction (2026-07-13), all Sprint 2 tasks (S2-1 through S2-14) share the single branch `sprint2/phase-b-generation-nodes` rather than one branch per task. Story-first gate still applies per task (this story file is committed alone and pushed before any implementation commit), but no new branch is created for S2-2 onward.
