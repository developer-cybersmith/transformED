# Bug Planner — Feature Sprint 2 (Dev 1 open items)

**Source:** `docs/master-tracker.md` § "Bug Resolution Sprint (Feature Sprint 2)" → Dev 1 section.
**Scope:** the 4 items from that list still unbuilt as of 2026-09-08 (verified against current code, not the tracker checkboxes). The 5th/6th list items — Nano Banana in the image fallback chain — are excluded here: already done and merged (Story 5-8b, D121 closed FIXED-GUARDED); only the tracker checkbox is stale.

---

## 1. Line-level caption timestamps

**What's missing:** `Narration.timestamps` always ships `[]` (`tts_node`'s own docstring, `graph.py:4009-4015`). The only timing that exists is per-**slide**, not per-caption-line: `_estimate_slide_timestamps` (`graph.py:4668`) produces one `{slide_id, start_ms, end_ms}` per slide, either from a real measured MP3 duration (`tinytag`, Story S3-38) split evenly across slides, or a word-count estimate. No word-level or line-level forced alignment exists anywhere. Explicitly named as deferred since Story 2-8.

**Who's blocked on it:** `docs/master-tracker.md`'s Dev 2 section, two items, both stated explicitly:
- "Caption/subtitle display — one dialogue line at a time, synced to narration timestamps"
- "Highlight/underline the active narration text on slide (karaoke-style sync) using caption timestamps" — **"depends on Dev 1's caption timestamp output"**

Dev 2 has already worked around the absence twice: D90 (2026-08-13) shipped a non-synced, always-visible caption panel specifically because "word/sentence-level SYNCED captions are not possible yet"; S4-07/S4-09 (merged, PR #143) redesigned it to a YouTube/Netflix one-line-at-a-time style, still without real sync data underneath.

**Relevant existing infra:** `tinytag`-measured real audio duration (`tts_node`) and `_estimate_slide_timestamps`'s existing split logic are the closest analogue — the mechanism for turning "total duration + N items" into a timestamp array already exists at the slide level and could plausibly be adapted to line level if per-line text boundaries and a per-line duration estimate (or real alignment) are available.

**Open questions:** word-count-proportional split of the known segment duration (cheap, approximate, no new dependency) vs. real forced alignment (e.g. Whisper timestamps on the synthesized audio, or an alignment library) — accuracy vs. cost/complexity tradeoff. Also: does this need to work across all three TTS fallback tiers (Sarvam, Azure, Browser Speech), given `duration_ms` is already `None` on the browser-fallback path today?

---

## 2. Inject Learner DNA + behavior signals into `lesson_planner` / `slide_generator` / `narration_generator` system prompts

**This is the item we're brainstorming next — details below.**

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
