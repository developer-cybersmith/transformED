# Story 2.28: Pipeline state duplication fix + e2e duplication guards

Status: ready-for-dev

## Story

As Dev 1 (content pipeline owner),
I want LangGraph nodes to stop re-emitting reducer-backed state channels, and the e2e integration test to actively guard against it,
so that a single clean pipeline run produces exactly one copy of each quiz question, summary, narration script and glossary entry — instead of 16 copies — and so this class of defect can never silently return.

**Source:** reported by Dev 2 from a live end-to-end test on a Refresher-tier PDF (2026-07-27). Observed: 32 quiz questions for a 2-question segment and 48 for a 3-question segment — 16× each. Root-caused 2026-07-28.

## Context — what actually causes this

`PipelineState` declares six Phase-1 channels as **concatenating reducers**:

```python
segment_summaries: Annotated[list[dict[str, Any]], operator.add]
quiz_questions:    Annotated[list[dict[str, Any]], operator.add]
# ...and glossary, narration_scripts, segment_complexities, interventions
```

A LangGraph node's return dict is *merged* into state. For an `operator.add` channel, "merged" means **appended**. So a node that returns `{**state, ...}` re-appends every value already accumulated in those channels — doubling them.

Four nodes run **after** the Phase-1 fan-in and each spread `**state`:

| Node | Return sites |
|---|---|
| `lesson_planner_node` | 1194, 1394 |
| `slide_generator_node` | 1491, 1685 |
| `tts_node` | 3063, 3187 |
| `image_generator_node` | 3316, 3421 |

**2⁴ = 16×.** This happens in a **single clean run** — no ARQ retry required. This is why Dev 2 saw exactly 16× on both a 2-unique and a 3-unique segment: the multiplier comes from the graph's shape, not from a retry count. (`max_tries=3` could never produce 16 anyway.)

The remaining spreads — `extract_node` (250, 427), `structure_node` (492, 595), `chunk_node` (637, 723), `embed_node` (779, 965), `package_builder_node` (3575, 3894) — run before the channels fill or after everything reads them, so they do **not** multiply. They are still wrong: they copy `raw_text`, `chunks` and base64 image payloads into every checkpoint. The comment already at `graph.py:3902` acknowledges exactly this hazard for the `Send()` payload.

### Two rejected explanations (do not re-litigate)

- **"It's ARQ retries + MemorySaver thread reuse."** Investigated and disproven: `max_tries=3` caps retries at 3×, which cannot yield 16×. Thread reuse is a real but separate hygiene problem (see AC-5) — it is **not** the cause.
- **Dev 2's proposed fix — "skip re-dispatching Phase 1 if `lesson_jobs.last_node` shows it completed" — is UNSAFE.** Accumulated reducer state lives only in the process-local `MemorySaver`. After a worker restart, or a different worker picking up the retry, `lesson_planner` and `package_builder` would run with **empty** `segment_summaries`/`quiz_questions` and ship a structurally valid but content-empty lesson. Measured: re-dispatching Phase 1 costs **zero** extra LLM calls (93 → 93) because the Supabase checkpoints absorb it. Skipping buys nothing and risks everything.

## Acceptance Criteria

1. **AC-1 — No node returns a spread of incoming state.** All 18 `**state` return sites in `apps/api/app/modules/content/pipeline/graph.py` are rewritten to return only the keys that node owns (lines 250, 427, 492, 595, 637, 723, 779, 965, 1194, 1394, 1491, 1685, 3063, 3187, 3316, 3421, 3575, 3894). Note 250 and 427 are **multiline** spreads inside a dict literal — a naive `return {**state, ` regex misses them.
2. **AC-2 — Source-level guard.** A new test walks `apps/api/app/modules/content/pipeline/**/*.py` and fails if any function returns a dict literal containing `**state`. Directory-walking, **not** pinned to `graph.py` — `pipeline/nodes/` already exists and CLAUDE.md mandates future node extraction there.
3. **AC-3 — `tier` reaches Phase 1 nodes.** `_FAN_OUT_STATE_KEYS` (`graph.py:3904`) gains `"tier"`. The `Send()` payload **replaces** state for the dispatched node, so `state.get("tier")` inside all six Phase-1 nodes currently always resolves to the `T2` default — silently disabling the S2-LM3/LM4/LM5 tier bands. A T1 lesson must produce a T1 quiz-count band.
4. **AC-4 — Per-node return-key assertions.** For `lesson_planner`, `slide_generator`, `tts_node`, `image_generator`: assert the returned key set is exactly the keys that node owns (e.g. `set(await tts_node(state)) == {"audio_assets", "progress_pct"}`).
5. **AC-5 — Per-attempt `thread_id` + checkpoint eviction (hygiene, NOT the fix).** `run_pipeline` builds a unique `thread_id` per invocation and discards the thread in a `finally`. Explicitly labelled in the PR as memory hygiene so it is never mistaken for the duplication cure.
   - The nonce must be computed **inside the function body** — a `uuid4()` default argument evaluates once at import and defeats the fix.
   - `content_pipeline_job` must pass `job_try`. **`ctx["job_id"]` alone is not a uniquifier** — `router.py:271` pins `_job_id=f"pipeline:{lesson_id}"`, byte-identical across every retry.
   - **Invariant:** `attempt` scopes **only** the LangGraph `thread_id`, **never** the `merge_lesson_job_node_output` key space. All seven tests in `test_phase1_checkpoint_idempotency.py` depend on those keys being `f"{node}:{section_id}"`; attempt-scoping them would re-bill every section on retry against the $3.00 ceiling.
6. **AC-6 — e2e harness repaired.** `tests/integration/test_howto_pipeline_e2e.py` passes. The fake provider gains a `_QuizBatchLLM` dispatch branch (added by Story 3-28's batch-shaped quiz generation, never mocked — the file has been red on `main` for weeks). Sweep for any other unmocked `_*LLM` response formats.
7. **AC-7 — e2e duplication assertions.** The happy-path e2e test asserts, per segment, `2 <= len(seg["quiz"]) <= 3`; globally, `len(qids) == len(set(qids))`; and in total `sum(len(s["quiz"]) for s in segments) == 3 * len(segments)`. Plus: spy `_LessonPlanLLM`'s prompt and assert `count("- segment_id=") == len(segments)` — proving the planner sees each segment once. **These assertions fail before AC-1 and pass after; that is the point.**
8. **AC-8 — Pre-spend canaries.** A distinct-vs-total check at `lesson_planner_node` (before the cache-hit read, so it fires before any GPT-4o token is spent) and at `tts_node` entry on `narration_scripts` (the only place duplicated narration is caught before paid synthesis). Residual check in `package_builder_node` on **exact keys** — `(segment_id, question_id)` and `(segment_id, term)` — with **no** count bands (jargon has no per-segment cap, so a band guarantees false positives, and `LoggingIntegration(event_level=ERROR)` turns each into a Sentry issue).
9. **AC-9 — No regression.** Full suite shows exactly the pre-existing unrelated failures — no more, no fewer. `ruff check`, `ruff format --check`, `mypy app/` clean on every touched file.

## Tasks / Subtasks

- [ ] Task 1 (AC-6): repair the e2e harness — `_QuizBatchLLM` branch, sweep for other unmocked formats, delete the now-dead `_QuizQuestionLLM` branch, make fixture narration segment-specific, function-scoped autouse `_reset_compiled_graph` fixture.
- [ ] Task 2 (AC-7): add the RED duplication assertions to the e2e happy path.
- [ ] Task 3 (AC-1): strip `**state` from all 18 return sites.
- [ ] Task 4 (AC-3): add `"tier"` to `_FAN_OUT_STATE_KEYS` + tier-band test.
- [ ] Task 5 (AC-2, AC-4): source-level guard test + per-node return-key assertions.
- [ ] Task 6 (AC-8): the three canaries + caplog tests.
- [ ] Task 7 (AC-5): per-attempt `thread_id` + `finally`-scoped eviction + worker plumbing.
- [ ] Task 8 (AC-9): full suite, lint, types; confirm AC-7 assertions now GREEN.

## Dev Notes

- **Cost note for the PR body:** this reduces real TTS spend ~4×. Every existing $3.00/lesson calibration and Langfuse cost baseline is inflated and must be re-measured before drawing any ceiling conclusions.
- **Do NOT blank the Phase-1 cache-hit returns to `{}`** (`graph.py:2159`, `2786`). With a fresh `thread_id` those returns are the **only** path by which cached work reaches `package_builder`. Blanking them ships a quiz-less lesson.
- **Eviction test traps:** do not assert `hasattr(cp, "adelete_thread")` — `BaseCheckpointSaver` defines it (raising `NotImplementedError`), so it can never fail. Never index `storage`/`writes`/`blobs` in assertions — they are `defaultdict`s and indexing *creates* the key; use `thread_id not in saver.storage`. Bind `saver` before any `_compiled_graph = None`.
- **`assert pkg2["segments"] == pkg1["segments"]` is vacuous** — `package_builder` cache-hits at 3575 and returns run 1's dict verbatim. Assert on spy-captured run-2 state instead.
- Every new test needs `@pytest.mark.unit` **and** `@pytest.mark.asyncio` — `-m unit` with `--strict-markers` silently deselects unmarked tests and still reports green.
- Verification command (system Python cannot even collect): `apps/api/.venv/Scripts/python.exe -m pytest tests/integration/test_howto_pipeline_e2e.py -q`

### Project Structure Notes

Touches `apps/api/app/modules/content/pipeline/graph.py`, `apps/api/app/workers/jobs/content_pipeline.py`, `apps/api/tests/integration/test_howto_pipeline_e2e.py`, and new/updated unit tests. **No** `packages/shared/*` and **no** `supabase/migrations/*` file is touched — CLAUDE.md §16 four-dev gate is **not** triggered. Zero `apps/web/**` changes.

### Cross-team

The same `{**state, ...}` pattern exists in `apps/api/app/modules/tutor/state_machine/graph.py` (Dev 4), plus an un-evicted `MemorySaver` in the **long-lived API process** — a worse exposure than the worker. Hand off separately; out of scope here.

### References

- [Source: docs/reports/sprint2-360-audit-2026-07-27.md]
- [Source: DEV1-FIX-PLAN.md — Phases 0, 1, 2]
- [Source: CLAUDE.md Development Rules — the two LangGraph state rules added 2026-07-28]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-28 | Story created — combines the e2e harness repair with the duplication fix, because the AC-7 assertions are RED until AC-1 lands and must ship in one PR. | Dev 1 |
