# TransformED AI — Claude Code Project Guide

**PRD version:** 1.0 Final (10 June 2026) + Decisions Update (25 June 2026).
**Goal:** First paying student completes a full session by end of Week 10.

---

## Locked Technology Stack

| Layer | Choice | Hard constraint |
|-------|--------|-----------------|
| Backend | **FastAPI** (Python 3.12) | Modular monolith |
| Job queue | **ARQ** | Celery is BANNED |
| Frontend | **Next.js 14 + TypeScript + Tailwind** | App Router |
| DB | **Supabase Postgres + pgvector + JSONB** | |
| Storage | **Supabase Storage** | S3-compatible + CDN |
| Auth | **Supabase Auth + PyJWT local verify** | No remote auth call per request |
| Cache/Queue/PubSub | **Upstash Redis** | Moved off Railway with the Fly.io migration (2026-08-14, D158) — same instance backs `REDIS_URL` and `RATE_LIMIT_STORAGE_URL`. |
| AI orchestration | **LangGraph** (pin exact version — never auto-upgrade) | |
| LangGraph checkpointing | **Custom lesson_jobs table + MemorySaver** | PostgresSaver BANNED |
| Primary LLM | **OpenAI GPT-4o + GPT-4o-mini** (defaults — see model table) | Per-task allocation below |
| Alt LLM | **Claude Sonnet** (Phase 2 tutor Q&A, evaluation candidate) | |
| TTS | **Sarvam AI Bulbul v3 → Azure TTS → Browser Speech** | Fallback chain. ElevenLabs REMOVED. Was v2 until D148 (2026-09-04) — Sarvam deprecated v2 server-side. |
| Avatar | **No active vendor (D144, 2026-09-02)** | HeyGen was never wired into the pipeline (no node ever called it) — removed as dead code, not replaced. `LessonPackage.avatar_intro_url/avatar_static_url/avatar_outro_url` remain (nullable, vendor-agnostic) for a future implementation. |
| Image | **Gemini "Nano Banana" → GPT Image 2 → text-only** | DALL-E 3 DEAD (shut down May 2026). GPT Image 1 Mini migrated to GPT Image 2 2026-08-18 (D122) — 1 Mini itself retires 2026-12-01. **Imagen 4 Fast was DEAD as of 2026-08-17 (D121, FIXED-GUARDED) — replaced, not patched: Gemini 2.5/3.1 Flash Image ("Nano Banana") is now PRIMARY (Story 5-8b), GPT Image 2 is FALLBACK, `ImagenProvider` deleted.** Nano Banana costs more per image (~$0.067 vs GPT Image 2's ~$0.05) — a deliberate quality-over-cost choice, not an oversight. |
| Embeddings | **text-embedding-3-small** | Chunk content: embed at ingestion only, never regenerate. Phase 2 RAG tutor embeds student questions at query time — this is permitted. |
| OCR | **Tesseract** (in-container) | Azure Doc Intelligence removed |
| PDF | **pypdfium2 + pdftext + pdfplumber (table detection only) + docling (table markdown)** | PyMuPDF/fitz BANNED — AGPL-3.0. pypdfium2 (Apache 2.0) for text + rendering; pdftext (Apache 2.0) for font/layout metadata; pdfplumber (MIT) retained only to trigger docling on table pages |
| Attention | **MediaPipe Face Landmarker WASM** | WebGazer REJECTED |
| Lesson player | **Custom React audio-timeline state machine** | Reveal.js REJECTED. This is the FIRST-WATCH experience — never replace it with video; it is the only mode that carries quizzes, teach-back, CES interventions and jargon tooltips. |
| Video delivery | **Bunny Stream** — avatar clips (live) + compiled revision-mode lesson video (DECIDED 2026-07-28, not yet designed or implemented) | Revision/re-watch ONLY, never first watch. No video/ffmpeg code exists yet. Must be re-costed against the $3.00/lesson ceiling and kept off the ARQ critical path — see `docs/decisionupdate.md` §7b before implementing. |
| Realtime | **Native FastAPI WebSockets** | |
| Observability | **Langfuse + Sentry + OTel + PostHog** | Wire before feature work |
| Deploy | **Fly.io (`hie-api`, Mumbai/`bom`) + GitHub Actions** | `fly.toml`. Railway retired 2026-08-14 (D158) — `railway.toml` removed same day. One Fly app, two process groups (`api`, `worker`) sharing `apps/api/Dockerfile`; see ADR-001 for why they stay one app, not two. **Known residual gap: D145** — the live region list has been observed drifted to `sin` (Singapore), not `bom`, independent of `fly.toml`'s stated intent; registered, not fixed. |

## Per-Task Model Allocation

> **Model evaluation sprint: Sprint 1, Week 1.** Defaults below are conservative and confirmed working. Final model IDs locked before Sprint 2. **Never hardcode model strings** — always use `settings.llm_*` aliases from `config.py`. Swapping models is an env var change only.

| Task | Default (env var) | Evaluation candidates |
|------|-------------------|-----------------------|
| Lesson planning | `gpt-4o` (`LLM_LESSON_PLANNER`) | GPT-4o, Claude 3.5 Sonnet, o1-mini |
| Slide generation | `gpt-4o` (`LLM_SLIDE_GENERATOR`) | Same as above |
| Quiz, scoring, complexity, narration, jargon, interventions, Learner DNA | `gpt-4o-mini` (`LLM_MINI`) | GPT-4o-mini, Gemini 2.0 Flash |
| Tutor Q&A (Phase 2) | `gpt-4o` (`LLM_TUTOR`) | GPT-4o, Claude 3.5 Sonnet |

**Batch API rule:** Never use OpenAI or Google Batch API for pipeline nodes. Batch API has a 24-hour completion window — incompatible with real-time generation. All pipeline LLM calls use the synchronous (real-time) API endpoint.

## Repo Structure

```
transformED-corp/
├── apps/
│   ├── api/                    # FastAPI modular monolith
│   │   └── app/
│   │       ├── main.py         # App factory
│   │       ├── config.py       # pydantic-settings (all env vars)
│   │       ├── dependencies.py # JWT verify, redis, settings deps
│   │       ├── modules/        # auth | content | media | assessment | analytics | tutor | admin
│   │       │   └── content/
│   │       │       └── pipeline/
│   │       │           └── nodes/  # 11 LangGraph nodes
│   │       ├── providers/      # LLM | TTS | Image | Avatar (abstract interfaces)
│   │       ├── core/           # db | redis | retry | circuit_breaker | cost_tracker | websocket
│   │       └── workers/        # ARQ entry + content_pipeline job
│   └── web/                    # Next.js 14 App Router
│       └── src/
│           ├── app/            # Routes: (auth)/ | (app)/dashboard | /lesson/[id] | /upload
│           ├── features/       # player | attention | quiz | teachback | tutor | onboarding
│           ├── lib/            # supabase | websocket | api clients
│           └── components/ui/
├── packages/
│   └── shared/                 # FROZEN Week 1 — unblocks all 4 devs
│       ├── types/lesson.ts     # LessonPackage TS types
│       ├── types/ws.ts         # WebSocket discriminated union
│       └── lesson_package.schema.json
├── supabase/
│   └── migrations/             # Never modify applied migrations
└── .github/workflows/          # CI (lint+test) + deploy to Fly.io
```

## Core Architectural Principles (from PRD §5)

1. **Lesson generation ≠ RAG** — source chapter is known; no retrieval needed for generation
2. **Process once, reuse everywhere** — chunk embeddings generated at ingestion, never regenerated for stored content. Phase 2 RAG tutor embeds the student's question at query time — this is intentional and required.
3. **Modular monolith** — one FastAPI deploy; module names match future microservice names
4. **One discipline rule** — modules communicate only through service layer, never via direct DB access into another module's tables. Violating PRs are rejected.
5. **Provider abstraction everywhere** — no direct provider client calls in business logic
6. **Hierarchical document processing** — process Chapter → Section → Topic. Never full-book single call.
7. **Observability from commit one** — Langfuse + Sentry + OTel + PostHog wired before feature work
8. **Scale is a stated constraint, not an assumption** — every unit of work, budget, limit scope, query bound, inherited cap and check-then-act sequence is written down and re-derived, or the story is incomplete. Note that principle 6 above ("Never full-book single call") *is* a scale principle, it was written down first, and it was still violated — `structure_max_sections = 15` × `_get_section_body(max_chars=6000)` capped the LLM-visible window at ~90,000 characters, so a 1,151-page book yielded a lesson covering 4 % of it with nothing erroring. A principle with no machine behind it did not hold. That is why principle 8 ships with enforcement (story template section, sixth review layer, `tests/unit/test_unbounded_queries.py`) and principle 6 did not.

## The Scale Contract

**Full text — with the worked failure behind each question — is `docs/SCALE-CONTRACT.md`. Read it, do not re-derive it.** It is deliberately not duplicated here: two documents both claiming authority drift, and drift is a defect class this repo has already recorded (binding rule 5, and the Dev 1 tracker rule silently dropped by a merge on 2026-07-28).

**Every story carries a `## Scale & Load` section answering all six questions.** A story without it is incomplete and goes back. `"N/A"` is valid **only with a reason**; a bare `"N/A"` is a missing answer.

The six questions (`docs/SCALE-CONTRACT.md` §"The six questions"):

1. **What is ONE unit of work, and what is its range?** — min, typical, largest actually measured, and behaviour beyond it.
2. **Which budgets are FIXED while the input VARIES — and what happens past them?** — explicit error or explicit surfaced degradation. Silent truncation is never an acceptable answer.
3. **What is the SCOPE of every limit** — per user, per instance, or per deployment?
4. **Which reads and writes are UNBOUNDED?**
5. **Which caps were INHERITED from an earlier design, and have they been re-derived?**
6. **Is every check-then-act sequence safe under CONCURRENT requests?**

Enforcement, because prose does not hold: required story section → sixth mandatory review layer (**Scale & Load**, see the review gate below) → `tests/unit/test_unbounded_queries.py` in CI → binding rule 8 in `docs/DEFECT-REGISTER.md` for anything shipped knowingly.

Before merging, answer the one-line test: **"What input makes this silently wrong rather than loudly broken?"** The signature failure here was never slowness — it was a $0.00-over-budget lesson that reported success while covering 4 % of the book.

## Content Generation Pipeline (§9)

**Phase A — Book Ingestion** (once per book, ~2–5 min):
```
upload → store_pdf → extract_text → structure_detect → chunk → embed
```

**Phase B — Chapter Generation** (per chapter, student-triggered, ~5–15 min):

*Phase 1 — Economy nodes (all run in parallel, `settings.llm_mini`):*
```
summarise_segment × N   ← ALL must finish before Phase 2 starts
quiz_generator    × N
segment_complexity× N
jargon_extractor  × N
intervention_msgs × N
narration_script  × N
```

*Phase 2 — Premium nodes (sequential, start only after ALL Phase 1 segments complete):*
```
lesson_planner   ← input: segment summaries from Phase 1, NOT raw chapter text (5× token savings)
slide_generator  ← input: lesson outline from lesson_planner
```

*Phase 3 — Media nodes:*
```
tts_node         ← narration scripts → .mp3 per segment
image_generator  ← slide content → images
package_builder  ← assembles final JSONB lesson package
```

Checkpoint pattern: after each node, write `last_node` + `node_outputs` to `lesson_jobs`. On ARQ retry: read `last_node`, skip completed nodes. Never re-run completed LLM calls.

**Critical constraint:** `lesson_planner` receives segment summaries, not raw chapter text. Phase 1 must fully complete before Phase 2 starts. Violating this silently causes a 5× cost overrun.

## Tutor State Machine (7 states, §10)

States: IDLE → TEACHING → INTERVENING / CHECKING_IN → QUIZZING → TEACH_BACK → SESSION_END

Guard rules (MUST be enforced):
- CES monitoring ONLY active in TEACHING state
- 2-minute cooldown after any intervention (Redis TTL key)
- Max 3 distraction interventions per session
- Fatigue fires ONCE per session (Redis flag)
- NEVER interrupt mid-TEACH_BACK

Intervention messages are PRE-GENERATED at lesson build time (node 7). No GPT call at intervention time.

## CES Formula (§11 — weights are env vars, tunable post-calibration)

```
CES = quiz_accuracy×0.35 + teachback_score×0.25 + behavioral×0.20 + head_pose×0.12 + blink×0.08
```
Trigger: CES < 50 for 2 consecutive 5s windows → intervention.

When `teachback_score` is `None` (teach-back skipped — never gated, always allow Skip):
```
CES = quiz_accuracy×0.467 + behavioral×0.267 + head_pose×0.160 + blink×0.107
```
(Redistribute 0.25 weight proportionally across remaining 4 signals: each new weight = original ÷ 0.75)

## Failure Modes (§14)

- Exponential backoff: `wait = (2^attempt) + random(0,1)` — 3 attempts critical, 2 optional
- Retry on: 429, 500, 502, 503, 504. Never retry: 400, 401
- Circuit breaker: 5 failures/2min → open; 10min → half-open probe (state in Redis)
- Cost ceiling: $3.00/lesson — downshift to cheapest providers on breach, complete lesson, flag in admin
- TTS fallback chain: Sarvam Bulbul v3 → Azure TTS → Browser Speech — NEVER hard-fails

## Interface Contracts (frozen Week 1, §16)

Four contracts are frozen — changes require PR reviewed by all 4 developers:
1. `packages/shared/lesson_package.schema.json` + `packages/shared/types/lesson.ts`
2. `packages/shared/types/ws.ts` — WebSocket discriminated union
3. Assessment API (OpenAPI auto-generated from FastAPI)
4. `supabase/migrations/` — never modify applied migrations

Applied and frozen migrations (do not alter):
- `20260611000000_initial_schema.sql` — initial schema
- `20260625000000_chunks_inline_embedding.sql` — books table, inline embedding in chunks, lessons.book_id (applied 2026-06-25)

## Security (§18)

- JWT verified locally (PyJWT + SUPABASE_JWT_SECRET) — never remote call per request
- RLS on ALL Supabase tables — users read only their own data
- Raw webcam video NEVER leaves browser — only 5 derived numbers sent
- Attention capture requires explicit consent (modal + users.attention_consent flag)
- DPDP Act 2023 compliance — Learner DNA disclaimer required, no clinical claims
- **DPDP consent gap:** `users.attention_consent` boolean is insufficient — a `user_consents` audit table (columns: user_id, consent_type, policy_version, consented_at) is required before any attention data is collected. Sprint 2 priority.
- PDF security: parse user-uploaded PDFs in an isolated subprocess — calling PDF parsers (pypdfium2, pdfplumber, docling) directly in the main FastAPI process is a security risk with untrusted files. `fitz.open()` / PyMuPDF must never appear in the codebase at all (AGPL-3.0 banned)
- Kimi/Qwen deferred — China-hosted data residency risk

## Development Rules

- No Celery — ARQ only
- No PostgresSaver — custom lesson_jobs + MemorySaver
- No direct provider calls in business logic — go through providers/
- Pin LangGraph version — never auto-upgrade
- **A LangGraph node must return ONLY the state keys it owns — never `return {**state, ...}`.** Any channel annotated `Annotated[list, operator.add]` is a *concatenating reducer*: spreading the incoming state back out re-appends every accumulated value, so each node that does it **doubles** those channels. Four such nodes after a fan-in = 2⁴ = **16× duplication in a single clean run**, with no retry involved. Found in production 2026-07-28 (`quiz_questions` 45 → 720, `segment_summaries` 15 → 240) across 18 sites in the content pipeline, and independently in `modules/tutor/state_machine/graph.py`. Guarded by `tests/unit/test_node_return_shape.py` — a source-level scan that fails CI on any `**state` spread inside a node return. Applies to **every** StateGraph in the repo, not just the content pipeline.
- **A LangGraph `thread_id` must be unique per pipeline attempt.** `MemorySaver` is process-local and never evicted; reusing `thread_id=lesson_id` retains accumulated channels across retries and across the worker's lifetime. Resume must be rebuilt from the durable Supabase `node_outputs` checkpoints, **never** from MemorySaver. Note `router.py` pins `_job_id=f"pipeline:{lesson_id}"`, so `job_id` alone is *not* a uniquifier — `job_try` must be part of the token.
- Never import `fitz` / `pymupdf` / `pymupdf4llm` / `borb` — all AGPL-3.0; PDF extraction uses `pypdfium2` + `pdftext` instead
- PDF image extraction must render at **300 DPI** minimum (not 150 DPI) — use `page.render(scale=300/72)` in pypdfium2
- **Silent truncation is never acceptable.** Any fixed budget that meets a variable input — token window, section count, character limit, page count, byte size, timeout, retry count — must past its limit either raise an **explicit error** or emit an **explicit, surfaced degradation** (persisted on the record and visible to the caller/admin, not a `logger.warning` nobody reads). Naming the failure this catches: `structure_max_sections = 15` × `_get_section_body(max_chars=6000)` = ~90,000 characters of LLM-visible window regardless of input, i.e. ~36 pages at ~2,500 chars/page — a 1,151-page book was silently reduced to 3–4 % and reported success. The `$3.00/lesson` ceiling cannot catch this class: the failure is *cheap wrong*, not expensive. See `docs/SCALE-CONTRACT.md` Q2.
- **Every query is bounded, or carries a written justification.** Every Supabase read reachable from a request path must carry `.limit()` / `.range()`, use `count=` instead of materialising rows, or carry a `# BOUNDED:` comment stating why the row count is naturally bounded. Guarded by `tests/unit/test_unbounded_queries.py` (source scan, fails CI). Same rule for generated volume: **D50** — 300-DPI page rendering and image upload had no count cap at all and sat entirely outside `cost_tracker`. Related unbounded reads: the per-user concurrency gate `select("lesson_id")` over every `generating` row, and the limitless chapters→lessons embed returning 20 rows per chapter after 20 regenerations. See `docs/SCALE-CONTRACT.md` Q4.
- **Re-derive every inherited cap when the unit of work changes** — the 50 MB upload cap was sized when one upload was one lesson; unrevisited when the unit became a book, it rejects OpenStax Physics (1,671 pages, 251 MB) and Biology (1,475 pages, 382 MB), which are exactly the target textbooks. State the scope of each limit (per user / per instance / per deployment): **D52** — the rate limiter fell back to keying by IP, sharing one bucket across all authenticated users behind an egress IP; **D49** — `RATE_LIMIT_STORAGE_URL` defaults to `memory://`, multiplying every ceiling by replica count. And bound every check-then-act: **D45** — the `(chapter_id, tier)` idempotency pre-check has no UNIQUE constraint behind it, so concurrent duplicates both bill.
- No raw IQ/EQ/SQ claims — branded as "Learner DNA"
- No clinical scores shown to students — descriptive profile only
- Never gate lesson progress on teach-back score in MVP
- No teach-back timer — creates test anxiety
- No STT on the typed teach-back endpoint (`POST /assessment/teachback`) — `TeachbackSubmission` never carries a `transcript` field. Voice submissions use the dedicated audio endpoint `POST /assessment/teachback/{session_id}/{segment_id}/audio` (Story F2-4, lifted 2026-09-04).
- Chunk embeddings at ingestion only — never regenerate stored chunk embeddings. Phase 2 RAG tutor query-embedding IS allowed (embed the student question at query time).
- **Advisory CI bucket is NOT ambient noise.** CI runs two test buckets: gating (`tests/unit`, `tests/integration`) which blocks merge, and advisory (`continue-on-error: true`) which does not. A green checkmark does NOT mean the advisory bucket is clean. Before requesting review on any PR, pull the full CI run log and categorise every FAILED line: "was this failing on main before my branch?" If yes, note it in the PR description. If no, it is YOUR regression — fix it before review. Guard tests (`test_dunder_all_*`, `test_no_hardcoded_*`, `test_node_return_shape`, `test_unbounded_queries`) are ALWAYS your responsibility if your PR trips them: they enforce architectural invariants that protect the whole repo, not just the code you touched.
- **Guard-test check before touching any module.** When implementing any story that modifies an existing module, run `grep -rn "test_.*<module_name>\|test_no_hardcoded\|test_dunder_all" apps/api/tests/` before writing code. List the guard tests that reference that module. Run them locally before every push: `pytest tests/test_ces.py tests/unit/test_node_return_shape.py tests/unit/test_unbounded_queries.py -v`. If you intentionally need to extend a guard's allowlist (e.g., adding a public function to `__all__`), update the guard test in the same commit with a comment explaining why. Silent allowlist expansion is a process violation — it recreates the ratchet that spread `return {**state, ...}` from 1 site to 18.
- **When adding to `__all__` or adding float literals in a guarded module, the story AC list must explicitly include "existing guard tests for `<module>` pass."** A story that touches `ces.py`, `dna_fusion.py`, or any pipeline node file is incomplete if it does not name those modules' guard tests as acceptance criteria. The Story Quality agent should reject any story for a guarded module that omits this AC.
- **India-region migration DONE (2026-08-14, D158)** — API/ARQ moved off Railway to Fly.io (`bom`/Mumbai per `fly.toml`), Redis moved to Upstash in the same change. Topology: read `docs/decisions/ADR-001-india-region-migration-topology.md` for the reasoning (Langfuse is Cloud, not a deployed service; API and worker stay separate processes — job timeout 1800s vs a web request lifecycle). **Residual gap: D145** — the live region list has been observed as `sin` (Singapore), not `bom`, despite `fly.toml`'s stated intent; registered, not fixed, treat as an open DPDP/data-residency compliance item, not a closed migration.

## Defect Register — READ BEFORE FIXING ANYTHING

**`docs/DEFECT-REGISTER.md` is authoritative for known defects and the decisions about them.**
Consult it before opening a story; add to it before deferring anything.

Established by evidence on 2026-07-29, not by opinion:

- **9 of 11 pre-existing defects never worked for one minute.** Only 1 of 17 was a true
  regression. This codebase is not unstable — its verification never confirmed anything
  worked, so the same never-tested assumption resurfaces in a new subsystem and feels like
  recurrence.
- **24% of test assertions (567 of 2,328) describe a conversation with a mock**, not an
  outcome. A mock written by the consumer cannot disconfirm the consumer's belief.
- **Prose guidance does not hold.** Dev 1 wrote `DEV1-FIX-PLAN.md` and then deviated from it
  four times in a single day. Every deviation was caught by review, none by a machine.

### Binding rules

1. **Verification scope = CI scope.** Never scope an AC gate to "touched files" — CI checks
   repo-wide. That exact wording let 78 repo-wide ruff errors accumulate unseen.
2. **No test may assert only on a mock it constructed.** Assert an observable outcome, or
   mark it `# MOCK-CONTRACT:` and name the real-dependency test covering that path.
3. **Any `except SomeLib.Error` needs an executable premise assertion** proving the type
   hierarchy is what you think. Four separate defects were "we assumed a base class".
   Pattern to copy: `test_openai_exceptions_are_not_httpx_derived`.
4. **Any code naming a DB table/column must be validated against `supabase/migrations/`.**
   A Supabase mock has no Postgres catalog and cannot 42703.
5. **A documented limitation is NOT an accepted one.** Every `KNOWN LIMITATION` / `TODO` /
   `FIXME` must carry a `D-nn` register ID. A comment without an ID is a defect wearing a
   decision's clothes — that is exactly how the inert `structure_node` LLM call survived
   multiple sprints of review.
6. **"Matches existing accepted pattern" is not a justification.** It is the ratchet that
   took `return {**state, ...}` from one site to eighteen. Wrong at site 19 means wrong at
   site 1 — open a register entry instead.
7. **A fix without a guard is `FIXED-UNGUARDED`, not fixed.** Closure requires something in
   CI that fails if the defect returns.

## BMAD Pre-Implementation Checklist (Story-First Gate)

Before writing ANY code for a new story, complete ALL of the following in order — no exceptions:

1. **Create the story file** at `docs/stories/{N}-{M}-{story-slug}.md` with all ACs fully defined **and a `## Scale & Load` section answering the six questions** (`docs/SCALE-CONTRACT.md`). This is stated here, not only in the BMad template, because most stories in `docs/stories/` are hand-written and never open that template — a rule that lives only in a template a process does not use is not a rule.
2. **Commit ONLY the story file**: `git commit -m "docs(story-first): Story N-M — {title}"`
3. **Push the story-only commit** to remote: `git push origin <branch-name>`
4. **Verify** the story commit is the chronologically first commit on the branch
5. **Only then** begin the RED phase (write failing tests)

**NEVER** write implementation code in the same commit as the story file.
**NEVER** merge a PR where story and implementation share a commit.

## BMAD Code Review Gate (6-Agent Requirement)

Every PR requires a 6-agent adversarial code review via `/bmad-code-review` before merge.

The 6 required agent layers are:
1. **Story Quality** — all ACs testable, story complete before code
2. **Blind Hunter (Security)** — IDOR, injection, enumeration, DoS vectors
3. **Test Coverage** — every AC has a test, edge cases covered, no false confidence
4. **AC Completeness** — every AC maps to at least one explicit test assertion
5. **Process Integrity** — no LLM calls in wrong modules, no hardcoded models, no rule violations
6. **Scale & Load** — the six questions of `docs/SCALE-CONTRACT.the shipped `bmad-code-review` skill defines **4** built-in layers — Blind Hunter, Edge Case Hunter, Acceptance Auditor and Scale & Load Hunter — and their names do NOT map onto the six below: only Blind Hunter and Scale & Load appear in both lists. Story Quality, Test Coverage, AC Completeness and Process Integrity must be supplied by the invoking prompt. Check the skill before assuming a layer ran. The remaining layers are supplied by the invoking prompt. Six layers is the gate; three of them come from the skill, three you must ask for explicitly.)

**REJECT** any PR whose Senior Developer Review section lists fewer than 6 agent layers.
The Story Quality agent is the most critical — it catches missing ACs before they reach main.
The Scale & Load agent is the one that would have caught a green-merged Sprint 1, Sprint 2 and Learner Mode, all of which passed the other five while silently assuming a small PDF, one user, one instance.

## Build Roadmap (10 weeks, §22)

- **Week 1 (Sprint 0):** Infra setup + shared contracts frozen (THIS SPRINT)
- **Weeks 2–3 (Sprint 1):** Core pipeline + player skeleton
- **Weeks 4–5 (Sprint 2):** Full 11-node pipeline + integration → investor demo ready
- **Weeks 6–7 (Sprint 3):** MediaPipe + CES + full tutor state machine — **prerequisite:** migrate FastAPI/ARQ from Railway to India-region provider before real students join — **done 2026-08-14, Fly.io (D158); D145's region-list drift is the one open follow-up**
- **Weeks 8–9 (Sprint 4):** Load test + calibration + Razorpay + hardening
- **Week 10:** Launch — first paying student

## Team Ownership (§21)

| Dev | Owns |
|-----|------|
| Dev 1 | Infra, content pipeline, all 11 nodes, embeddings, provider abstraction, Langfuse |
| Dev 2 | Next.js, custom player, MediaPipe, quiz/teachback UI, dashboard, WebSocket client |
| Dev 3 | Quiz API, teachback scorer, CES formula, Learner DNA, session reports, analytics |
| Dev 4 | WebSocket handlers, JWT middleware, 7-state tutor, Redis buffer, interventions |

Anti-deadlock: after Week 1 schema freeze, each dev mocks the other's interface.

## Sprint Tracker Auto-Update Rule

> **Each developer has their own tracker with its own format. Follow the rule for the tracker whose task you are working on.**
>
> | Dev | Tracker | Format |
> |-----|---------|--------|
> | Dev 1 | `docs/dev1-tracker.md` | `- [ ]` / `- [x]` checkboxes |
> | Dev 2 | `docs/dev2-sprint-tracker.md` | see that file |
> | Dev 3 | `docs/dev3-assessment-tracker.md` | see that file |
> | Dev 4 | `docs/dev4-tracker.md` | `[Not Started]` / `[Partial]` / `[Completed]` labels |
>
> When editing this section, **add alongside — never replace another dev's rule.** (The Dev 1 rule below was silently dropped by an unrelated merge on 2026-07-28 and had to be restored.)

### Dev 1 — `docs/dev1-tracker.md`

Whenever you mark any task complete in `docs/dev1-tracker.md` — either because you just implemented it or the user confirms it is done — you MUST immediately, in the same response:

1. Change the task checkbox from `- [ ]` to `- [x]`
2. Append ` — ✓ YYYY-MM-DD` (today's date) to the task title line
3. Update the **Quick Status Dashboard** table at the top of the file (increment Done, decrement Not Started or Partial on the correct sprint row, and update Totals)
4. Update **Last updated** in the header to today's date

Do this without being asked. Never mark a task complete without also updating the dashboard. Never update the dashboard without also updating the header date.

### Dev 4 — `docs/dev4-tracker.md`

The Dev 4 tracker is `docs/dev4-tracker.md`. It uses three-state labels — `[Not Started]` / `[Partial]` / `[Completed]` — one per task, each tagged with a `<!-- CHECK:tag -->` marker, and is auto-maintained by `scripts/check_dev4_progress.py` (flips `[Not Started]`↔`[Completed]` by code presence; never downgrades a human-set `[Partial]`).

Whenever you finish implementing a task, or the user confirms one is done — either way, in the same response — you MUST:

1. Set the task's label to `[Completed]` and append ` ✅ YYYY-MM-DD (short note)` to the task title line. Use `[Partial]` (with a `⚠️ PARTIAL — <reason>` note) when the code exists but is untested, unmerged, or blocked on an external dependency.
2. Update the **Quick Status Dashboard** table at the top of the file (adjust Completed / Partial / Not Started on the correct sprint row, and update the **Total** row so the columns still sum to 39).
3. Update **Last updated** and **Overall status** in the header to today's date and the new counts.
4. Prefer running `python scripts/check_dev4_progress.py` to auto-apply label changes and print the authoritative per-sprint counts — then reconcile the dashboard/header to match its output. The script updates labels only, not the dashboard table.

Do this without being asked. Never mark a task complete without also updating the dashboard. Never update the dashboard without also updating the header date. Keep the dashboard totals consistent with the script's reported counts.

## Sprint Task Branch Rule

**Apply automatically — do not wait to be asked.**

When you begin implementing any sprint task from **any dev's tracker** (`docs/dev1-tracker.md`, `docs/dev2-sprint-tracker.md`, `docs/dev3-assessment-tracker.md`, `docs/dev4-tracker.md`), the very first action before any file edit must be to create a dedicated git branch.

### Branch naming

| Pattern | Example |
|---------|---------|
| `sprint{N}/s{N}-{M}-{slug}` | `sprint1/s1-2-pymupdf-extract` |
| `week10/w10-{M}-{slug}` | `week10/w10-1-prod-deploy` |

- `N` = sprint number (0–4)
- `M` = task number within the sprint
- `slug` = 2–4 word lowercase hyphenated summary of the task title (not the full title — just enough to identify it at a glance)

Examples:
- S1-2 "PyMuPDF text + image + layout extraction node" → `sprint1/s1-2-pymupdf-extract`
- S1-7 "Semantic chunking" → `sprint1/s1-7-semantic-chunking`
- S2-7 "`lesson_planner` node" → `sprint2/s2-7-lesson-planner`
- S0-9 "Langfuse wired globally" → `sprint0/s0-9-langfuse-global`

### Steps (execute in this order, no exceptions)

1. If there are uncommitted changes from a previous task, commit them to the current branch first.
2. Run: `git checkout main && git checkout -b <branch-name>`
   - If the branch already exists (resumed session): `git checkout <branch-name>` instead.
3. Announce the branch in the first line of your response — e.g., `Branch: sprint1/s1-2-pymupdf-extract created.`
4. Then begin implementation.

### One task, one branch

Every task gets its own branch based on `main`. Never stack a new task on top of the previous task's branch. When a task is marked complete and the next task begins, the next branch is created fresh from `main` at the start of implementation — again, without being asked.
