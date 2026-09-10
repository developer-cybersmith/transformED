# Story F2-5 — Inject Learner DNA Context into Content-Generation Prompts

**Epic:** Feature 2 — Bug Resolution Sprint
**Story:** F2-5
**Branch:** `sprint4/s4-dna-context-injection`
**Owner:** Dev 1
**Status:** review — all 8 ACs done and live-verified end-to-end against real infrastructure
(2026-09-09), not just unit tests

---

## Story

As a **returning student**, I want the lesson I'm generating to be shaped by what the system already knows about how I learn, so that the plan, slides, and narration feel personalized instead of identical to what a first-time student would get.

---

## Background

`docs/master-tracker.md`'s Bug Resolution Sprint (Feature Sprint 2) lists, under Dev 1: "Inject Learner DNA + behavior signals into `lesson_planner` / `slide_generator` / `narration_generator` system prompts." `docs/bug-planner.md` (this sprint's working doc) traced the real state before this story: Story F2-1 already built the Learner DNA fetch + descriptive-banding + prompt-formatting logic for the **tutor** (session-keyed, Dev 3's `assessment` module) — nothing in content generation calls it or anything like it today.

**Design decisions (this session, confirmed with the user before writing this story):**
- **New checkpointed graph node** (`fetch_learner_context_node`), not folded into an existing node. `embed_node`'s own idempotency cache-hit returns early on a retry once embeddings are done — code added after that early-return inside `embed_node` would never re-run on such a retry, so a dedicated node is the correct place, not a cost-saving shortcut.
- **Reuse Story F2-1's existing logic**, not a duplicate. One new, small, additive function in `apps/api/app/modules/assessment/service.py` (Dev 3's module — flagged for their awareness in the PR) reuses the *dna*-half of F2-1's already-reviewed query/banding/prompt-formatting code, keyed by `user_id` alone (content generation has no assessment session yet — F2-1's `current_session` half does not apply here).
- **Same DNA text into all three consuming nodes**, verbatim, to start — no per-node framing yet.

---

## Acceptance Criteria

**AC1 — Reusable DNA-context function:**
`get_dna_prompt_context(user_id: str, supabase: Client) -> str` (new, `apps/api/app/modules/assessment/service.py`) returns `""` when the student has no `learner_dna` row (graceful degradation — never raises, never null), and a non-empty, descriptive-language-only string (reusing the existing `_build_learner_prompt_text`/`_dim_band`/`ALL_NINE_DIMENSIONS` logic F2-1 already built and tested) when a row exists. No raw numeric dimension values ever appear in the returned string.

**AC2 — New checkpointed graph node:**
`fetch_learner_context_node` (new, `apps/api/app/modules/content/pipeline/graph.py`) sits between `embed` and the Phase-1 `Send()` fan-out. It follows the same idempotency/checkpoint pattern every other node in this file uses: on a fresh run, calls `get_dna_prompt_context` once and writes `node_outputs["fetch_learner_context"] = {"dna_context": ...}`; on an ARQ retry of the same job, returns the already-checkpointed value without re-querying.

**AC3 — `dna_context` reaches all three target nodes:**
`PipelineState` gains a `dna_context: str` key. `_FAN_OUT_STATE_KEYS` includes `"dna_context"` so `narration_generator_node` (Phase 1, Send()-dispatched per section) receives it in its dispatch payload. `lesson_planner_node` and `slide_generator_node` (Phase 2, sequential) read `state["dna_context"]` directly.

**AC4 — All three nodes' system prompts include the DNA context when present:**
When `dna_context` is non-empty, each of `lesson_planner_node`'s, `slide_generator_node`'s, and `narration_generator_node`'s system-prompt message includes it verbatim (same text, no per-node framing in this story).

**AC5 — Graceful degradation is explicit, not assumed:**
When `dna_context` is `""` (new user, no `learner_dna` row), all three nodes' system prompts are **byte-identical** to their pre-this-story behavior — asserted directly in tests, not inferred from "appending an empty string should be a no-op."

**AC6 — Idempotency under ARQ retry:**
If a job retries after `fetch_learner_context` already succeeded, the retry reuses the exact same `dna_context` — no re-fetch, no risk of a mid-generation DNA change (e.g. `session_count` incrementing elsewhere) silently producing inconsistent prompts across nodes within one lesson.

**AC7 — Existing guard tests pass:**
`test_fan_out_state_keys.py` (extended with a `"dna_context"` case, mirroring its own existing `"tier"` regression) and `test_unbounded_queries.py` both pass — the new query is `.maybe_single()` on a `UNIQUE`-constrained column, inherently bounded.

**AC8 — No code changes outside the allowlist:**
Nothing in `apps/web`, no other pipeline node, no schema/contract file changes. `docs/bug-planner.md`'s Item 2 is marked done in the same PR.

---

## Scale & Load

1. **What is ONE unit of work, and what is its range?**
   One unit of work is one DB read (`learner_dna` by `user_id`) plus one formatted string, done once per lesson-generation attempt. Range: 0 rows (a new student who hasn't completed onboarding yet) to 1 row — `learner_dna.user_id` carries a `UNIQUE` constraint (`supabase/migrations/20260611000000_initial_schema.sql`), so more than 1 is not a real case to handle.

2. **Which budgets are FIXED while the input VARIES — and what happens past them?**
   The real fixed budget here is prompt tokens against the $3.00/lesson cost ceiling, not the DB read itself. `narration_generator` is Send()-dispatched **once per section** (`_ECONOMY_NODES`, `_fan_out_phase1_economy_nodes`) — the same `dna_context` string is injected into **every section's** LLM call, not once per lesson, so its real token cost multiplies by section count. This is **not yet measured** in this story — the PR must include a real Langfuse-trace check of the actual added token cost on a real lesson generation, not an assumption that a short profile string is negligible. If it turns out to be non-negligible at high section counts, that becomes a new, explicitly registered follow-up (a `D-nn`), not a silent absorption into this story's scope.

3. **What is the SCOPE of every limit — per user, per instance, or per deployment?**
   Scoped **per lesson-generation attempt**: `dna_context` is fetched once and checkpointed on that lesson's own `lesson_jobs.node_outputs` row, then reused unchanged by every node within that one generation (`lesson_planner` once, `slide_generator` once, `narration_generator` N times for N sections). It is never shared or cached across different lessons or different users.

4. **Which reads and writes are UNBOUNDED?**
   None. The only new query is `.maybe_single()` against `learner_dna` filtered by `user_id`, which is `UNIQUE` — bounded to at most one row by the database schema itself, not by application-level `.limit()`.

5. **Which caps were INHERITED from an earlier design, and have they been re-derived?**
   Nothing is inherited — this is new. The one thing this story must re-derive rather than assume: whether the added prompt length, multiplied across `narration_generator`'s N per-section calls, meaningfully changes real per-lesson cost. See Q2.

6. **Is every check-then-act sequence safe under CONCURRENT requests?**
   Yes — this is a pure read with no check-then-act mutation. Two lessons generating concurrently for the same `user_id` (or for different users) each independently fetch and checkpoint their own `dna_context` on their own `lesson_jobs` row; there is no shared mutable state and no race to guard.

---

## Tasks / Subtasks

- [x] Task 1 — `get_dna_prompt_context` (AC1)
  - [x] 1.1 Add the function to `apps/api/app/modules/assessment/service.py`, reusing the existing `learner_dna` query shape (`get_learner_context`'s Step 2), `_dim_band`/`ALL_NINE_DIMENSIONS` banding, and `_build_learner_prompt_text(dna, session=LearnerContextSession())` for the actual string — zero new prompt-formatting code.
  - [x] 1.2 RED: write tests first — no row → `""`; a row exists → non-empty string with no raw floats. Confirm they fail (function doesn't exist yet).
  - [x] 1.3 GREEN: implement, confirm tests pass.

- [x] Task 2 — `fetch_learner_context_node` + graph wiring (AC2, AC3, AC6, AC7)
  - [x] 2.1 RED: `test_f2_5_dna_context_injection.py` (new) — cache-hit path, no-row path, row-exists path, checkpoint-write shape. `test_fan_out_state_keys.py` — new `"dna_context"` case. Confirmed all fail.
  - [x] 2.2 GREEN: implemented the node mirroring `embed_node`'s exact idempotency shape; wired `add_node`/`add_edge`/`add_conditional_edges`; added `dna_context` to `PipelineState` and `_FAN_OUT_STATE_KEYS`.

- [x] Task 3 — Consumption in the three nodes (AC4, AC5)
  - [x] 3.1 RED: extended `test_lesson_planner_node.py`, `test_slide_generator_node.py`, `test_phase1_economy_nodes.py` — non-empty `dna_context` appears in the system prompt; empty `dna_context` leaves the prompt byte-identical to today. Confirmed fail.
  - [x] 3.2 GREEN: appended `state.get("dna_context", "")` at each of the three system-prompt construction sites.

- [x] Task 4 — Real cost measurement (Scale & Load Q2)
  - [x] 4.1 **Done, live, 2026-09-09** — ran a real lesson generation (small 3-page book, T3 tier, real student with a real `learner_dna` row) against the real running ARQ worker. Pulled the real Langfuse trace and confirmed the injected DNA text reached exactly the 5 real LLM calls expected (2× `gpt-4o` — `lesson_planner`/`slide_generator`, 3× `gpt-4o-mini` — `narration_generator`, one per section). Tokenized the actual injected string: 99 tokens per call. Real added cost for this whole lesson: **$0.00054** — negligible against the $3.00/lesson ceiling, measured, not assumed. See Completion Notes for full detail.

- [x] Task 5 — Full-suite verification + docs
  - [x] 5.1 `ruff format --check`, `ruff check` clean on all touched files; `mypy` shows only the 4 pre-existing httpx-version errors in untouched provider files (documented baseline elsewhere in this register). Full `pytest tests/unit/`: 1497 passed, 6 skipped, zero regressions (baseline before this story: 1466 passed).
  - [x] 5.2 Mutation-checked the fan-out-key test (removing `"dna_context"` from `_FAN_OUT_STATE_KEYS` → the pinned regression test goes red, correctly). Mutation-checked all three "unchanged when empty" tests — **first attempt was too weak** (comparing two same-value calls, which passes even with the bug present); fixed to assert against the real literal prompt content, re-verified the fix actually catches the mutation. All restored clean, re-verified via full re-run.
  - [x] 5.3 Marked `docs/bug-planner.md`'s Item 2 done, same PR (branch merged in cleanly).

---

## Dev Notes

- `narration_generator_node`, `lesson_planner_node`, `slide_generator_node` system-prompt construction points (for the append): `graph.py`'s `_planner_system_prompt()`, the inline system message inside `slide_generator_node`, and the inline system message inside `narration_generator_node` — re-read each at implementation time to get the exact current text, not from memory.
- `embed_node`'s idempotency/checkpoint pattern (`graph.py`) is the template for `fetch_learner_context_node` — same shape: read `lesson_jobs.node_outputs`, cache-hit early return, else do the real work, then write the checkpoint.
- `get_learner_context`'s Step 2 (`assessment/service.py`) is the template for the `learner_dna` query — same table, same column selection, same `.maybe_single()`.
- `LearnerContextSession`'s fields are all optional/defaulted — `LearnerContextSession()` (all defaults) is a valid, safe "no session" instance to pass into the existing `_build_learner_prompt_text`, producing zero "Current Session" lines and only the DNA-profile part.

### References

- [Source: docs/bug-planner.md — Item 2, the brainstorm/decision record this story implements]
- [Source: docs/stories/f2-1-dna-prompt-context-api.md — the existing DNA logic this story reuses]
- [Source: apps/api/app/modules/content/pipeline/graph.py — `embed_node`, `_FAN_OUT_STATE_KEYS`, `_fan_out_phase1_economy_nodes`, `_build_pipeline_graph`]
- [Source: apps/api/app/modules/assessment/service.py — `get_learner_context`, `_build_learner_prompt_text`, `_dim_band`]
- [Source: supabase/migrations/20260611000000_initial_schema.sql — `learner_dna` table, `UNIQUE` constraint on `user_id`]

## Dev Agent Record

### Agent Model Used

Claude Sonnet 5 (claude-sonnet-5)

### Debug Log References

None — no live infra call, no debugging incident. Full test suite output: 1497 passed, 6 skipped
(baseline before this story: 1466 passed).

### Completion Notes List

- Reused F2-1's exact query/banding/formatting logic with zero duplication — `get_dna_prompt_context`
  is a thin wrapper calling `_build_learner_prompt_text(dna, LearnerContextSession())`, the same
  already-reviewed function F2-1 built. `LearnerContextSession()`'s all-optional/defaulted fields
  make an empty "no session" instance valid, exactly as planned.
- Traced the real graph topology directly (`_build_pipeline_graph`) rather than trusting memory —
  confirmed `narration_generator` is genuinely Phase-1 (Send()-dispatched, once per section,
  before `lesson_planner`/`slide_generator`), which is why `fetch_learner_context_node` had to sit
  before the fan-out, not between Phase-2 nodes.
- **Real mistake caught by mutation-checking, corrected in-session**: the first version of the
  "empty dna_context leaves the prompt unchanged" tests (all three: `_planner_system_prompt`,
  `slide_generator_node`, `narration_generator_node`) compared two calls that both implicitly
  resolved to the same empty value — this passes even when the implementation unconditionally
  appends `dna_context` regardless of emptiness, which I confirmed by deliberately introducing
  that exact bug and watching all three tests still pass. Fixed by asserting against the real
  literal prompt content/ending instead of a self-referential two-calls-agree comparison;
  re-verified the fix actually catches the mutation this time (all three correctly went red),
  then restored the real code and re-confirmed the full suite green.
- **Task 4 (real per-section token-cost measurement) — done live, 2026-09-09, with the user's
  explicit go-ahead.** Real end-to-end test, against the real running ARQ worker (not a mock):
  - Real, existing infra reused — a 3-page book (`short_3page.pdf`, already ingested), its 3-chunk
    "Introduction to Cell Biology" chapter, and a real student (`learner_dna` row seeded
    2026-08-05 for unrelated upload-feature testing) — no new book upload, minimal real spend.
    Inserted `lessons`/`lesson_jobs` rows directly and enqueued `content_pipeline_job` on the real
    `hie:pipeline` ARQ queue (T3 tier, cheapest).
  - Live worker log confirmed `fetch_learner_context_node` actually ran mid-pipeline
    (`last_node: fetch_learner_context`), then the job completed successfully in 203.6s:
    `lessons.status = 'ready'`, real 3-segment package, real slides, real narration on every
    segment.
  - **Checkpoint verified directly**: `lesson_jobs.node_outputs.fetch_learner_context.dna_context`
    contains the real, formatted DNA text (`"**Student Learning Profile:** ..."`).
  - **Reached the LLM — confirmed via the real Langfuse trace, not inferred.** Computed the
    trace's deterministic id (`Langfuse.create_trace_id(seed=lesson_id)`, this codebase's own
    convention) and pulled it via the public API. Searched all 39 real `GENERATION` observations
    for the literal injected text: found in **exactly 5** — matching the predicted shape exactly
    (2× `gpt-4o`: `lesson_planner` + `slide_generator`; 3× `gpt-4o-mini`: `narration_generator`,
    once per section, confirming the Scale & Load Q2 concern that this node injects per-section,
    not per-lesson).
  - **Real cost, measured not assumed**: tokenized the actual injected string with `tiktoken`
    (`gpt-4o` encoding) — 99 tokens, present identically in the observed `input_tokens` delta on
    all 5 real calls. Total added cost for this whole lesson: 2×(99/1e6×$2.50) +
    3×(99/1e6×$0.15) = **$0.00054** — negligible against the $3.00/lesson ceiling. Scales linearly
    with section count; even at the pipeline's own max (`_MAX_PHASE1_SECTIONS=60`), still
    negligible.
  - **One real, honest finding, investigated and confirmed NOT a bug**: the fetched context showed
    `"badges: none yet"` and every dimension as `"developing"`, despite the real row having a
    badge (`"Curious Learner"`) and varied scores (55-72). Root cause confirmed by reading
    `BADGE_THRESHOLDS` (`onboarding_questions.py`) directly: `"Curious Learner"` is not one of the
    9 real canonical badge strings (`"Curious Explorer"` is) — this test row was a manually-seeded
    fixture predating that exact naming, and `_build_learner_prompt_text`'s existing allowlist
    filter (F2-1, security-motivated: never let an arbitrary/stale badge string reach an LLM
    prompt) correctly rejected it. The "developing" bands are also correct: all 9 real dimension
    values (55-72) genuinely fall in `_dim_descriptor`'s 55-74.99 "developing" band by coincidence
    of the seeded values, not a bug. Both mechanisms behaved exactly as designed.
  - `docs/bug-planner.md`'s Item 2 update revised to remove the "not yet measured" caveat now that
    this has real evidence behind it.
- `docs/bug-planner.md` (previously on its own unmerged branch, `feature2/bug-planner-doc`) was
  merged into this branch cleanly (no conflicts) so Item 2 could be marked done in this same PR,
  per AC8.

### File List

- `apps/api/app/modules/assessment/service.py` (new function: `get_dna_prompt_context`)
- `apps/api/app/modules/content/pipeline/graph.py` (new node `fetch_learner_context_node`; graph
  wiring; `PipelineState.dna_context`; `_FAN_OUT_STATE_KEYS` extended; 3 consumption call sites)
- `apps/api/tests/unit/test_f2_5_dna_context_injection.py` (new)
- `apps/api/tests/unit/test_fan_out_state_keys.py` (extended)
- `apps/api/tests/unit/test_lesson_planner_node.py` (extended)
- `apps/api/tests/unit/test_slide_generator_node.py` (extended)
- `apps/api/tests/unit/test_phase1_economy_nodes.py` (extended)
- `docs/bug-planner.md` (Item 2 marked done)
- `docs/stories/f2-5-dna-context-injection.md` (this file)
