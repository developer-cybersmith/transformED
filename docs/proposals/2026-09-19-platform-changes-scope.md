# Platform Change Initiative — Scope Doc (2026-09-19)

**Status:** Research phase — no code changes yet.
**Owner:** developer.team2@cybersmithsecure.com
**Purpose:** Capture the 4 changes currently under consideration, and the findings from parallel codebase research on each, so we can plan implementation with full context.

This doc does not authorize implementation. Each section below will be filled in with a research brief before any story is opened per the BMAD Pre-Implementation Checklist in `CLAUDE.md`.

---

## Change 1 — Multi-stage personalization forms

**Current state:** One onboarding form exists today (`apps/web/src/components/onboarding/OnboardingFlow.tsx`, 20 questions → 9 "Learner DNA" sub-dimensions, stored in the `learner_dna` table, turned into `profile_text` via `dna_profile.py`, injected into pipeline system prompts via `fetch_learner_context_node` in `graph.py`).

**Requested change:** Add two more data-collection forms:
1. At **book upload** time.
2. At **lesson-building** time.

All three forms' collected data should feed into the system prompt used to personalize content generation for that user, alongside (not instead of) the existing Learner DNA profile.

**Needs clarification before planning:** what should the book-upload and lesson-build forms actually ask (e.g., prior knowledge of this specific book/topic? learning goal for this lesson? preferred pace?) — not yet specified by the user.

---

## Change 2 — Vector database → "contextual database"

**Current state:** Supabase Postgres + pgvector. Chunk embeddings stored inline on the `chunks` table (`text-embedding-3-small`, embed-once-at-ingestion). Retrieval used only for the Phase 2 tutor Q&A path via the `match_tutor_chunks` RPC (cosine similarity, scoped to chapter/book). Lesson generation itself is **not** RAG — the source chapter is known and passed directly (Core Architectural Principle #1 in `CLAUDE.md`).

**Requested change:** A suggestion was made to move from "vector database" to "contextual database." The user does not yet know what this means precisely and wants to understand the concept and its implications (including at scale) before deciding whether to pursue it. This is explicitly **not yet a decided direction** — research first.

---

## Change 3 — TTS vendor swap: Sarvam → 60db.ai

**Current state:** TTS fallback chain is Sarvam AI Bulbul v3 → Azure TTS → Browser Speech (never hard-fails). Implemented via a `TTSProvider` abstract interface (`apps/api/app/providers/base.py`), with `SarvamTTSProvider` (`apps/api/app/providers/tts/sarvam.py`) and `AzureTTSProvider` (`apps/api/app/providers/tts/azure.py`). Fallback orchestration lives in `_synthesize_with_fallback()` in `graph.py`. Config via `settings.sarvam_api_key`, `sarvam_voice_id`, `sarvam_narration_pace` in `config.py`.

**Requested change:** Replace Sarvam with **60db.ai** (https://60db.ai/) as the primary TTS provider. Need a full architecture plan for the switch — not just a drop-in swap, since Sarvam was chosen partly for Indian-language support and the fallback chain, cost ceiling ($3.00/lesson), and narration-pace tuning all currently assume Sarvam's specific API shape.

---

## Change 4 — Lesson duration model: switch to fixed 15/30/45 min

**Current state:** Lessons use a `tier` field (`T1`/`T2`/`T3`, DB-constrained in `lessons.tier`, single source of truth `VALID_TIERS` in `apps/api/app/schemas/lesson.py`). Tiers are framed by **content depth**, not duration directly: T1 = full-depth (covers secondary sub-topics), T2 = standard, T3 = critical-topics-only refresher (`_TIER_PROMPT_FRAMING` in `graph.py`), each with its own per-segment slide budget. Notably, the **frontend already labels these with implied durations** — `apps/web/src/types/learnerMode.ts` maps `deep→T1 (45 min)`, `balanced→T2 (30 min)`, `refresher→T3 (15 min)` — but the backend framing and prompts are depth-based, not time-based.

**Requested change:** Replace the current input model (framed around depth/session-type, e.g. "deep learning session" / "quick refresher") with exactly three fixed duration options: **15 min / 30 min / 45 min**. All system prompts and the user-facing lesson-build form should be redriven off duration rather than depth-framing. This is a reframing of the same 3-way choice already partially duration-labeled on the frontend, but requires the backend prompt framing, slide budgets, and narration length targets to actually be calibrated to a spoken-duration budget rather than a depth description.

---

## Process

1. ✅ Scope captured (this doc).
2. ✅ Parallel research pass — one brief per change above (4 agents), covering: current-state detail, exact files/components affected, technical considerations, risks/edge cases, open questions, rough effort. Findings below.
3. ✅ Findings appended to this doc.
4. ⏳ User reviews, answers open questions, decides which changes to pursue and in what order.
5. ⏳ Each approved change gets its own story file per the BMAD Pre-Implementation Checklist before any implementation begins.

---

# Research Findings (2026-09-19)

**Cross-cutting flag before the individual briefs:** Change 1 (lesson-build form) and Change 4 (duration tiers) both land on the exact same UI moment (`ModeSelection.tsx`) and the exact same request (`GenerateLessonRequest`/`generate_chapter_lesson`). **Plan these two together, not as independent workstreams** — otherwise two separate efforts will edit the same component/schema in conflicting ways.

---

## 1. Multi-stage personalization forms

**Headline finding:** This is not "add two screens." Every existing personalization primitive (`learner_dna`, `dna_context`) is architected as exactly one row per **user**, with no book/lesson dimension. Book-scoped and lesson-scoped answers need genuinely new storage, not new columns on `learner_dna`.

**Current state**
- Onboarding (already built): 20 questions (`apps/web/src/components/onboarding/questions.ts`) → 9 dimensions → `learner_dna` table (`UNIQUE(user_id)`) via EMA fusion (`dna_fusion.py`) → `profile_text` via GPT-4o-mini (`dna_profile.py`) + DPDP disclaimer.
- `assessment/service.py::get_dna_prompt_context` builds ONE free-text block (`dna_context`, no explicit length cap) from banded dimensions + allowlisted badges + profile_text.
- `fetch_learner_context_node` (`graph.py:1163`) fetches it once per lesson run, checkpointed so it can't change mid-generation. Read by exactly 3 prompt sites: `_planner_system_prompt` (1372), slide-generator prompt (1944), narration prompt (3705) — each does `if dna_context:` append.
- **Book upload today:** `UploadFlow.tsx` auto-uploads on file drop — **zero intermediate form**, by deliberate design (the team previously removed a tier-at-upload step to reduce friction, and the endpoint explicitly 422s if you send `tier` on upload: "a book has no tier"). Adding a form here **reverses a friction decision the team already made once** — flag back to product, don't assume it's free.
- **Lesson build today:** `ModeSelection.tsx` → `GenerateLessonRequest {tier, force}` — nothing else. This is where `lesson_id`/`book_id`/`chapter_id`/`user_id` are all created in one transaction — the cheap integration point.

**What would actually need to change**
- New storage: lesson-build context is cheap (piggyback on the existing `generate_chapter_lesson` INSERT — one new jsonb column or 1:1 table). Book-upload context is harder: `book_id` doesn't exist until the upload request completes, so answers either ride the same multipart POST (reopens the 422-tier precedent) or need a separate follow-up call (extra round trip + an "empty context" state every reader must handle).
- A new **merge function** (order/precedence + de-duplication of 3 sources) needs to be designed — doesn't exist today even for 1 source.
- An explicit **character/token budget with surfaced degradation** on the combined prompt block — none exists today; CLAUDE.md is explicit that silent truncation is never acceptable, and this is exactly that failure class.
- `_FAN_OUT_STATE_KEYS` allowlist (`graph.py:5694`) — narration is the one node that's `Send()`-dispatched; any new context key silently no-ops there unless explicitly added (this exact bug already happened once, with `tier`).
- Free-text fields (if any) need `max_length` + possibly the same prompt-injection guarding already applied to `narration_style` (which was moved off system-role for this exact reason).
- DPDP: onboarding data already carries a disclaimer; two new personal-context sources likely need the same consent treatment.

**Biggest open question:** *what do the two forms actually ask?* Not specified yet. Strawman options generated for you to react to — see full brief; roughly: book-upload = motivation/familiarity (2 questions), lesson-build = session goal / time available (which **overlaps directly with Change 4** — reinforces the "plan together" flag above).

**Effort:** M–L, realistically 3 separate stories (book-context, lesson-context, prompt-merge+budget). The merge/budget design is the part most likely to be underestimated.

**Recommendation:** Design the 3-source merge/precedence/budget rule first (everything else depends on it). Build lesson-build context first (cheap, and shares a story with Change 4). Build book-upload context last, after explicit product sign-off on reintroducing upload friction.

---

## 2. Vector database → "contextual database"

**Headline finding:** "Contextual database" is not an established product category. It almost certainly refers to **Anthropic's "Contextual Retrieval"** technique — an ingestion-time enrichment layered on top of a vector store, not a replacement database. And critically: **pgvector is used ONLY by the Phase 2 tutor Q&A path today** — lesson generation is explicitly not RAG (Core Architectural Principle #1) — so this change, if pursued, only affects tutor-answer relevance, not core content generation.

**What the technique actually is:** Before embedding each chunk, prepend a short (50–100 token) LLM-generated blurb situating that chunk within the book/chapter, then embed `context + chunk` instead of raw chunk text; optionally add BM25/keyword hybrid search + a reranking step. Anthropic reports ~49% fewer failed retrievals from contextual embeddings alone, ~67% combined with reranking.

**Cost shape:** One extra LLM call **per chunk, at ingestion time only** (not per lesson generation, not per tutor query) — this is a one-time cost, and cheap if done with prompt caching (cache the book/chapter once, vary only the chunk). Naive implementation (resending full context per chunk) could blow this up — must be prototyped and measured, not assumed.

**Two separable pieces:**
1. Contextual embeddings (prefix + re-embed) — small, additive, no new infra, no architecture-principle conflict if scoped to newly-ingested books only (no backfill of existing chunks — avoids touching the "never regenerate stored embeddings" rule).
2. Hybrid BM25 + reranking — new Postgres `tsvector`/GIN index, rewritten `match_tutor_chunks` RPC, new query-time reranker dependency + latency budget. Higher effort/risk, separable, should wait for (1)'s measured results.

**Reality check the research surfaced:** no evidence in the repo (no complaints, defect-register entries, or metrics) that tutor Q&A answer quality is currently a known problem. Also worth double-checking: the assumption that "we already track per-book ingestion cost" wasn't confirmed in code — only the per-lesson $3.00 ceiling is enforced; ingestion cost is observed via Langfuse but not gated.

**Open questions for you:**
- Is tutor Q&A quality actually a known pain point, or is this speculative/pitch-driven? This entirely determines urgency.
- Was a **specific vendor/product** pitched to you as "contextual database"? If so, name it — this analysis assumes the Anthropic technique because no established product goes by that name.
- Is there a broader intent to expand RAG beyond tutor Q&A (would require revisiting Core Architectural Principle #1 explicitly)?

**Recommendation:** Low urgency as stated — narrow blast radius, no confirmed pain point. If tutor Q&A quality *is* a known issue, a small "contextual embeddings on new books only" pilot is cheap and low-risk; hold off on hybrid search/reranking/backfill until that pilot's results are in.

---

## 3. TTS swap: Sarvam → 60db.ai

**Headline finding:** 60db.ai (docs.60db.ai) is real and well-documented — 30 TTS languages including all 12 major Indic languages, 1,000+ voices, ~150ms streaming latency, REST + Bearer auth, a speed parameter (0.5–2.0, same shape as Sarvam's `pace`), and **native word-level timestamps** (which neither Sarvam nor Azure currently provide — a real bonus, but should be scoped as a separate follow-on story, not bundled in). Pricing ($0.00002/char) is numerically identical to Sarvam's — the $3.00/lesson ceiling math is unaffected either way.

**The two real gaps found:**
1. **Indic TTS quality is unverified.** 60db's marketing claim ("#1 vs Sarvam") is a *speech-to-text* (Hindi WER) benchmark, not a TTS quality claim. Sarvam's TTS has documented strong Hindi phonological accuracy (handles retroflex/aspirated sounds correctly) — no equivalent public TTS-quality evidence exists yet for 60db. **Needs a native-speaker-reviewed A/B before any primary-tier commitment.**
2. **Data residency is undocumented.** No hosting-region/data-residency info found anywhere on 60db's site or docs. This repo already carries an open DPDP-adjacent compliance gap (D145, region drift), so adding an undocumented-residency vendor compounds an already-open issue. Needs a direct written answer from 60db, not an inference.

**What the swap actually touches:** new `SixtyDbTTSProvider` (clean fit against the existing `TTSProvider` interface — actually *simpler* than Sarvam's, since 60db's 5000-char limit removes most of the chunking machinery Sarvam needs at its 500-char limit); `config.py` new settings; `_synthesize_with_fallback()` reordering in `graph.py`; the frozen `AudioProvider` Literal in `apps/api/app/schemas/lesson.py` (needs a new value added — this is one of CLAUDE.md's 4 frozen contracts requiring a 4-developer-reviewed PR, cascades to `packages/shared/`); 30 files reference "sarvam" across `apps/api` (mostly tests — largely need fresh tests, not ported ones, since chunking behavior differs entirely). Also found, pre-existing and unrelated but adjacent: `.env.example` is stale — missing `SARVAM_*`/`AZURE_TTS_*` entirely, still lists deprecated ElevenLabs vars — worth fixing in the same PR.

**Precedent for full removal:** CLAUDE.md already documents ElevenLabs being fully removed and HeyGen deleted as dead code — but both happened only *after* the replacement was proven in production. Same sequencing recommended here.

**Open questions for you:**
- Fallback position: full replacement (60db → Azure → Browser), inserted ahead of Sarvam (60db → Sarvam → Azure → Browser) as an A/B tier, or evaluation-only with Sarvam still primary?
- Is Indic-language narration a hard current requirement, or is this migration aimed at an English-only/global segment? Changes how much the unresolved Hindi-TTS-quality gap should weigh.
- Is there a compliance/legal intake process that should formally ask 60db about data residency before any production text is sent to them?
- Appetite for a parallel A/B spend window vs. validating on a held-out non-production script set?

**Effort:** M–L. The provider code itself is small (arguably a simplification vs. Sarvam). What pushes it to M–L: the frozen-contract change, fresh test coverage, and the two gating non-code items (quality validation, data-residency answer) which aren't on your team's timeline to close.

**Recommendation:** Don't treat as a drop-in swap or a hard cutover. Add 60db as an **additional A/B tier ahead of Sarvam**, gate promotion to sole-primary on (a) a native-speaker Indic TTS quality review and (b) a written data-residency answer from 60db. Cost is a non-issue either way — pricing is essentially identical.

---

## 4. Lesson duration model: fixed 15/30/45 min

**Headline finding — this is the most important discovery of the whole research pass:** Duration (45/30/15 min) **already exists today only as a frontend label** (`apps/web/src/types/learnerMode.ts`) mapped onto the T1/T2/T3 depth tiers. There is **no backend mechanism that enforces or even estimates spoken duration at generation time.** Worse: `narration_generator_node` — the node that actually drives spoken length — runs in Phase 1, before tier is even applied, and **never reads the tier at all.** A "45-min" and a "15-min" lesson over the same chapter get word-for-word identical narration today, differing only in slide count. So this isn't a copy-editing change — it's a real architecture gap: tier/duration needs to be threaded into a node that currently has zero awareness of it.

**What exists vs. what's needed:**
- What exists: `_TIER_PROMPT_FRAMING` (depth wording, only read by `lesson_planner_node`), `_tier_slide_budget_per_segment` (slide *count* only), and a **post-hoc** word-count/duration estimate (`narration_words_per_minute=150`) that runs *after* narration is generated, purely to split slides across a timeline for the player — never fed forward as a generation target.
- What's missing: an actual **target word-count budget** (`duration_minutes × words-per-minute-at-narration-pace`) threaded into `narration_generator_node`'s prompt as an explicit constraint, replacing the current "no length target" instruction.
- Bonus finding: a real *measured* duration already exists downstream (`known_duration_ms`, from `tinytag` on the actual synthesized MP3, via `tts_node`) — this could become the ground-truth check for "did we hit the target," but nothing currently surfaces or acts on a mismatch.
- Three independent hardcoded copies of the 45/30/15 mapping already exist (frontend, `assessment/service.py::_TIER_MINUTES`, `config.py` Q&A-seconds comments) with no shared source of truth — worth consolidating regardless of what else changes.

**Design decision that matters most:** Keep the `T1`/`T2`/`T3` enum and DB column (lower risk — no migration, no frozen `packages/shared` contract change, since `tier` is already frozen there as an enum) but **reinterpret its semantics** from depth to duration, vs. introducing a brand-new `duration_minutes` field (requires an additive migration + the 4-developer-reviewed frozen-contract PR, for a benefit that's arguably cosmetic since the enum already maps 1:1 to fixed durations). **Recommend keeping the enum.**

**Real risks surfaced:**
- **Short-chapter edge case:** a thin chapter forced into a 45-min budget has no padding mechanism today, and padding conflicts with the pipeline's existing anti-fabrication guardrails. Needs an explicit product decision (cap available durations per chapter length? accept variance?), not a silent code path.
- Threading a new signal into `narration_generator_node`'s `Send()`-dispatch fan-out is the single highest-risk code change here — this exact fan-out pattern has a documented history of a nasty defect class (reducer-channel duplication) elsewhere in this file.
- Backward compatibility: existing lessons' `tier` values reflect the *old* depth semantics; a UI now showing "45 min" next to an old lesson would display a claim that was never actually enforced for it.
- `_TIER_QUIZ_COUNT_BAND` and the tutor Q&A phase-length table (`qa_phase_seconds`) are also tier-keyed and were tuned under the old depth framing — not automatically correct under duration framing; needs an explicit decision on whether to recalibrate them too or leave for later.
- Overshoot/undershoot handling must be an explicit, surfaced degradation (flag + accept variance within a stated band), never a silent hard truncation — this is exactly the failure class CLAUDE.md calls out by name as the project's own headline past defect.

**Open questions for you:**
- Acceptable variance around the target duration (±10%? more?) — determines whether enforcement is a hard constraint with regeneration-on-overshoot, or a soft target with logged variance.
- Keep the existing depth-framing language (`FULL-DEPTH`/`CRITICAL-TOPICS-ONLY`) as secondary guidance alongside the new duration budget, or drop it entirely? It currently does real, separate work (topic breadth) that a word-count budget alone doesn't replace.
- Should all 3 durations remain selectable for every chapter regardless of actual length, or should short chapters have some durations hidden/capped?
- Recalibrate quiz-count and Q&A-phase-length tables in the same effort, or leave them as a follow-up?
- Consolidate the 3 existing independent 45/30/15 hardcodes into one source of truth as part of this work, or treat as out of scope?

**Effort:** M–L, realistically a multi-story effort (each needing its own Story-First Gate entry). The framing-dict rewording is small; the real work is (1) threading duration into the Phase-1 fan-out state for the first time, (2) designing the word-budget-to-prompt-constraint math and its overshoot handling, (3) reconciling the 3 hardcoded duration tables.

**Recommendation:** Keep the `T1`/`T2`/`T3` enum, reinterpret its semantics. Thread a real word-count budget into `narration_generator_node` (the actually-missing piece). Use the existing measured `known_duration_ms` as the ground-truth check, with an explicit variance band rather than a hard cutoff. Plan this together with Change 1's lesson-build form, since both touch `ModeSelection.tsx` and `GenerateLessonRequest` in the same PR-worthy moment. Get the open questions above answered before writing the story.

---

## Answered so far (from clarifying questions)

- **60db.ai** confirmed as https://60db.ai/ — not a typo, real vendor (see brief above).
- **"Contextual database"** — user wants to understand the concept before deciding (see brief above); no specific vendor confirmed yet.
- **Scope for this pass:** research only, no code changes — respected throughout.

---

# Clarifications from `AI_Learning_Product_Final_Strategy.pdf` (added 2026-09-19)

This is the product strategy doc, not codebase-derived — it directly resolves several open questions the research briefs above flagged as unanswered.

## Resolves Change 1's biggest open question: what do the 3 forms ask?

The doc specifies exact field lists — these should now be treated as the answer, not a strawman:

**4.1 User Onboarding Form** (per-user — maps onto/extends the existing `learner_dna` onboarding, doesn't replace its cognitive/EQ questions, but adds explicit goal/preference fields not currently collected):
main learning goal & reason for using the product · purpose (exam/interview/project/job/academic/personal) · current knowledge level & difficult areas · preferred language, teaching style, tone, examples, pace · typical available learning time & motivation · career/academic goal.

**4.2 Book Understanding Form** (per-book — this is the "book upload" form from Change 1, though the doc doesn't specify it must sit at upload time itself, see note below):
why the user uploaded this book/PDF · what they want to achieve from it · complete book vs. selected chapters · important/difficult sections · deadline & expected depth · whether to follow the document exactly or reorganize it for learning.

**4.3 Chapter/Sub-Chapter Form** (per-lesson-build — explicitly required to be **short and optional**, and must NOT repeat info already captured at user/book level):
what the user wants to understand from this chapter · specific doubts/difficult topics · desired duration & depth · need for examples/formulas/diagrams/questions · topics to focus on or skip · expected outcome by end of lesson.

**Note on timing:** the strategy doc doesn't say the book form must appear at the exact moment of file upload — only that it's "book-level" info distinct from user-level and chapter-level. This gives room to resolve the research brief's flagged conflict (book form vs. the team's deliberate no-friction-at-upload decision): the book form could live on the book's post-upload landing/chapter-list page instead of blocking the upload action itself, satisfying the strategy doc's intent without reversing the earlier UX decision.

## Resolves Change 1's other open question: precedence/merge order

Section 5 of the strategy doc gives an explicit, ordered priority for the combined system prompt — this directly answers the research brief's flagged gap (no merge/precedence rule exists today):

**accuracy & safety → source content → system teaching rules → duration → user profile (onboarding) → book context → chapter instructions → user prompt → past performance (CES/history)**

This is a concrete design input for the merge function the research brief said needs to be built. It also confirms a **user prompt** is a distinct 4th input (a free-text per-lesson instruction, separate from the structured chapter form) — not previously scoped in Change 1's brief; add it to the design.

## Materially expands Change 4 (duration model)

The strategy doc confirms 15/30/45 min as the exact target (matches your original ask) but goes further than "recalibrate word count," which is what the codebase research scoped:

> "Important: duration should change more than slide count. It should change **depth, pace, examples, questions, personalisation, and skill-building**."

Concretely, per the doc's own duration table:
- **15 min:** key concepts/definitions/formulas, 1–2 examples, quick recall. Essential IQ checks, 1 reflection/confidence question, 1 short application.
- **30 min:** important concepts, examples, questions, connections, checkpoints. Multiple IQ questions, EQ checkpoints, 1 SQ activity, 1 research-thinking activity.
- **45 min:** detailed teaching, examples, interaction, personalisation, skill activities, revision. Full skill mapping, multiple cognitive activities, emotional reflection, communication practice, research-based questioning.

This means Change 4 is bigger than "thread a word-count budget into `narration_generator_node`" (which is still necessary and still correct as a first step per the codebase brief) — it also needs duration to drive **which activity types get generated at all** (skill-mapping breadth), not just how long the narration runs.

## Two things this doc surfaces that are NOT in your original 4-item list — flagging before scope creep happens

**1. A second, conflicting CES formula.** The strategy doc defines Cognitive Engagement Score as:
`CES = IQ×0.35 + EQ×0.25 + SQ×0.20 + Research×0.20` (skill-based, "a product hypothesis, not a validated final formula").

The **already-implemented** CES in this codebase (`CLAUDE.md` §CES Formula, actively enforced with a 2-min cooldown, fatigue caps, etc.) is:
`CES = quiz_accuracy×0.35 + teachback_score×0.25 + behavioral×0.20 + head_pose×0.12 + blink×0.08` (attention/webcam-based, MediaPipe-driven).

These are **two different metrics with the same name and coincidentally similar weight shapes**, measuring different things (skill categories vs. behavioral attention signals). This isn't something I'll reconcile without direction — it's a strategic question, not a research one.

**2. A "manual-first, prove-then-automate" build philosophy** ("Create a complete lesson manually... define the quality threshold... then automate the proven workflow. Recommended first test: build one complete 45-minute lesson manually"). This is a development *methodology* directive, at odds with the current state of the repo (a fully-built, already-automated 11-node LangGraph pipeline in production use per `CLAUDE.md`'s 10-week roadmap). It's unclear whether this is: (a) historical strategy from before the pipeline was built and now superseded, (b) a direction to prototype the *new* IQ/EQ/SQ/Research/CES-v2 additions manually before wiring them into the pipeline, or (c) something else.

**Open questions for you (new, from this doc):**
- Is the IQ/EQ/SQ/Research-skill framework and CES-v2 formula something you want scoped into this current change round, or is that a separate, later initiative? (It's not in your original 4-item list, but the strategy doc frames it as core to *why* duration should change depth/skill-mix, not just length — so Change 4 may be hard to fully spec without an answer here.)
- Is the "manual-first" methodology still the intended approach going forward, or superseded by the pipeline that already exists and is in the 10-week build roadmap?
- Should the two CES formulas be reconciled (e.g., fold skill-based signals into the existing formula as new weighted terms) or are they intentionally two separate metrics for two separate purposes?

### Decisions (2026-09-19)

- **IQ/EQ/SQ/Research + CES-v2 scope:** **Deferred — separate initiative, not part of this change round.** Change 4 (duration model) proceeds using only the codebase-research-derived plan (word-count budget threaded into `narration_generator_node`, per-tier framing) plus the strategy doc's depth/pace/examples/questions guidance *that doesn't depend on the new skill framework*. Skill-mapping-by-duration (§13 of the strategy doc) is explicitly out of scope for now.
- **CES conflict:** **Reconcile later, not now.** The existing behavioral CES (`quiz_accuracy/teachback/behavioral/head_pose/blink`) is authoritative and unchanged for this change round — it keeps driving live intervention logic (cooldowns, fatigue caps). The skill-based CES from the strategy doc is acknowledged as a future direction but not implemented or wired in now. Flagged here so it isn't silently forgotten or silently merged by a future contributor without a deliberate decision.
- **Manual-first methodology:** **Still intended, but scoped only to the deferred IQ/EQ/SQ/CES-v2 work** — i.e., when that separate initiative starts, prove it by hand (one manually-built 45-min lesson) before wiring it into the pipeline. It does **not** apply to the 4 changes in this doc — those proceed via the existing automated-pipeline development process (BMAD Story-First Gate, 6-agent review, etc.) as normal.

**Net effect on Changes 1–4:** all four remain scoped as originally defined. Change 1's form field lists and merge-precedence order are now locked in from the strategy doc (see above) — the "which fields" open question is resolved. Change 4 proceeds with word-count-budget calibration only; the fuller depth/skill-activity recalibration waits for the deferred IQ/EQ/SQ/CES-v2 initiative.

---

# Recommended Sequencing (2026-09-19)

Ranked by (a) how many open questions are already resolved, (b) dependency overlap, (c) risk/blast radius. This is a recommendation, not a commitment — none of this is built yet, and the BMAD Story-First Gate (`CLAUDE.md`) requires a committed, fully-ACed story file before any code, which the drafts below are not yet (marked DRAFT for a reason — see each one's "still needs your sign-off" line).

| Order | Work item | Why this position |
|---|---|---|
| 1 | **Change 4 + Change 1's lesson-build form, as ONE combined story** | Same UI moment (`ModeSelection.tsx`), same API call (`GenerateLessonRequest`/`generate_chapter_lesson`) — building separately guarantees a merge conflict. Most open questions already answered (form fields, merge precedence, keep-the-enum recommendation). Fixes a real, currently-shipping gap (durations are unenforced marketing labels). |
| 2 | **Change 1's book-upload form** | Depends on nothing from #1, but lower urgency and one open UX question (does it block upload or live on the post-upload page) — recommend answering that first, see draft below. |
| 3 | **Change 3 (TTS 60db)** | Fully plannable in parallel with #1/#2 (no shared files) — but before any code lands, two non-code prerequisites (Indic TTS quality review, written data-residency answer from 60db) should be kicked off now since they have unknown turnaround and don't block anything else. |
| 4 | **Change 2 (contextual retrieval)** | Correctly low-urgency per research — no confirmed pain point, narrow blast radius (tutor Q&A only). Next action is a product question ("is tutor Q&A quality actually a complaint?"), not a story. |

---

# Draft Story Outlines (NOT YET Story-First-Gate-ready — pending your sign-off on the flagged items)

These are working drafts to get your reaction, not committed stories. Per `CLAUDE.md`'s BMAD gate, a real story needs every AC locked and a complete Scale & Load section before the first commit — the items marked **⚠️ NEEDS YOUR CALL** below are exactly what's blocking that, and I've proposed a default with reasoning for each rather than leaving it blank.

## Draft Story A — Duration-driven generation + lesson-build context (combines Change 4 + Change 1's chapter form)

**Proposed scope:**
1. Keep `T1`/`T2`/`T3` enum and DB column as-is (no migration, no frozen `packages/shared` PR) — reinterpret semantics from depth to duration, per the codebase research's recommendation and the strategy doc's confirmation that 15/30/45 is the exact target.
2. Compute a target narration word-count budget (`duration_minutes × narration_words_per_minute(150) × sarvam_narration_pace(0.85)` — reuse the existing config constants, don't invent new ones) and thread it into `narration_generator_node`'s prompt for the first time (it currently has zero tier/duration awareness — the core finding of the research pass).
3. Add the Chapter/Sub-Chapter form fields from the strategy doc §4.3 (what to understand from this chapter, specific doubts, desired duration/depth, need for examples/formulas/diagrams/questions, topics to focus/skip, expected outcome) to the existing `ModeSelection.tsx` step, submitted together with the duration/tier selection into the same `generate_chapter_lesson` request — the strategy doc explicitly says this form should be **short and optional** and must not repeat onboarding/book-level info.
4. Use the existing measured `known_duration_ms` (real `tinytag`-based MP3 duration, already computed by `tts_node`) as the post-hoc ground-truth check against the target — log/flag variance, never silently truncate (binding CLAUDE.md rule).

**⚠️ NEEDS YOUR CALL — proposed defaults below, override if you disagree:**

- **Acceptable variance around target duration.** *Proposed default: ±15%, flagged (not regenerated) on breach for the first release.* Reasoning: LLM length control is inherently approximate; starting with a wider band avoids constant, costly regeneration while real data is collected on actual overshoot/undershoot patterns; tighten later once measured. A hard-regenerate-on-breach policy can be considered in a v2 once the false-positive rate at ±15% is known.
- **Depth-framing language (`_TIER_PROMPT_FRAMING`'s "FULL-DEPTH"/"CRITICAL-TOPICS-ONLY" text).** *Proposed default: keep, but demote to secondary guidance below the word-count budget.* Reasoning: research found this does real, separate work (topic breadth/selection) that a word-count constraint alone doesn't replace — dropping it risks a technically-on-time lesson that covers the wrong amount of material.
- **Short chapters forced into a 45-min budget.** *Proposed default: hide/disable durations whose word-count floor exceeds a conservative multiple (e.g. 3×) of the chapter's actual extractable content — computed once at structure-detection time, not per-request.* Reasoning: the pipeline already has anti-fabrication guardrails (`lesson_planner`'s degrade-not-fabricate pattern) that a padding-based approach would violate; capping available options is honest, padding is not.
- **Quiz count (`_TIER_QUIZ_COUNT_BAND`) and tutor Q&A phase length (`qa_phase_seconds`).** *Proposed default: leave unchanged in this story, revisit as an explicit follow-up.* Reasoning: keeps this story's blast radius contained to narration/duration; both were flagged by research as "tuned under old depth framing, not automatically correct under duration framing," but changing them isn't required to close the "durations are unenforced" gap, which is the core problem.
- **Consolidating the 3 existing hardcoded 45/30/15 tables** (frontend, `assessment/service.py::_TIER_MINUTES`, `config.py` qa-seconds comments). *Proposed default: do it in this story* — it's low-risk, small, and prevents a 4th independent copy being added by this very story's own word-count-budget constant.

**Known-risk item carried into implementation, not resolved by this draft:** threading a new signal into `narration_generator_node`'s `Send()`-dispatch fan-out state (`_FAN_OUT_STATE_KEYS`) is the single highest-risk code change here — this exact mechanism has a documented history of a serious defect class elsewhere in this file (reducer-channel duplication). The eventual story's tasks must include the same mutation-testing rigor `f2-5-dna-context-injection.md` used for its own fan-out-key change (a good template to copy from).

---

## Draft Story B — Book-upload personalization form (Change 1, book-level)

**⚠️ NEEDS YOUR CALL:**
- **Where does this form live?** *Proposed default: on the book's post-upload chapter-list/landing page (shown once, before the first chapter is generated), NOT blocking the upload action itself.* Reasoning: `UploadFlow.tsx` was deliberately redesigned to auto-upload with zero friction, and the endpoint explicitly 422s a `tier` field for the same reason. Reopening that decision at the literal upload step should require an explicit product call, not be a side effect of this story. The strategy doc's own framing (book-level info, distinct from chapter-level) doesn't actually require it at the upload moment itself.
- **Capture once, or editable later?** *Proposed default: capture once (immutable), no EMA/fusion.* Reasoning: unlike `learner_dna` (which deliberately evolves session-over-session), book-level intent ("why did you upload this book") is a point-in-time fact that doesn't need continuous re-fusion — simpler storage, no concurrency-handling needed.

**Scope:** strategy doc §4.2 field list (why uploaded, what to achieve, complete book vs. selected chapters, important/difficult sections, deadline/expected depth, follow-document-exactly vs. reorganize) → new `book_context` column/table keyed by `book_id` → merged into the system prompt per the strategy doc's precedence order (§5) alongside onboarding and chapter context.

**Depends on:** the merge/precedence function and character-budget design should be built once, shared by Draft Story A's chapter-context and this story's book-context (don't build two separate ad-hoc concatenation sites).

---

## Draft Story C — 60db.ai TTS integration (Change 3)

**Not blocked on any other draft here — can start in parallel.** Two things should start now, independent of any code:
1. **Native-speaker-reviewed Hindi/Indic TTS quality comparison** (60db vs. current Sarvam output) — not code work, has unknown turnaround, gates promotion to primary regardless of when the code is written.
2. **Written data-residency/hosting-region question sent to 60db** (sales/support) — same reasoning; this repo already carries an open DPDP-adjacent gap (D145) and shouldn't add a second undocumented one.

**Code scope once those are underway:** new `SixtyDbTTSProvider` (`apps/api/app/providers/tts/60db.py`) implementing the existing `TTSProvider` ABC; inserted as an **additional tier ahead of Sarvam** (`60db → Sarvam → Azure → Browser`) for a bounded A/B period — not a hard cutover, matching the "never hard-fails" chain philosophy and costing nothing extra on the happy path. Also fix the pre-existing, unrelated `.env.example` gap (missing `SARVAM_*`/`AZURE_TTS_*` entries, stale `ELEVENLABS_*`) in the same PR since it's the same file.

**⚠️ NEEDS YOUR CALL:** final fallback position (full replacement vs. permanent 4-tier chain vs. eventual Sarvam removal matching the ElevenLabs precedent) — explicitly deferred until the quality review and residency answer are in hand; don't decide this blind.

---

## Change 2 (contextual retrieval) — no draft story yet

Correctly not ready for a story. The one next action: **confirm whether tutor Q&A answer quality is an actual known complaint** (support tickets, low post-tutor CES, user feedback) — nothing in the repo evidences this today. If yes → small "contextual embeddings on new books only" pilot becomes Draft Story D. If no → deprioritize, no story needed right now.

---

**Next step from me, on your signal:** pick any "NEEDS YOUR CALL" item(s) above to confirm/override, or tell me to proceed with the proposed defaults as-is — at that point I'll promote the relevant draft into a real `docs/stories/{N}-{M}-{slug}.md` file meeting the full Story-First Gate bar (locked ACs + complete Scale & Load section), following the branch-creation and story-commit-first process `CLAUDE.md` mandates, before any implementation begins.

---

# File-Level Action Lists (2026-09-21, re-verified against current code — no relevant commits since 2026-09-19)

Correction found: the frozen tier migration's real filename is `supabase/migrations/20260714020000_add_lesson_tier.sql` (earlier notes had the timestamp slightly wrong — same file).

## A. Duration + chapter form

- `apps/api/app/schemas/lesson.py` — modify: add one shared `TIER_DURATION_MINUTES` map so nothing else hardcodes 45/30/15 again
- `apps/api/app/modules/content/pipeline/graph.py` — modify: `narration_generator_node` computes a real word budget (duration × words-per-minute × pace) and threads it into the prompt; trims+flags on overshoot, never silently cuts
- `apps/api/app/modules/assessment/service.py` — modify: point its own `_TIER_MINUTES` at the new shared map instead of duplicating it
- `apps/web/src/types/learnerMode.ts` — modify: comment-only update (durations become real, not just labels)
- `apps/api/app/modules/content/schemas.py` — modify: add new optional chapter-form fields to `GenerateLessonRequest`
- `supabase/migrations/<new>_add_lesson_generation_preferences.sql` — **create**: new nullable jsonb column on `lessons` (found: no existing column can carry these fields to the worker at all)
- `apps/api/app/modules/content/router.py` — modify: write the new fields into the same insert as tier/book/chapter
- `apps/api/app/workers/jobs/content_pipeline.py` — modify: fetch the new column, add to pipeline state
- `apps/web/src/components/dashboard/upload/ModeSelection.tsx` — modify: add the short optional form under the tier picker
- `apps/web/src/components/dashboard/books/ChapterGenerateControl.tsx` — modify: pass new form data through
- `apps/web/src/services/books.service.ts` — modify: extend request type + payload
- `packages/shared/*` (schema.json, lesson.ts) — **no change needed** (tier shape unchanged, only its meaning)
- New finding: a 4th hardcoded tier table exists (`tutor/service.py::qa_phase_seconds`) — governs live tutor Q&A length, not lesson duration, so no change needed but worth knowing it exists

## B. Book-upload form

- `supabase/migrations/<new>_book_context.sql` — **create**: new table/column keyed on `book_id`
- `apps/api/app/modules/content/schemas.py` — modify: new request/response models for the 6 fields
- `apps/api/app/modules/content/router.py` — modify: new `POST /books/{book_id}/context` endpoint, one-time only (409 on resubmit)
- new `apps/api/app/modules/content/context.py` (or similar) — **create**: `get_book_context_prompt_context()`, same pattern as the onboarding one
- `apps/api/app/modules/content/pipeline/graph.py` — modify: fetch it in `fetch_learner_context_node`, add to the Send() fan-out allowlist, merge into all 3 prompt sites
- new `apps/api/app/modules/content/pipeline/prompt_context.py` — **create**: one shared merge function (so this and the future chapter-context don't each duplicate string-concatenation logic)
- `apps/web/src/services/books.service.ts` — modify: new submit call
- new `apps/web/src/components/dashboard/books/BookContextForm.tsx` — **create**
- `apps/web/src/components/dashboard/books/BookDetail.tsx` — modify: show the form once, on the post-upload page (confirmed: upload flow itself needs zero changes)

## C. TTS 60db integration

- new `apps/api/app/providers/tts/sixtydb.py` — **create**: provider + the NDJSON-parsing/manual-WAV-wrapping logic (this is genuinely different from Sarvam/Azure, not a copy-paste)
- `apps/api/app/config.py` — modify: new settings (key, voice, model, sample rate restricted to 8000/16000/24000/48000, speed)
- `apps/api/app/modules/content/pipeline/graph.py` — modify: insert 60db as first tier in the fallback chain
- `apps/api/app/core/circuit_breaker.py` — modify: new provider key, no logic change
- `apps/api/app/schemas/lesson.py` + `packages/shared/*` — modify: add `"sixtydb"` to the frozen `AudioProvider` enum (needs the 4-dev-reviewed PR)
- `.env.example` — modify: add new vars (+ fix pre-existing unrelated gap: missing Sarvam/Azure vars, stale ElevenLabs entry)
- new test file — **create**: fresh tests, not adapted Sarvam ones (different limits/response shape)
- **Corrections found today** (from the vendor's own official CLI docs, more reliable than the earlier web research): response format is NDJSON not single-JSON (must parse line-by-line and hand-wrap the audio as WAV); real audio fidelity is capped around 8kHz regardless of requested sample rate (new quality risk to listen-test); **pricing parity with Sarvam is NOT actually confirmed** — 60db publishes no per-character price, only a wallet-credit billing model — earlier "identical cost" claim should be treated as unverified, not fact

## D. Contextual retrieval

- Still nothing to build — re-checked, still no evidence of a real tutor Q&A quality complaint anywhere in the repo
- Only next step: get a real product/support-side answer on whether this is an actual pain point
