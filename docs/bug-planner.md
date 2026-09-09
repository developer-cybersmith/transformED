# Bug Planner — Feature Sprint 2 (Dev 1 open items)

**Source:** `docs/master-tracker.md` § "Bug Resolution Sprint (Feature Sprint 2)" → Dev 1 section.
**Scope:** the 3 items from that list still unbuilt as of 2026-09-09 (verified against current code, not the tracker checkboxes). Two list items are excluded here as already done: Nano Banana in the image fallback chain (Story 5-8b, D121 closed FIXED-GUARDED), and line-level caption timestamps (Story 4-29/BR-6 + BR-3, see below) — both merged since this doc was first drafted.

---

## 1. Line-level caption timestamps — DONE (merged 2026-09-08/09)

**Update 2026-09-09:** built and shipped since this doc was first drafted. `Narration.caption_lines: list[CaptionLine]` (new field, `apps/api/app/schemas/lesson.py`) is populated by `_split_into_caption_lines()` inside `package_builder_node` (`graph.py`) — real per-line `{text, start_ms, end_ms}` timestamps, duration distributed proportionally by character count from the same `tinytag`-measured real audio duration `_estimate_slide_timestamps` already used at the slide level (the "relevant existing infra" this doc originally flagged was in fact reused, not reinvented). Empty list on the browser-fallback path or a `tinytag` failure — explicit degraded case (Story 4-29 AC5), not silently wrong. Retroactive-field pattern (`default_factory=list`, not in the JSON schema's `required`) so old lesson records and fixtures validate unchanged. Frontend: `CaptionOverlay` now consumes `caption_lines` directly via `activeCaptionLineIndexFromTimestamps()` when present, falling back to the old proportional-character-count estimate otherwise (Story 2-61/BR-3). Backend: `docs/stories/4-29-caption-lines-schema-pipeline.md`. Frontend: `docs/stories/2-61-caption-sync-real-timestamps.md`.

**Resolved, not left open:** the word-count-vs-forced-alignment question this doc originally posed was answered by choosing the cheaper character-proportional split, consistent with the existing slide-level mechanism, rather than real forced alignment — accuracy vs. complexity tradeoff was made explicitly, not left pending.

---

## 2. Inject Learner DNA + behavior signals into `lesson_planner` / `slide_generator` / `narration_generator` system prompts — DONE

**Update:** built per the "fetch once, checkpoint it" decision recorded below (Story F2-5,
branch `sprint4/s4-dna-context-injection`). New checkpointed graph node
`fetch_learner_context_node` sits between `embed` and the Phase-1 fan-out, delegates to a new
`get_dna_prompt_context()` (`assessment/service.py`) that reuses F2-1's existing query/banding/
formatting logic (zero duplicated prompt-formatting code). `dna_context` reaches all three
target nodes — `narration_generator` via `_FAN_OUT_STATE_KEYS`, `lesson_planner`/
`slide_generator` directly from state — same text verbatim, appended only when non-empty.
Graceful degradation (`""` for a new student with no `learner_dna` row) explicitly tested, not
assumed — the "unchanged when empty" tests were mutation-checked and initially found to be too
weak (comparing two same-value calls, which passes even under a broken implementation); fixed to
assert against the real literal prompt ending instead. Full suite: 1497 passed, 6 skipped, zero
regressions. **Residual, deliberately not done here**: the real per-section token-cost
measurement (Scale & Load Q2 — `narration_generator` injects `dna_context` once per section, not
once per lesson) needs a real Langfuse trace from a live run, which needs the user's go-ahead to
spend real money — not run as part of this implementation pass.

---

## 3. Human narration pipeline

**What's missing:** Nothing exists — no node, no endpoint, no schema field, no Storage convention. Confirmed via repo-wide search (zero hits for anything resembling "human narration" under `apps/api`).

**Scope implied by the tracker line:** "new node to accept human-recorded audio per segment, store in Supabase, sync duration to slide timing." Three distinct pieces: (a) an ingestion path (upload endpoint or admin tool) for a human-recorded clip per segment, (b) Storage — the existing `lesson-audio` bucket is currently written only by `tts_node`'s own synthesis output, so this would be a second writer into the same bucket with a different provenance, (c) duration sync — `_estimate_slide_timestamps` already accepts a `known_duration_ms` computed via `tinytag`; a human-recorded clip's real duration could plug into the same function.

**Already prepared for this, downstream:** Dev 4's BR-2 (merged, PR #163) already verified "tutor intervention/CES timing still functions correctly with variable-length human-recorded narration" — the consuming side has been validated ahead of the producing side existing.

**Open questions:** who records/uploads (admin-only tool, or a per-lesson upload flow the requesting user can use)? Does a human clip replace the TTS-synthesized one entirely for that segment, or are both retained (fallback if the human clip is missing/rejected)? Does `AudioProvider` (the enum on `Narration.audio_provider`) need a new value for this, and does that ripple into cost accounting (a human clip has no per-character TTS cost, but likely a different cost/effort model entirely)?

---

## 4. Redesign `lesson_planner` / `slide_generator` prompts — plain-language + easy-to-understand diagrams

**What's missing:** Both nodes' system prompts are purely structural today. `_planner_system_prompt` (`graph.py:1305`) only specifies title/objectives/complexity_level/segment duration — no instruction about reading level, audience, or explanation style. The only "plain-language" instruction anywhere in the pipeline is `jargon_extractor`'s glossary-definition prompt, which is unrelated (it defines individual terms, not the overall explanation style). `slide_generator`'s prompt has no diagram-clarity guidance at all — zero mentions of "diagram" anywhere in `graph.py`.

**Open questions:** this is a product/content decision before it's an engineering one — what does "plain-language" concretely mean here (reading grade level? avoiding jargon inline vs. relying on the existing glossary? sentence length?), and what does "easy-to-understand diagram prompts" mean for `slide_generator`'s image-generation prompt construction specifically (layout guidance? avoiding dense/technical diagram styles? labeling conventions?). Lowest engineering risk of the four, but needs this scoping conversation before a story can be written.

---

## Brainstorm setup: Item 2 in detail

**Real, relevant infrastructure that already exists:**

`F2-1` (merged, PR #194) built `GET /api/assessment/session/{session_id}/learner-context`, returning a `LearnerContext`:
- `dna: LearnerContextDNA | None` — `badge_labels` (list[str]), `profile_text` (str, DPDP-disclaimer-suffixed), `session_count` (int), `dimension_labels` (dict of 9 dimension keys → band string: "strong"/"developing"/"building"/"emerging" — **never raw numeric values**)
- `current_session: LearnerContextSession` — `quiz_accuracy`, `quiz_total`, `teachback_score`, `teachback_count`, `ces_score` — all specific to one assessment session
- `prompt_text: str` — a pre-built, LLM-ready string combining both blocks, empty string if neither has data

This was built for the **tutor** (Dev 4's Q&A chat), not for content generation. Nothing in `lesson_planner`/`slide_generator`/`narration_generator` calls it or anything like it today.

**The architectural mismatch to resolve first:** F2-1's endpoint is keyed by `session_id` — but `PipelineState` (`graph.py:85`) has `user_id`, not `session_id`, and content generation (Phase B, per chapter) can run before any assessment session for that lesson exists. So:
- The **`dna` block** (historical profile — badges, profile_text, dimension_labels) is keyed by `user_id` alone, at the DB level (`learner_dna` table) — this part is reachable during generation with no session dependency.
- The **`current_session` block** (quiz_accuracy, teachback_score, ces_score for *this* session) structurally cannot apply at generation time — there is no "this session" yet.

So this item is really "reuse the `dna` half of F2-1's logic, by `user_id`, inside three generation nodes" — not a direct call to F2-1's existing endpoint.

**Questions to open the brainstorm with:**
1. Same DNA data into all three nodes verbatim, or does each node need a different slice/framing (e.g. `lesson_planner` cares about pacing/depth, `slide_generator` about visual-vs-text preference, `narration_generator` about tone)?
2. Cost: this adds a DB read (and possibly prompt tokens) to three nodes that currently run per-segment/per-chapter — what's the real token cost of `prompt_text`-style injection at this frequency, against the $3.00/lesson ceiling?
3. New user (no `learner_dna` row yet, `dna` is null per AC4) — every one of these three nodes must degrade gracefully to today's un-personalized behavior, not fail or produce a degenerate prompt.
4. Does this change what "identical input → identical output" means for these nodes' existing idempotency/checkpoint pattern — if DNA is re-fetched on an ARQ retry and has changed since the first attempt (e.g. `session_count` incremented), does the checkpoint still correctly skip re-running, or does this introduce a new source of non-determinism into an already-checkpointed node?
5. Should this reuse `LearnerContextDNA` as-is (import/share the schema) or does content-generation need its own, smaller shape?

**Decision so far (2026-09-09): fetch once, checkpoint it.**

Traced the actual graph topology (`graph.py:5624-5671`):
```
extract → structure → chunk → embed → [Send() fan-out: 6 Phase-1 nodes, incl. narration_generator] → lesson_planner → slide_generator → tts_node → image_generator → package_builder
```

Two things this rules out:
- **Not inside `embed_node`** — its whole job is `embeddings_stored: bool`; every node in this file is scoped that narrowly by convention (`tts_node`'s own docstring: "Input is `state["narration_scripts"]` ONLY").
- **Not inside the Phase-1 router** (`_fan_out_phase1_economy_nodes`) — it's a conditional-edge router, not a checkpointed graph node (no `if "x" in node_outputs: return cached` guard like every real node has). On an ARQ retry it re-runs from scratch every time — DNA-fetching here would re-fetch on every retry, reintroducing the exact non-determinism question 4 above raises.

**Proposed mechanism:** a new, real, checkpointed node (`fetch_learner_context_node`) inserted between `embed` and the fan-out, following the same idempotency pattern as every other node:
```python
graph.add_node("fetch_learner_context", fetch_learner_context_node)
graph.add_edge("embed", "fetch_learner_context")
graph.add_conditional_edges("fetch_learner_context", _fan_out_phase1_economy_nodes, _ECONOMY_NODES)
```
- `narration_generator` (Phase 1, Send()-dispatched) needs `dna_context` added to `_FAN_OUT_STATE_KEYS` (`graph.py:5503`) to receive it in its per-section dispatch payload.
- `lesson_planner` / `slide_generator` (Phase 2, sequential) just read `state["dna_context"]` directly.
- Query: `learner_dna` by `user_id` alone, `.maybe_single()`, null-safe.

**Still open:** whether a new graph node is the right shape vs. some other mechanism — not yet confirmed with the user; "fetch once, checkpoint it" is agreed as the *principle*, this specific implementation is the next thing to validate.
