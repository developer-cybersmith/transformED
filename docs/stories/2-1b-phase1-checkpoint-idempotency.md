# Story 2-1b — Phase 1 Economy Node Checkpoint/Idempotency

**Status:** implemented, pending code review
**Sprint:** 2
**Owner:** Dev 1
**Branch:** `sprint2/phase-b-generation-nodes` (shared Sprint 2 branch)
**Source:** Deferred from Story 2-1's code review (2026-07-13) — see `docs/stories/2-1-phase1-economy-nodes.md` Review Findings and `docs/stories/deferred-work.md`

## Context

Story 2-1 made `summarise_segment_node` and `segment_complexity_node` real (billed OpenAI calls), fanned out once per section via `Send()`. Unlike the four Phase A nodes (`extract`, `structure`, `chunk`, `embed`), which each check `lesson_jobs.node_outputs[node_name]` before doing work and skip on a cache hit, none of the six Phase 1 economy nodes have any idempotency guard. Before Story 2-1 this was free (they were stubs); now a worker crash mid-fan-out means an ARQ retry silently re-runs and re-bills every already-completed section's LLM call.

This also blocks S2-3 through S2-6 (the remaining four economy nodes) from inheriting the same gap — better to design the checkpoint pattern once, here, before they're built.

## Acceptance Criteria

1. Each of the 6 economy nodes checks for a per-section completion record before calling its provider — e.g. `node_outputs[f"{node_name}:{section_id}"]` in the existing `lesson_jobs.node_outputs` JSONB column — and returns the cached result on a hit instead of re-calling the LLM.
2. Each node writes its per-section result to that same key on success, following the existing Phase A checkpoint-write pattern (see `embed_node`'s checkpoint write for the established convention).
3. A simulated ARQ retry (job cancelled after 2 of 3 sections complete for a node, then re-invoked) results in exactly 0 additional LLM calls for the 2 already-completed sections and exactly 1 call for the remaining section.
4. Progress visibility during Phase 1 fan-out: `lesson_jobs` (or a Redis-backed alternative, given `progress_pct` can't be a shared graph-state channel under concurrent `Send()` writes — see Story 2-1's Review Findings) reflects how many of the `6 × N` dispatched calls have completed, not just the pre/post Phase-1 progress percentages already in place.
5. Existing Story 2-1 tests (`test_phase1_economy_nodes.py`) continue to pass with node **behavior** unchanged when no cache hit exists — this story only adds idempotency, it does not change what the nodes produce. **Correction during implementation:** "unmodified" (as originally written) turned out to be unachievable — those tests never mocked Supabase/Redis (no dependency on either existed yet), so adding the checkpoint read/write and progress counter required adding an `autouse` fixture that mocks both as a permanent cache-miss/no-op. The tests' *assertions* and *intent* are unchanged; their *mocking setup* needed updating for the new dependency.

## Dev Notes

- `MemorySaver` (the project's mandated checkpointer, `PostgresSaver` banned per `CLAUDE.md`) is in-memory only and lost on a worker crash — the per-section idempotency guard must live in `lesson_jobs.node_outputs` (durable, Supabase-backed), the same store the four Phase A nodes already use, not in LangGraph's own checkpoint.
- `progress_pct` cannot be written by the economy nodes directly (see Story 2-1's fan-out-safe stub pattern — concurrent writes to a non-reducer `PipelineState` key raise `InvalidUpdateError`). Any progress-visibility mechanism here needs its own channel (e.g. a Redis hash keyed by lesson_id, incremented per completed dispatch) rather than the `PipelineState` graph channel.
- Scope boundary: this story does not implement S2-3 through S2-6's actual generation logic — only retrofits the checkpoint pattern onto whichever economy nodes exist by the time this lands (currently 2 of 6; more may exist by the time this is picked up).
