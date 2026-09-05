# Dev 3 — Assessment, CES & Learner DNA: Sprint Tracker

**Owner:** Dev 3 (tannmayygupta) · developer@cybersmithsecure.com
**Domain:** Quiz API · Teachback Scorer · CES Formula · Learner DNA · Session Reports · Analytics
**PRD version:** 1.0 Final (2026-06-10) — CLAUDE.md is the single source of truth
**Last updated:** 2026-09-05 (S4-31 CES weight tuning done; F2-1 Learner Context API + F2-2 Teachback score_source + F2-3 tier label verify done — Sprint 4 now 10/13)
**Sprint 0 status — COMPLETE + BMAD AUDITED 2026-06-27:** All 7 tasks done and merged to main. Post-merge BMAD quality audit passed (4 parallel agents — backend accuracy, test quality, Dev 2 integration, story completeness). Audit fixes applied on `sprint0/s0-8-audit-test-fixes`: analytics migration tests rewritten with table-scoped assertions (D→B rating), teachback scoring boundary tests added (score=89/90), CES weight @model_validator wired in config.py, onboarding content tests updated to new path, `jsonschema` added to dev deps. Story 3.7 closed. 120 unit tests pass.

> **Cross-team note (2026-07-13):** Dev 1's Sprint 1 backend content-ingestion pipeline merged to `main` (PR #72). Dev 1's Sprint 2 backend work (11 lesson-generation nodes, ending in `package_builder`) starts now — real `LessonPackage` JSONB is not available yet. Keep building/testing against existing mocks/fixtures until `package_builder` (S2-11) lands; do not stand up a parallel real-content path. Ping Dev 1 first if a mock is blocking progress. See `docs/master-tracker.md` for the full note.

---

## Quick Status Dashboard

| Sprint | Period | Tasks | Done | Partial | Not Started |
|--------|--------|-------|------|---------|-------------|
| Sprint 0 | Week 1 | 7 | 7 | 0 | 0 |
| Sprint 1 | Weeks 2–3 | 12 | 12 | 0 | 0 |
| Sprint 2 | Weeks 4–5 | 7 | 7 | 0 | 0 |
| Sprint 3 | Weeks 6–7 | 17 | 17 | 0 | 0 |
| Learner Mode Sprint | Ongoing | 4 | 4 | 0 | 0 |
| Demo Sprint | Aug 2026 | 7 | 7 | 0 | 0 |
| Sprint 4 | Weeks 8–9 | 13 | 10 | 1 | 2 |
| Bug Resolution Sprint | Sep 2026 | 1 | 1 | 0 | 0 |
| Week 10 | Launch | 2 | 0 | 0 | 2 |
| **Total** | | **70** | **64** | **1** | **5** |

Update this table each time a task is checked off below.

---

## Primary Files (Dev 3 Owns)

| File | Purpose |
|------|---------|
| `apps/api/app/modules/assessment/router.py` | All 5 assessment endpoints |
| `apps/api/app/modules/analytics/router.py` | Event ingestion + session summary |
| `apps/api/app/modules/assessment/service.py` | Business logic — quiz grading, teach-back scoring, session report, onboarding, Learner DNA |
| `apps/api/app/modules/analytics/service.py` | Analytics aggregation — event ingestion, session summary |
| `apps/api/app/modules/assessment/ces.py` | CES formula (5 weights as env vars, None redistribution) |
| `apps/api/app/modules/assessment/dna_fusion.py` | Learner DNA EMA fusion (9 dimensions, 0.7 retain × 0.3 new) |
| `apps/api/app/modules/assessment/dna_growth.py` | Growth delta per dimension per session (session_events write) |
| `apps/api/app/modules/assessment/dna_profile.py` | GPT-4o-mini profile text generation (DPDP disclaimer suffix) |
| `apps/api/app/modules/assessment/prompts.py` | Teach-back scoring prompt + onboarding profile prompt |
| `apps/api/app/modules/assessment/schemas.py` | Pydantic request/response models for all assessment endpoints |
| `apps/api/app/modules/assessment/onboarding_questions.py` | 20-question onboarding content + dimension mappings |
| `apps/api/app/core/posthog_client.py` | Fire-and-forget PostHog event wrapper (consent-gated) |

**Read-only dependencies (do not modify):**

| File | Why |
|------|-----|
| `packages/shared/types/lesson.ts` | `QuizQuestion`, `Segment`, `TeachbackPrompt` types — frozen |
| `packages/shared/types/ws.ts` | `AttentionSignalMessage` carries `quiz_accuracy`, `teachback_score` |
| `supabase/migrations/20260611000000_initial_schema.sql` | Initial DB schema — never modify applied migrations |
| `supabase/migrations/20260625000000_chunks_inline_embedding.sql` | Books table, inline embedding in chunks, lessons.book_id — applied 2026-06-25, never modify |
| `apps/api/app/providers/llm/openai.py` | GPT-4o-mini calls go through this — never call OpenAI directly |
| `apps/api/app/core/cost_tracker.py` | Track per-lesson cost — use for every LLM call |

---

## Interface Contracts (Frozen — 4-dev PR required to change)

1. **Assessment OpenAPI spec** — auto-generated from FastAPI routes. Adding new endpoints or changing existing signatures requires a PR reviewed by all 4 developers.
2. **`packages/shared/` types** — `LessonPackage`, `QuizQuestion`, `Segment` are read-only input for Dev 3.
3. **`packages/shared/types/ws.ts`** — `AttentionSignalMessage` is the source of `quiz_accuracy` + `teachback_score` fed to CES. Dev 4 owns the WebSocket layer.
4. **`supabase/migrations/`** — Schema is frozen. If a new column is needed, create a new migration file; never edit the applied one.

---

## Dependency Map (Dev 3 ↔ Other Devs)

```
Dev 1 (pipeline) ──► generates quiz/teachback_prompt in LessonPackage.segments
                     Dev 3 reads these at quiz/teachback submission time

Dev 4 (WebSocket) ──► sends AttentionSignalMessage every 5s (behavioral, head_pose, blink)
                      Dev 3 owns CES formula; Dev 4 triggers the computation

Dev 2 (frontend) ◄── consumes POST /assessment/quiz, POST /assessment/teachback,
                      GET /assessment/user/dna, GET /assessment/session/{id}/report
                      Dev 3 must keep OpenAPI spec stable for Dev 2

Dev 3 ──► writes ces_final to sessions table (Dev 4 reads this for state machine transitions)
Dev 3 ──► writes to learner_dna, quiz_attempts, teachback_attempts, onboarding_responses,
          session_events (all owned by Dev 3 exclusively)
```

---

## Technical Reference

### CES Formula (CLAUDE.md §11 — weights are env vars)

```
CES = quiz_accuracy   × CES_WEIGHT_QUIZ        (default 0.35)
    + teachback_score × CES_WEIGHT_TEACHBACK    (default 0.25)
    + behavioral      × CES_WEIGHT_BEHAVIORAL   (default 0.20)
    + head_pose_score × CES_WEIGHT_HEAD_POSE    (default 0.12)
    + blink_rate      × CES_WEIGHT_BLINK        (default 0.08)
```

- All inputs normalised to 0–1 before formula
- Output is 0–100 (multiply by 100)
- Trigger threshold: `CES_THRESHOLD=50.0` (env var)
- Dev 4 calls the CES update on each `AttentionSignalMessage`; Dev 3 owns the formula implementation
- CES computed per 5s window; stored in Redis as rolling average; final value written to `sessions.ces_final` on session end

**When `teachback_score` is `None`** (teach-back skipped — never gated, always allow Skip):
```
CES = quiz_accuracy   × 0.467  (= 0.35 ÷ 0.75)
    + behavioral      × 0.267  (= 0.20 ÷ 0.75)
    + head_pose_score × 0.160  (= 0.12 ÷ 0.75)
    + blink_rate      × 0.107  (= 0.08 ÷ 0.75)
```
Redistribute the 0.25 weight proportionally: `new_weight = original_weight ÷ 0.75`. All weights still sum to 1.0.

**CES env vars (config.py, tunable without redeploy):**
```
CES_WEIGHT_QUIZ=0.35
CES_WEIGHT_TEACHBACK=0.25
CES_WEIGHT_BEHAVIORAL=0.20
CES_WEIGHT_HEAD_POSE=0.12
CES_WEIGHT_BLINK=0.08
CES_THRESHOLD=50.0
```

### GPT-4o-mini Scope (Dev 3 always uses mini, never GPT-4o)

| Task | Model |
|------|-------|
| Teach-back rubric scoring | GPT-4o-mini via `LLM_MINI` config key |
| Learner DNA profile text generation | GPT-4o-mini |
| Re-assessment prompt text (after 10 sessions) | GPT-4o-mini |
| Onboarding scoring / dimension mapping | GPT-4o-mini |

Always call via `providers/llm/openai.py` — never instantiate `openai.AsyncOpenAI()` directly.
Always pass `lesson_id` to cost tracker on every LLM call.

### 5 Assessment Endpoints (frozen OpenAPI surface)

| Method | Path | Sprint | DB Write |
|--------|------|--------|----------|
| `POST` | `/api/assessment/quiz` | Sprint 1 | `quiz_attempts` |
| `POST` | `/api/assessment/teachback` | Sprint 1 | `teachback_attempts` |
| `GET` | `/api/assessment/session/{id}/report` | Sprint 2 | read-only |
| `GET` | `/api/assessment/user/dna` | Sprint 2 | read-only |
| `POST` | `/api/assessment/onboarding/submit` | Sprint 2 | `onboarding_responses`, `learner_dna` |

### 2 Analytics Endpoints

| Method | Path | Sprint | DB Write |
|--------|------|--------|----------|
| `POST` | `/api/analytics/events` | Sprint 2 | `session_events` |
| `GET` | `/api/analytics/session/{id}/summary` | Sprint 2 | read-only |

### DB Tables Owned by Dev 3

**`quiz_attempts`**
```sql
session_id       uuid   FK → sessions
segment_id       text   from LessonPackage.segments[].segment_id
question_id      text   from QuizQuestion.question_id
response_index   int    0-based index of selected option
is_correct       bool
response_time_ms int    captured client-side
attempt_number   int    DEFAULT 1
```

**`teachback_attempts`**
```sql
session_id          uuid   FK → sessions
segment_id          text
response_text       text   student's typed answer (NOT a transcript — no STT)
score               int    0–100  CHECK constraint in DB
feedback_praise     text   GPT-generated praise string
feedback_correction text   GPT-generated correction string
concepts_hit        text[] array of concept strings the student covered
concepts_missed     text[] array of concept strings the student missed
attempt_number      int    DEFAULT 1 (frontend allows 1 retry if score < 60)
```

**`learner_dna`** (one row per user, upsert pattern)
```sql
user_id               uuid  UNIQUE
-- Cognitive
pattern_recognition   numeric(5,2)   0–100
logical_deduction     numeric(5,2)   0–100
processing_speed      numeric(5,2)   0–100
-- Emotional
frustration_tolerance numeric(5,2)   0–100
persistence           numeric(5,2)   0–100
help_seeking          numeric(5,2)   0–100
-- Self-direction
goal_orientation      numeric(5,2)   0–100
curiosity_index       numeric(5,2)   0–100
study_independence    numeric(5,2)   0–100
-- Profile
badge_labels          text[]
profile_text          text   GPT-4o-mini generated, descriptive (no clinical claims)
session_count         int    incremented each session
last_updated          timestamptz
```

**`onboarding_responses`** (20 rows per user)
```sql
user_id          uuid
question_id      text   e.g. "cog_01", "emo_03", "sd_07"
response_value   int    Likert scale value (1–5)
response_time_ms int    captures reading speed as a signal
dimension_tag    text   CHECK IN ('cognitive', 'emotional', 'self_direction')
                        cognitive: 8 questions
                        emotional: 5 questions
                        self_direction: 7 questions
```

**`session_events`** (event log for analytics + PostHog)
```sql
session_id   uuid
event_type   text   e.g. 'tab_switch', 'retry_after_fail', 'jargon_hover',
                    'quiz_skip', 'teachback_skip', 'intervention_acknowledged',
                    'segment_complete', 'session_end'
payload      jsonb  event-specific data
```

### Redis Keys (Dev 3 reads/writes)

```
session:{session_id}:ces_window    → string  running CES per 5s window (float)
session:{session_id}:ces_history   → list    last N CES values (for consecutive check)
user:{user_id}:dna                 → string  JSON-serialised learner_dna (cache, TTL 1h)
user:{user_id}:onboarding_done     → string  "1" — set after onboarding submit completes
```

---

## Architecture Decisions Log

### 2026-06-25 — Schema Migration 2 + Independent Architecture Review

**Migration `20260625000000_chunks_inline_embedding.sql` applied and frozen:**
- `books` table created — fixes dangling `chapters.book_id` UUID that had no FK constraint
- `chapters.book_id` FK retrofitted with `ON DELETE CASCADE`
- `lessons.book_id` added (nullable, `ON DELETE SET NULL`) — lesson JSONB survives book deletion; `book_id IS NULL` = "Source book removed" badge in UI
- `chunks.embedding vector(1536)` moved inline — eliminates JOIN on every RAG query; HNSW index created
- `chunks.content TEXT` intentionally kept — industry standard; dropping it adds 200–300ms re-extraction per pipeline node call
- `embeddings` table dropped

**Key decisions affecting Dev 3's implementation:**
1. **CES redistribution** when `teachback_score` is `None` — redistribute 0.25 weight proportionally (formula in Technical Reference above). Dev 3 must implement this in `ces.py`.
2. **DPDP consent gap** — `users.attention_consent boolean` is insufficient; a `user_consents` audit table is required before any attention data is collected. Sprint 2 task added.
3. **Pipeline execution order** — `summarise_segment` runs in Phase 1 (economy, parallel) BEFORE `lesson_planner` (Phase 2, premium). Dev 3 reads `LessonPackage.segments[].quiz` only after Phase B fully completes.
4. **Railway region** — API stays on Railway through Sprint 3 (no India region). Dev 3 has no direct action, but analytics query latency will be US→India until Sprint 3 migration.
5. **Model evaluation** — Sprint 1 Week 1 will trial-test GPT-4o vs alternatives. All Dev 3 LLM calls use `settings.llm_mini` — no code change needed when models are finalised.

---

## Cross-Cutting Bugs Found During Re-Verification (2026-06-16)

These affect Dev 3's sprint work directly and must be fixed before Sprint 1:

| # | File | Bug | Impact | Fix |
|---|------|-----|--------|-----|
| 1 | `apps/api/pyproject.toml:22` | `openai>=1.30.0` too low — `beta.chat.completions.parse` needs `>=1.40.0` | **CRITICAL** — `complete_structured()` raises `AttributeError` on any install resolving to 1.30–1.39; silently breaks all teach-back scoring | Change to `"openai>=1.40.0"` |
| 2 | `apps/api/pyproject.toml:20` | `langgraph>=0.1.0` is a minimum version constraint, not a pin | **CRITICAL** — violates PRD §24 "never auto-upgrade"; breaking LangGraph API changes between minor versions | Change to `"langgraph==0.1.0"` (verify exact working version first) |
| 3 | `apps/api/pyproject.toml` | `posthog` Python SDK not in dependencies | Sprint 2 blocker — PostHog events task cannot be implemented | Add `"posthog>=3.0.0"` to dependencies |
| 4 | `apps/api/app/core/db.py:15` | Supabase client is synchronous (`from supabase import Client`) | Blocks async event loop in Sprint 1 routes under load — not a correctness bug but a performance regression | Change to `from supabase import AsyncClient, acreate_client` and make `get_supabase()` async |
| 5 | `apps/api/app/core/circuit_breaker.py:112` | `sentry_sdk.capture_message(extras={...})` — `extras` is not a valid kwarg | Sentry circuit-breaker context data silently dropped; `# type: ignore[call-arg]` suppresses the error | Use `sentry_sdk.push_scope()` pattern instead |

---

## Known Stub Discrepancies to Fix During Implementation

These exist in the current `router.py` stubs and **must be corrected** before going live:

| Location | Current Stub Issue | Correct Behaviour | PRD Rule |
|----------|--------------------|-------------------|----------|
| `TeachbackSubmission.transcript` | Field named `transcript` implies STT | Rename to `response_text` | "No STT in MVP — typed teach-back only" |
| `TeachbackSubmission.duration_seconds` | Implies a timer exists | Remove this field entirely | "No teach-back timer — creates test anxiety" |
| `QuizSubmission` | Missing `segment_id` | Add `segment_id: str` to body | `quiz_attempts` table requires it |
| `QuizSubmission.answers` | `list[dict[str, Any]]` (untyped) | Use typed `list[QuizAnswer]` with `question_id: str, response_index: int, response_time_ms: int` | DB schema requires typed writes |
| `LearnerDNA` response model | Returns `strengths`, `growth_areas`, `preferred_learning_style` — generic | Must align with 9 DB sub-dimensions, return descriptive `profile_text` not raw scores | "No clinical scores shown to students — descriptive only" |
| `OnboardingDiagnosticSubmission` | Has `subject: str`, `grade_level: str`; body field is `answers` | Frontend sends `{ responses: [{question_id, dimension, selected_index, selected_text}] }` — shape completely mismatches stub | Rewrite model to match frontend: `responses: list[OnboardingAnswer]` with `question_id`, `dimension`, `selected_index`, `selected_text` |
| `OnboardingDiagnosticSubmission` → DB write | Frontend `dimension` field uses values `'cognitive'`, `'emotional'`, `'self_direction'` | DB `onboarding_responses.dimension_tag` uses the same values — fine, just rename the field in the Pydantic model from `dimension` to `dimension_tag` when writing to DB | Mapping logic needed in service layer |

---

## Sprint 0 — Week 1 (Due: ~2026-06-13)

> **Goal:** Skeleton, stubs, and all DB tables in the migration. No business logic required.

- [x] **Assessment module stub in FastAPI — model violations fixed** — ✓ 2026-06-17
  - File: `apps/api/app/modules/assessment/router.py`
  - All 5 routes defined and returning 501 ✓
  - Router registered in `apps/api/app/main.py` at line 99 ✓
  - All 5 PRD model violations fixed ✓
    1. `TeachbackSubmission.transcript` → `response_text`; `duration_seconds` removed ✓
    2. `LearnerDNA` rewritten: `badge_labels`, `profile_text`, `session_count`, `reassessment_due`, `last_updated` — matches DB schema ✓
    3. `QuizSubmission.segment_id: str` added ✓
    4. `QuizAnswer` typed model created (`question_id`, `response_index`, `response_time_ms`) ✓
    5. `OnboardingAnswer` typed model created; `OnboardingDiagnosticSubmission` uses `responses: list[OnboardingAnswer]`; `subject`/`grade_level` removed ✓
  - **BMAD retroactive (2026-06-26):**
    - Story file: `docs/stories/3-1-assessment-module-stub.md` — 17 ACs, all verified ✓
    - Tests: `apps/api/tests/test_assessment_stub_contracts.py` — 10 tests, 10 PASSED ✓
    - Code review fix: endpoint summary "transcript" wording → "typed teach-back response" ✓
    - Branch: `dev3-sprint0-task1`
  - **REMAINING:** OpenAPI spec has not been run or shared with Dev 2 ✗
  - **Action needed:** Run server → share `/openapi.json` with Dev 2

- [x] **DB tables: `quiz_attempts`, `teachback_attempts`, `learner_dna`** — ✓ 2026-06-11, migration applied to Supabase ✓ 2026-06-17
  - Confirmed present in `supabase/migrations/20260611000000_initial_schema.sql` (lines 188–240) ✓
  - RLS policies with hierarchical ownership applied for all 3 tables ✓
  - Migration applied to Supabase project `transformed-dev` (`kxhgvwopdszclfyrrkqm`) on 2026-06-17 ✓
  - **AC:** Tables exist in Supabase dashboard; RLS enabled ✓
  - **BMAD retroactive (2026-06-26):**
    - Story file: `docs/stories/3-2-db-tables-assessment.md` — 15 ACs, all verified ✓
    - Tests: `apps/api/tests/test_migration_assessment_schema.py` — 42 tests, 42 PASSED ✓
    - Code review: Approved ✓
    - Branch: `dev3-sprint0-task2`

- [x] **DB tables: `onboarding_responses`, `session_events`** — ✓ 2026-06-11, migration applied to Supabase ✓ 2026-06-17
  - Confirmed present in applied migration (lines 247–269) ✓
  - RLS policies applied for both tables ✓
  - Migration applied to Supabase project `transformed-dev` (`kxhgvwopdszclfyrrkqm`) on 2026-06-17 ✓
  - **AC:** Tables exist; RLS enabled ✓
  - **BMAD retroactive (2026-06-26):**
    - Story file: `docs/stories/3-3-db-tables-analytics.md` — 19 ACs, all verified ✓
    - Tests: `apps/api/tests/test_migration_analytics_schema.py` — 12 tests, 12 PASSED ✓ (rewritten 2026-06-27 — table-scoped assertions, added user_id_fk, session_id_fk, per-table RLS regex checks)
    - Code review finding (medium): no `UNIQUE(user_id, question_id)` on `onboarding_responses` — duplicate answers possible at DB level; add UNIQUE constraint in Sprint 2 migration
    - Branch: `dev3-sprint0-task3`

- [x] **20-question onboarding content written + reviewed** — ✓ 2026-06-11
  - 8 cognitive questions (id: `c1`–`c8`) ✓
  - 5 emotional questions (id: `e1`–`e5`) ✓
  - 7 self-direction questions (id: `s1`–`s7`) ✓
  - All are 4-option choice questions, no open-ended ✓
  - No IQ/EQ/SQ language; DPDP-safe wording confirmed ✓
  - Content lives in `apps/web/src/app/(app)/onboarding/page.tsx` lines 21–47 (frontend only)
  - **NOTE:** ID format mismatch — frontend uses `c1`–`c8`, tracker shows `cog_01` format; DB `dimension_tag` column has no format CHECK; service-layer mapping deferred to Sprint 2
  - **NOTE:** `(app)/onboarding` route was missing from main; restored in Task 4 branch — Dev 2 must review integration during Sprint 2 auth→onboarding flow PR
  - **AC:** Questions reviewed, no IQ/EQ/SQ language, DPDP-safe wording ✓
  - **BMAD retroactive (2026-06-26):**
    - Story file: `docs/stories/3-4-onboarding-diagnostic-content.md` — 10 ACs, all verified ✓
    - Tests: `apps/api/tests/test_onboarding_content.py` — 13 tests, 13 PASSED ✓
    - Code review: Approved ✓
    - Branch: `dev3-sprint0-task4`

- [x] **GPT-4o-mini provider wired for scoring** — ✓ 2026-06-26
  - `apps/api/app/providers/llm/openai.py` exists with `complete()` and `complete_structured()` ✓
  - `config.py` line 79: `llm_mini: str = Field(default="gpt-4o-mini")` ✓
  - `gpt-4o-mini` pricing in `_COST_PER_1K` ✓
  - `openai>=1.40.0` in `pyproject.toml` — fixes `beta.chat.completions.parse()` requirement ✓
  - `langgraph==1.2.6` pinned exactly in `pyproject.toml` — satisfies PRD §24 ✓
  - `apps/api/tests/__init__.py` created (empty package init) ✓
  - `apps/api/tests/test_llm_provider_smoke.py` created — integration smoke tests for `complete()` and `complete_structured()` ✓
  - `apps/api/tests/test_suite_health.py` created — unit sentinel so `pytest -m unit` exits 0 ✓
  - Model name sourced from `Settings.model_fields["llm_mini"].default` — no hardcoded `"gpt-4o-mini"` in test file ✓
  - `pytest -m unit` exits 0 ✓; smoke module skips (not fails) when OPENAI_API_KEY absent ✓
  - AC 4.3 confirmed 2026-06-26 — `pytest -m integration` → 2 PASSED, exit 0 (openai==2.29.0) ✓
  - pyproject.toml BOM + smart-quote issue fixed; pre-import added to test fixture; `ignore::ResourceWarning` added
  - Story 3.5 at `docs/stories/3-5-gpt4omini-provider-wired.md` — status: **done**

- [x] **Teach-back scoring prompt v1 written + tested in isolation** — ✓ 2026-06-26
  - `apps/api/app/modules/assessment/prompts.py` created ✓
  - `TeachbackScoreResult` Pydantic model: 5 fields (`score int ge=0 le=100`, `praise`, `correction`, `concepts_hit`, `concepts_missed`) ✓
  - `@model_validator` enforces `correction=""` when `score >= 90` at the Pydantic layer ✓
  - Rubric: Accuracy (40%) + Completeness (35%) + Clarity (25%) in system prompt ✓
  - `score_teachback()` calls `provider.complete_structured()` with `settings.llm_mini` — no hardcoded model string ✓
  - No direct `AsyncOpenAI()` import — TYPE_CHECKING guard only ✓
  - `lesson_id` NOT in `score_teachback()` signature — provider holds it at constructor level ✓
  - 23 unit tests, all PASSING (`pytest -m unit` exits 0) ✓ (2 boundary tests added 2026-06-27: score=89 retains correction, score=90 clears correction)
  - All review BLOCKER + IMP items resolved before push ✓
  - Story file: `docs/stories/3-6-teachback-scoring-prompt.md` — status: done ✓
  - Branch: `dev3-sprint0-task6`, pushed to origin ✓

- [x] **OpenAPI spec published for all 5 assessment endpoints** — ✓ 2026-06-26
  - Export script created: `apps/api/scripts/export_openapi.py` — no env vars, Redis, or DB required ✓
  - 14 spec-verification tests, all PASSING: `apps/api/tests/test_openapi_spec.py` ✓
  - Spec generated and committed: `docs/openapi-assessment.json` (5 paths, 11 schemas) ✓
  - All 5 endpoints confirmed present with correct HTTP methods ✓
  - `TeachbackSubmission` has `response_text` — NO `transcript` field ✓
  - `OnboardingDiagnosticSubmission` has `responses: list[OnboardingAnswer]` — NO `subject`/`grade_level` ✓
  - No `duration_seconds` anywhere in spec ✓
  - `LearnerDNA` has `badge_labels` + `profile_text` (descriptive, no raw numeric scores) ✓
  - `docs/dev2-assessment-api-handoff.md` shared with Dev 2 via GitHub (branch dev3-sprint0-task7) ✓
  - **DEV 2 SIGN-OFF RECEIVED 2026-06-26** — all 9 checklist items confirmed ✓
  - **Post-review fix (2026-06-26):** Onboarding page route group corrected per Dev 2 feedback:
    - Moved `(app)/onboarding/page.tsx` → `onboarding/page.tsx` (root-level, URL unchanged)
    - Import fixed: `{apiClient}` from non-existent module → `{api}` named export from `lib/api`
    - API call path fixed: `/api/assessment/...` → `assessment/...` (removes double `/api` with baseURL)
    - Branch: `sprint0/s0-7-onboarding-fix` — pushed, 14/14 spec tests still passing ✓
  - **Dev 2 PR #13 pnpm conflict resolved (2026-06-26):** Merged `origin/main` into `dev2/sprint-1`,
    resolved `pnpm-workspace.yaml` (took concrete bool values over placeholders),
    regenerated `pnpm-lock.yaml` via `pnpm install`, pushed to `origin/dev2/sprint-1` ✓
  - **BMAD:**
    - Story 3.7: `docs/stories/3-7-sprint0-onboarding-route-fix.md` ✓
    - Branch: `sprint0/s0-7-onboarding-fix`

---

## Sprint 1 — Weeks 2–3 (Due: ~2026-06-27)

> **Goal:** Quiz and teach-back endpoints live with DB writes. Assessment data flowing end-to-end.

- [x] **`POST /api/assessment/quiz` endpoint live** — ✓ 2026-07-01
  - BMAD process COMPLETE on branch `sprint1/s1-1-quiz-endpoint-v2`:
    - Story 3-8 amended first (story-first) ✓
    - RED: 5 failing tests written before implementation ✓
    - GREEN + REFACTOR: 28/28 unit tests pass ✓
    - 5-agent adversarial code review: 3 BLOCKERs resolved ✓
  - Merged to main via PR #44 on 2026-07-01 ✓
  - Final implementation: `grade_quiz()` in `service.py` — session/IDOR validation, bulk insert to `quiz_attempts`, CES ×100 scale, per-question feedback ✓

- [x] **MCQ scoring + response time capture** — ✓ 2026-07-01
  - `response_time_ms: int = Field(default=0, ge=0)` in `QuizAnswer` schema ✓
  - `response_time_ms` written to `quiz_attempts` on every submission ✓
  - Merged to main via PR #44 (same as S1-1) ✓

- [x] **`POST /api/assessment/teachback` live** — ✓ 2026-06-27
  - Story 3-9: `docs/stories/3-9-teachback-endpoint-live.md` — story-first before implementation ✓
  - `grade_teachback()` in `service.py`: session/IDOR validation, `score_teachback()` call, `teachback_attempts` insert ✓
  - `TeachbackSubmission` + `TeachbackResult` moved from `router.py` → `schemas.py` (eliminates circular import risk) ✓
  - Router `submit_teachback()` lazy-imports `grade_teachback` (same pattern as `submit_quiz`) ✓
  - 19 new unit tests — all PASSING; 190 total pass ✓
  - Branch: `sprint1/s1-3-teachback-endpoint`
  - **Note:** PR for `sprint1/s1-8-1-quiz-blockers` (13 BMAD BLOCKERs resolved) still open — merge before S1-3 lands on main

- [x] **GPT-4o-mini rubric scoring (accuracy / completeness / clarity)** — ✓ 2026-06-27
  - `TeachbackScoreResult` extended with `accuracy_score`, `completeness_score`, `clarity_score` sub-scores ✓
  - `TEACHBACK_SYSTEM_PROMPT` updated to request all 3 sub-scores in JSON output ✓
  - `rubric_scores` in `TeachbackResult` = `{"accuracy": str, "completeness": str, "clarity": str}` — descriptive labels (Exceptional/Proficient/Developing/Emerging/Beginning) ✓ **B5 fix applied 2026-07-01 via Story 3-14**
  - `score_teachback()` calls `provider.complete_structured()` with `settings.llm_mini` ✓
  - `OpenAILLMProvider(lesson_id=lesson_id)` constructed so cost tracks against the lesson ✓
  - Existing prompt tests updated for new 8-field model (was `test_model_has_five_fields`) ✓

- [x] **Praise + correction feedback response format** — ✓ 2026-06-27
  - `feedback = praise` when `score >= 90` (correction is empty per `@model_validator`) ✓
  - `feedback = f"{praise}\n\n{correction}"` when `score < 90` ✓
  - `test_feedback_high_score_praise_only` + `test_feedback_low_score_praise_and_correction` PASSING ✓

- [x] **`quiz_attempts` + `teachback_attempts` DB writes working** — ✓ 2026-07-01
  - `teachback_attempts`: merged to main via PR #20 ✓
    - `grade_teachback()` inserts with all required fields, `attempt_number` increments via SELECT COUNT ✓
  - `quiz_attempts`: merged to main via PR #44 (S1-1) ✓
    - `grade_quiz()` bulk-insert with error check, 409/500 branching (PR #48), dynamic attempt_number (PR #47) ✓
  - Both endpoints now have: session ownership validation, IDOR guard, 409 duplicate detection, 502 on scoring failure ✓

- [x] **SEC-006 quiz oracle fix: grade_quiz ownership returns HTTP 404** — ✓ 2026-07-01
  - Story 3-10: `docs/stories/3-10-quiz-security-hardening.md` ✓
  - `grade_quiz()` wrong-user check: 403 → 404 — prevents session-existence enumeration ✓
  - Comment explains security rationale: "Attacker must not distinguish belongs-to-someone-else from doesn't-exist" ✓
  - Merged to main via PR #43 on 2026-07-01 ✓
  - Branch: `sprint1/s1-10-quiz-security-hardening`

- [x] **SEC-006 + SEC-007 teachback hardening: oracle fix + 502 on scoring failure** — ✓ 2026-07-01
  - Story 3-11: `docs/stories/3-11-teachback-security-hardening.md` ✓
  - `grade_teachback()` wrong-user check: 403 → 404 (same oracle pattern as S1-10) ✓
  - `score_teachback()` wrapped in `try/except`: any exception → HTTP 502 Bad Gateway ✓
  - `result is None` guard added → HTTP 502 (double safety in case provider returns None) ✓
  - SEC-007 prompt injection: `<student_response>` XML wrapper + HTML entity escaping in `prompts.py` ✓
  - Merged to main via PR #46 on 2026-07-01 ✓
  - Branch: `sprint1/s1-11-teachback-security-hardening`

- [x] **Dynamic attempt_number via SELECT COUNT for quiz** — ✓ 2026-07-01
  - Story 3-12: `docs/stories/3-12-quiz-attempt-number-fix.md` ✓
  - Removed hardcoded `attempt_number: int = 1` param from `grade_quiz()` signature ✓
  - Added Step 6 SELECT COUNT from `quiz_attempts` to compute `attempt_number` dynamically ✓
  - Parity with `grade_teachback()` which already had SELECT COUNT pattern ✓
  - Merged to main via PR #47 on 2026-07-01 ✓
  - Branch: `sprint1/s1-12-quiz-attempt-number-fix`

- [x] **409 Conflict on duplicate quiz/teachback attempt** — ✓ 2026-07-01
  - Story 3-13: `docs/stories/3-13-unique-attempt-constraints.md` ✓
  - Insert error in `grade_quiz()`: inspect error string for "duplicate"/"unique" → 409; else → 500 ✓
  - Insert error in `grade_teachback()`: same branching pattern ✓
  - DB migration `20260630000000_unique_attempt_constraints.sql` applied to Supabase ✓
  - Merged to main via PR #48 on 2026-07-01 ✓
  - Branch: `sprint1/s1-13-unique-attempt-constraints`

- [x] **B5/B6 BMAD Blocker Fixes: rubric labels + quiz security tests** — ✓ 2026-07-01
  - Story 3-14: `docs/stories/3-14-teachback-rubric-labels.md` — B5 rubric_scores descriptive labels ✓
  - `_score_to_label()` helper added to `service.py`: 90+=Exceptional, 75-89=Proficient, 60-74=Developing, 40-59=Emerging, 0-39=Beginning ✓
  - `TeachbackResult.rubric_scores`: `dict[str, float]` → `dict[str, str]` — never expose raw floats to students ✓
  - 2 new tests: `test_rubric_scores_are_descriptive_labels` + `test_score_to_label_boundaries` ✓
  - B6: 6 new quiz security tests (SEC-008 response_index bounds, SEC-009 log sanitization, TQ-007 duplicate question_id) ✓
  - 4-call mock fix in `_build_supabase_with_insert_error()` for 409/500 paths ✓
  - Branch: `dev3-sprint1-blocker-fixes`
  - Stories 3-10..3-13 marked done with 5-agent reviews ✓

- [x] **BMAD Process Documentation + Story Status Corrections** — ✓ 2026-06-29
  - Story 3-15: `docs/stories/3-15-bmad-process-docs.md` — documentation-only story ✓
  - `CLAUDE.md` updated: BMAD Pre-Implementation Checklist section added (AC 1) ✓
  - `CLAUDE.md` updated: 5-agent code review gate documented (AC 2) ✓
  - `docs/stories/3-8-quiz-endpoint-live.md`: Status corrected to `in-progress` (AC 3) ✓
  - `docs/stories/3-8-quiz-endpoint-live.md`: Process Failure Post-Mortem added (AC 4) ✓
  - `docs/stories/3-9-teachback-endpoint-live.md`: REFACTOR phase note added (AC 5) ✓
  - Tracker updated — this entry (AC 6) ✓
  - Branch: `sprint1/s1-15-bmad-process-docs`

- [x] **Sprint 1 Audit Technical Debt Fixes (FIND-001 / FIND-002 / FIND-003)** — ✓ 2026-07-02
  - Story 3-16: `docs/stories/3-16-sprint1-audit-fixes.md` — remediation story ✓
  - FIND-001: UTF-8 encoding artifact `prompts.py` line 73 (TEACHBACK_SYSTEM_PROMPT) fixed: `â€"` → `—` ✓
  - FIND-001b: Same artifact at `prompts.py` line 118 (score_teachback docstring) fixed ✓
  - FIND-002 (SEC-009b): `grade_teachback()` insert error now uses `safe_err` sanitization — mirrors grade_quiz() pattern ✓
  - FIND-003: Docstring `Raises:` section corrected — wrong-user returns 404 (SEC-006), not 403 ✓
  - 3 new unit tests: `test_teachback_system_prompt_no_encoding_artifact`, `test_teachback_insert_error_log_sanitized`, `test_score_teachback_docstring_no_encoding_artifact` ✓
  - 5-agent adversarial review passed: 2 patches applied (AC 2 docstring test + EOF newline) ✓
  - 72 unit tests pass (28 quiz + 44 teachback); no regressions ✓
  - Branch: `sprint1/s1-16-audit-fixes`
  - PR #51 merged to main ✓

- [x] **DPDP Act 2023: user_consents audit table — Sprint 1 production readiness** — ✓ 2026-07-02
  - Story 3-17: `docs/stories/3-17-dpdp-user-consents.md` — pulled forward from Sprint 2 (DPDP blocker) ✓
  - New migration `20260702000000_dpdp_user_consents.sql` applied to Supabase (version 20260702104540) ✓
  - `public.user_consents` table: id, user_id (FK→users CASCADE), consent_type (CHECK IN ['attention_tracking','learner_dna']), policy_version, consented_at, created_at — all NOT NULL ✓
  - RLS: INSERT + SELECT own only — no UPDATE/DELETE (immutable DPDP audit records) ✓
  - Trigger `user_consents_sync_attention`: AFTER INSERT, syncs `users.attention_consent = true` when consent_type='attention_tracking' ✓
  - `attention_events: insert own` RLS hardened: dual check — session ownership + boolean AND user_consents record must both exist ✓
  - Verified via live SQL introspection (columns, constraints, trigger, WITH CHECK clause) ✓
  - 5-agent review: APPROVED; 2 deferred (CASCADE retention, SELECT/UPDATE RLS note) ✓
  - Branch: `sprint1/s1-17-dpdp-user-consents`

---

## Sprint 2 — Weeks 4–5 (Due: ~2026-07-11)

> **Goal:** Full assessment pipeline: onboarding scoring, Learner DNA initial write, session reports, analytics, PostHog.

- [x] **DPDP Act 2023 compliance: `user_consents` audit table** — ✓ 2026-07-02 (delivered Sprint 1 — see Story 3-17)
  - **AC:** Migration file created and reviewed by all 4 devs; `user_consents` rows written at onboarding consent step
  - **Note:** Do NOT apply the migration autonomously — create the file and get team PR review first

- [x] **Onboarding assessment scoring logic complete** — ✓ 2026-07-02
  - Story 3-18: `docs/stories/3-18-onboarding-assessment-scoring.md` — status: done ✓
  - `POST /api/assessment/onboarding/submit` implemented with atomic SET NX idempotency guard ✓
  - `_compute_dimension_scores()` + `_compute_badge_labels()` service helpers ✓
  - `process_onboarding()`: insert→generate LLM profile→upsert learner_dna (with profile_text) ✓
  - Upsert error check added — raises HTTP 500 (prevents silent user lockout) ✓
  - 43/43 unit tests GREEN; 5-agent adversarial review, 7 BLOCKERs fixed ✓
  - Branch: `dev3-sprint2-task1`; PR open ✓
  - **AC:** After submitting 20 answers, `learner_dna` row exists with all 9 dimension values and `profile_text` ✓

- [x] **`learner_dna` table initial writes (9 sub-dimensions)** — ✓ 2026-07-02
  - All 9 dimension columns populated via `**scores` spread in upsert `dna_row` ✓
  - `_compute_dimension_scores()` returns all 9 keys; range 0-100 mathematically guaranteed ✓
  - DB CHECK constraints enforce 0-100 bounds at persistence layer ✓
  - `test_compute_dimension_scores_all_max/min/index_1` + upsert payload assertions confirm coverage ✓
  - **AC:** All 9 dimensions populated and within bounds (covered by merged Story 3-18)

- [x] **Session report generation API live** — ✓ 2026-07-02
  - Implement `GET /api/assessment/session/{id}/report`
  - Flow:
    1. Verify session ownership
    2. Query `quiz_attempts` → compute `quiz_score` (avg accuracy for session)
    3. Query `teachback_attempts` → compute `teachback_score` (avg score for session)
    4. Query `sessions.ces_final` → overall CES
    5. Compute `duration_minutes` from `sessions.started_at` / `ended_at`
    6. Return `SessionReport` with CES breakdown by component
  - **AC:** Full session report returned with all fields populated for a completed session

- [x] **Jargon hover usage event tracking** — ✓ 2026-07-03
  - Story 3-20: `docs/stories/3-20-analytics-events-ingestion.md` — status: in-progress (review complete, PR open) ✓
  - `POST /api/analytics/events` implemented; jargon_hover + all event types → `session_events` table ✓
  - Ownership check: HTTP 403 for cross-user or non-existent sessions; identical detail (no enumeration oracle) ✓
  - **AC:** After hovering a jargon term in player, row exists in `session_events` with `event_type = "jargon_hover"` ✓

- [x] **Session events instrumentation (tab_switch, retry_after_fail, etc.)** — ✓ 2026-07-03
  - All 9 event types accepted; unknown types logged at WARNING (soft validation, never rejected) ✓
  - Single bulk insert per batch; `client_timestamp_ms` stored in payload JSONB as `_client_ts_ms` ✓
  - 5-agent adversarial BMAD review — 6 BLOCKERs + 6 IMPROVEMENTs all fixed; 194/194 unit tests GREEN ✓
  - Branch: `dev3-sprint2-task3`; PR open ✓
  - **AC:** Batch of 10 events writes 10 rows to DB in a single transaction ✓

- [x] **Basic analytics module (per-session aggregations)** — ✓ 2026-07-03
  - Implement `GET /api/analytics/session/{id}/summary`
  - Aggregate from `session_events` + `attention_events` (read-only)
  - Return `SessionSummary` with: ces_score, avg_attention, distraction_events count, total_blinks, page_views, duration_seconds, events_count
  - 31 unit tests (26 initial + 5 post-review); SEC-006 anti-enumeration (identical 404); null exclusion for attention metrics; single session_events query; .limit(10_000) DoS guard; _parse_ts ValueError guard; 5-agent review approved
  - Story: `docs/stories/3-21-analytics-session-summary.md` — 18 ACs, all satisfied ✓
  - Branch: `dev3-sprint2-task4`; PR merged to main ✓
  - **AC:** Summary endpoint returns non-null values for a session with >5 events ✓

- [x] **PostHog events for all assessment actions** — ✓ 2026-07-03
  - Story 3-22: `docs/stories/3-22-posthog-assessment-events.md` — 19 ACs, all satisfied ✓
  - `posthog>=3.0.0` already in pyproject.toml; `posthog_api_key` + `posthog_host` added to config.py ✓
  - `apps/api/app/core/posthog_client.py` created — fire-and-forget `capture_event()` wrapper; no-op when `POSTHOG_API_KEY` empty ✓
  - `grade_quiz()` fires `assessment_quiz_submitted`; `grade_teachback()` fires `assessment_teachback_submitted`; `process_onboarding()` fires `assessment_onboarding_completed` ✓
  - `GET /api/assessment/session/{id}/report` fires `assessment_session_report_viewed` ✓
  - `GET /api/assessment/user/dna` implemented (was 501 stub) + fires `assessment_dna_viewed` ✓
  - 13 unit tests in `test_posthog_events.py`; 345 Dev 3 unit tests pass; 0 regressions ✓
  - Branch: `dev3-sprint2-task5`; **merged to main 2026-07-03** ✓
  - **AC:** PostHog dashboard shows events for each action in a test session ✓

---

## Sprint 3 — Weeks 6–7 (Due: ~2026-07-25)

> **Goal:** Full CES computation live, Learner DNA fusion + profile text, growth tracking.

- [x] **CES v1 formula implementation (5 weights as env vars)** — ✓ 2026-07-03
  - Create `apps/api/app/modules/assessment/ces.py`
  - Function signature: `compute_ces(quiz_accuracy, teachback_score, behavioral, head_pose, blink, settings) -> float`
  - Handle `teachback_score=None` (teach-back skipped): redistribute 0.25 weight proportionally — `quiz×0.467, behavioral×0.267, head_pose×0.160, blink×0.107`
  - All 5 inputs normalised to 0–1 before applying weights
  - Result scaled to 0–100, clamped to [0.0, 100.0]
  - Weights loaded from `Settings` object (env vars `CES_WEIGHT_*`)
  - Dev 4 calls this function from the WebSocket handler on each `AttentionSignalMessage`
  - **AC:** 20 unit tests pass; 5-agent adversarial code review passed; Story 3-23 status: done

- [x] **Per-learner baseline computation** — ✓ 2026-07-03
  - After session 1: baseline CES = session 1 CES final
  - From session 2+: rolling average of last 5 sessions' CES (window configurable via `CES_BASELINE_WINDOW`)
  - Cached in Redis `user:{user_id}:ces_baseline` (TTL-based)
  - `compute_and_store_ces_baseline(user_id, session_id, supabase, redis, settings)` returns `float | None`
  - 27 unit tests pass (25 original + 2 post-impl audit: AC 11/12 dedicated tests); 5-agent adversarial review approved; 2 BLOCKERs fixed
  - Post-impl audit (2026-08-04): AC 3 iscoroutinefunction assertion added; AC 11 + AC 12 explicit tests added; coverage header corrected; validation report at `docs/reports/sprint3-task2-bmad-validation-report.md`
  - Story 3-24 at `docs/stories/3-24-ces-baseline-computation.md` — status: done
  - Branch: `sprint3-task2-dev3` (post-audit remediation) — merged to `master-sprint3-dev3`

- [x] **Learner DNA fusion formula live** — ✓ 2026-07-03
  - After each completed session, update `learner_dna` dimensions:
    - `persistence` ← score increases if student retried after low teachback score
    - `frustration_tolerance` ← decreases if distraction interventions were high
    - `goal_orientation` ← increases if session completed without skips
    - `curiosity_index` ← increases proportional to jargon_hover events
    - `study_independence` ← decreases if help_seeking events > threshold
    - Cognitive dimensions (pattern_recognition, logical_deduction, processing_speed) ← updated from quiz accuracy + response_time_ms patterns
  - `fuse_learner_dna(*, user_id, session_id, supabase, settings)` — EMA fusion, 9 dimensions
  - EMA: `new = round(retain * old + (1 - retain) * signal, 4)` — `dna_ema_retain` env var (default 0.7)
  - All 9 dimensions computed from quiz/teachback/events data; clamped [0.0, 100.0]
  - Upserts `learner_dna` (9 dims + session_count); never touches badge_labels/profile_text
  - 30 unit tests pass (29 original + 1 post-impl audit: AC 21 bounds-violation test); 5-agent adversarial review approved; 3 BLOCKERs fixed (AC6 impl, AC17 test, AC18 test)
  - Post-impl audit (2026-08-04): AC 3 iscoroutinefunction assertion added; AC 20 upsert payload exclusion assertions added; AC 21 bounds-violation test added; scope extensions documented (redis param, record_dna_growth call); validation report at `docs/reports/sprint3-task3-bmad-validation-report.md`
  - Story 3-25 at `docs/stories/3-25-dna-fusion-formula.md` — status: done
  - Branch: `sprint3-task3-dev3` (post-audit remediation) — merged to `master-sprint3-dev3`

- [x] **GPT-4o-mini profile text generation** — ✓ 2026-07-06
  - Create `LEARNER_DNA_PROFILE_PROMPT` in `prompts.py`
  - Input: all 9 dimension values + session_count + badge_labels
  - Output: 2–3 sentence descriptive profile (no IQ/EQ/SQ/clinical language, no raw numbers)
  - Must include DPDP Act 2023 disclaimer as a fixed suffix on the response
  - Regenerate `profile_text` after every Learner DNA update (or when session_count is a multiple of 3)
  - **AC:** Profile text describes learning style naturally; spot-check confirms no clinical language
  - Story 3-26 at `docs/stories/3-26-dna-profile-text.md` — status: done
  - 29 unit tests GREEN; 5-agent adversarial review APPROVED; all 3 BLOCKERs + R4-R11 security/test patches resolved
  - Post-impl audit (2026-08-04): AC 8 iscoroutinefunction assertion added; tasks 3.24–3.29 documented; Dev Notes Option B block corrected; validation report at `docs/reports/sprint3-task4-bmad-validation-report.md`
  - Branch: `dev3-sprint3-task4` — merged into `main` (commit `54d4ec2` is ancestor of `master-sprint3-dev3`); post-audit remediation on `sprint3-task4-dev3`

- [x] **Growth tracking (delta per dimension per session)** — ✓ 2026-07-07
  - After each `learner_dna` upsert, write a `session_events` row:
    - `event_type: "dna_update"`, `payload: {dimension: str, old_value: float, new_value: float, delta: float}`
  - This powers the "growth since last session" view in session reports
  - **AC:** `session_events` contains `dna_update` rows with correct deltas after session completion
  - 21 unit tests GREEN; 5-agent adversarial review APPROVED; all 3 BLOCKERs resolved (R1 caplog AC10, R2 log injection, R3 analytics.service.write_system_events)
  - Story 3-27 at `docs/stories/3-27-dna-growth-tracking.md` — status: done
  - Post-impl audit (2026-08-04): AC 2 iscoroutinefunction assertion added; Dev Notes R3 template corrected; validation report at `docs/reports/sprint3-task5-bmad-validation-report.md`
  - Branch: `dev3-sprint3-task5` — merged into `main` via PR #68 (commit `e563f13`); post-audit remediation on `sprint3-task5-dev3`

- [x] **Session report: Learner DNA section** — ✓ 2026-07-21
  - Extend `GET /api/assessment/session/{id}/report` to include a `learner_dna_snapshot` field
  - Snapshot = dimension values at end of session + delta from previous session
  - Return descriptive labels not raw scores (e.g., "Persistence: Growing" not "Persistence: 67.5")
  - **AC:** Report response includes Learner DNA section with descriptive labels and deltas
  - Story 3-30 at `docs/stories/3-30-session-report-learner-dna-snapshot.md` — status: done
  - 56 unit tests GREEN (54 original + 2 post-audit BLOCKER regression tests); 5-agent adversarial review APPROVED (2 BLOCKERs patched: maybe_single None guard + isinstance payload guard); additive field `default=None`
  - Post-impl audit (2026-08-04): AC 1/9 counts corrected (test baseline 42 not 30; call count 7 not 6); Task 4.16/4.17 names fixed; BLOCKER-1/2 regression tests added; validation report at `docs/reports/sprint3-task6-bmad-validation-report.md`
  - Branch: `learner-mode-sprint-dev3-task3` — merged into `main` (commit `5ebcbe4`); post-audit remediation on `sprint3-task6-dev3`

- [x] **Re-assessment prompt after 10 sessions logic** — ✓ 2026-07-22
  - Story 3-31: `docs/stories/3-31-reassessment-prompt.md` — status: done ✓
  - `_REASSESSMENT_INTERVAL = 10` constant in `dna_fusion.py`; Step 7 sets `user:{uid}:reassessment_due = "1"` after every 10th session (non-fatal, `redis=None` default preserves backward compat for Dev 4) ✓
  - `get_learner_dna_data()` reads flag with `val == "1"` strict check; `redis=None` → False ✓
  - Router `get_learner_dna`: `get_redis()` guarded in try/except → graceful degradation if Redis unavailable ✓
  - Router `submit_onboarding_diagnostic`: re-assessment bypass before 409 guard; `_safe_uid` in logger ✓
  - 24 unit tests (15 original + 8 review-mandated + 1 G2 bypass regression) ✓
  - 5-agent adversarial review: 4 BLOCKERs + 5 IMPROVEMENTs found and resolved ✓
  - Post-impl audit remediation 2026-08-05: G1 vacuous mock assertion replaced with caplog-based regression guard; G2 router bypass tightened to `== "1"` (was `is not None`) + new regression test; G3 stale count corrected ✓
  - Branch: `sprint3-task7-dev3` — merged into `master-sprint3-dev3` ✓
  - **AC:** Flag is set correctly after sessions 10, 20, 30; `GET /user/dna` returns `reassessment_due: true` ✓

---

## Learner Mode Sprint (Ongoing — tier-aware quiz + session report)

> **Goal:** Extend the platform for T1/T2/T3 learner tiers — quiz counts per segment, session report context.

- [x] **Task 1 — Tier-aware quiz generation (Story 3-28)** — ✓ 2026-07-21
  - Extended `quiz_generator_node` to produce tier-appropriate MCQ counts per segment
  - T1 Full-Depth: 3–5 MCQs/segment · T2 Standard: 2–3 MCQs/segment · T3 Refresher: 1–2 MCQs/segment
  - `lessons.tier` column consumed from DB; default T2 when absent
  - Branch: `learner-mode-sprint-dev3-task1` — pushed to origin, PR raised

- [x] **Task 2 — Session report contextualised by tier (Story 3-29)** — ✓ 2026-07-21
  - Extended `GET /api/assessment/session/{id}/report` with 5 new fields:
    - `tier: str` — from `lessons.tier` (T1/T2/T3)
    - `tier_label: str` — Full-Depth / Standard / Refresher
    - `quiz_total_questions: int` — absolute count of quiz_attempts
    - `quiz_correct_count: int` — absolute correct count
    - `quiz_accuracy_label: str|None` — Strong/Developing/Needs Review/None
  - `_TIER_LABELS` constant + `_quiz_accuracy_label()` helper at module level in `service.py`
  - Lessons tier fetch runs after ownership check (SEC-006 preserved, asserted)
  - T2/Standard safe default when lesson row absent or tier value unexpected
  - 5-agent adversarial review: 2 BLOCKERs resolved (80%/60% boundary tests + SEC-006 assertion)
  - 42/42 tests GREEN (30 existing + 12 new); conftest.py openai stub extended
  - Story: `docs/stories/3-29-session-report-tier-context.md` — status: done
  - Branch: `learner-mode-sprint-dev3-task2` — pushed to origin; PR to `master-learner-mode-sprint-dev3` pending

- [x] **Task 3 — Session report Learner DNA snapshot (Story 3-30)** — ✓ 2026-07-21
  - Extended `GET /api/assessment/session/{id}/report` with `learner_dna_snapshot: dict[str, Any] | None = None` (additive, default=None)
  - Snapshot contains `dimension_labels` (descriptive text, no raw floats) + `growth_labels` (Improving/Declining/Stable/None)
  - Module-level constants `_DNA_GROWTH_IMPROVING_THRESHOLD=2.0`, `_DNA_GROWTH_DECLINING_THRESHOLD=-2.0`; pure `_delta_to_growth_label()` function
  - 5-agent adversarial review APPROVED; 2 BLOCKERs patched (maybe_single None guard + isinstance payload guard)
  - 42 unit tests GREEN (30 existing + 12 new); conftest.py openai stub extended
  - Story: `docs/stories/3-30-session-report-learner-dna-snapshot.md` — status: done
  - Branch: `learner-mode-sprint-dev3-task3` — merged to `master-learner-mode-sprint-dev3`

- [x] **Task 4 — Re-assessment prompt after 10 sessions (Story 3-31)** — ✓ 2026-07-22
  - `_REASSESSMENT_INTERVAL = 10` constant in `dna_fusion.py`; Step 7 sets `user:{uid}:reassessment_due = "1"` after every 10th session
  - `redis=None` default on `fuse_learner_dna()` preserves backward compat — Dev 4 must pass `redis=get_redis()` to activate
  - `get_learner_dna_data()` reads flag with strict `val == "1"` check; `redis=None` → `reassessment_due: false`
  - Re-assessment bypass in `submit_onboarding_diagnostic`: deletes `onboarding_done` key before SET NX guard so returning users can re-submit
  - 5-agent adversarial review: 4 BLOCKERs + 5 IMPROVEMENTs found and resolved
  - 24 unit tests (15 original + 8 review-mandated + 1 G2 bypass regression)
  - Post-impl audit remediation 2026-08-05: G1 vacuous mock assertion fixed; G2 router bypass tightened to `== "1"`; stale count corrected
  - Story: `docs/stories/3-31-reassessment-prompt.md` — status: done
  - Branch: `sprint3-task7-dev3` — merged into `master-sprint3-dev3`

- [x] **Task 5 — DPDP consent write endpoint, D29 fix (Story 3-32)** — ✓ 2026-08-05
  - Root cause: Story 3-17 delivered the `user_consents` migration but never built the runtime write path; AC "user_consents rows written at onboarding consent step" was marked done on migration landing only
  - `POST /api/assessment/consent` — returns 201 (first consent) or 200 (idempotent)
  - `record_consent()` in `service.py` — INSERT-first atomicity: tries INSERT, catches PostgreSQL 23505 (unique violation) and falls back to SELECT; this is TOCTOU-safe unlike SELECT-then-INSERT
  - `ConsentCreate` + `ConsentRecord` added to `schemas.py`
  - `supabase/migrations/20260805000000_user_consents_unique_constraint.sql` — UNIQUE(user_id, consent_type, policy_version) guards against duplicate rows under concurrent requests
  - 24 unit tests (all ACs covered, including AC 6 structural JWT guard, AC 5/7 body injection, idempotent to_thread count assertions)
  - 5-agent adversarial review: 4 IMPs + 7 MINORs all resolved before commit
  - Unblocks Dev 2: S3-01 (Attention Consent Modal) and S3-02 (AttentionMonitor/MediaPipe)
  - Story: `docs/stories/3-32-dpdp-consent-write-endpoint.md` — status: done
  - Branch: `sprint3/s3-32-dpdp-consent-endpoint` — merged to **main** 2026-08-14

- [x] **S3-54 — Onboarding LLM lock deadlock + HIE rebrand fix (D71/D72)** — ✓ 2026-08-13
  - **D71:** `process_onboarding()` Step 4 LLM call wrapped in `try/except Exception`; on failure: (a) rollback 20 orphaned `onboarding_responses` rows via `.eq("user_id").in_("question_id", _question_ids)`, (b) raise `HTTPException(503)` so router's existing `except HTTPException` cleanup fires and releases the Redis lock. Provider already has `@with_retry(max_attempts=3)`; permanent lock only triggered after all retries exhausted.
  - **D72:** Replaced "TransformED" → "HIE" in `DPDP_DISCLAIMER` (line 120) and `ONBOARDING_PROFILE_SYSTEM_PROMPT` (line 131) in `prompts.py`. Migration `20260813000000_learner_dna_rebrand.sql` backfills existing `learner_dna.profile_text` rows.
  - 7 unit tests in `tests/test_onboarding_llm_failure.py` — all GREEN; 57 existing onboarding tests unaffected
  - Story: `docs/stories/3-54-onboarding-lock-brand-fix.md` — status: done
  - Branch: `sprint3/s3-54-onboarding-lock-brand-fix`

- [x] **Task 5 — DPDP consent write endpoint, D29 fix (Story 3-32)** — ✓ 2026-08-05
  - Root cause: Story 3-17 delivered the `user_consents` migration but never built the runtime write path; AC "user_consents rows written at onboarding consent step" was marked done on migration landing only
  - `POST /api/assessment/consent` — returns 201 (first consent) or 200 (idempotent)
  - `record_consent()` in `service.py` — INSERT-first atomicity: tries INSERT, catches PostgreSQL 23505 (unique violation) and falls back to SELECT; this is TOCTOU-safe unlike SELECT-then-INSERT
  - `ConsentCreate` + `ConsentRecord` added to `schemas.py`
  - `supabase/migrations/20260805000000_user_consents_unique_constraint.sql` — UNIQUE(user_id, consent_type, policy_version) guards against duplicate rows under concurrent requests
  - 24 unit tests (all ACs covered, including AC 6 structural JWT guard, AC 5/7 body injection, idempotent to_thread count assertions)
  - 5-agent adversarial review: 4 IMPs + 7 MINORs all resolved before commit
  - Unblocks Dev 2: S3-01 (Attention Consent Modal) and S3-02 (AttentionMonitor/MediaPipe)
  - Story: `docs/stories/3-32-dpdp-consent-write-endpoint.md` — status: done
  - Branch: `sprint3/s3-32-dpdp-consent-endpoint` — merged into `master-sprint3-dev3`

- [x] **S3-45 — Behavioral fatigue trigger dispatch (D7)** — ✓ 2026-08-12
  - `config.py`: `ces_fatigue_blink_threshold` (default 0.3), `ces_fatigue_head_pose_threshold` (default 0.3), `ces_fatigue_min_session_seconds` (default 900, ge=60) — all env-var tunable
  - `websocket.py _init_session_state`: writes `session:{sid}:session_start_ts` (ex=86400); NOT written on reconnect path
  - `tutor/service.py process_attention_signal`: fatigue trigger block — primary trigger (blink+head_pose both < threshold for 2 consecutive windows AND duration >= 900s), exhaustion fallback (all MediaPipe None AND duration floor), once-per-session via `_can_intervene_fatigue`, `lrange` bounded (end=1), fail-closed on missing `session_start_ts`
  - 20 unit tests, all GREEN; ruff clean
  - Branch: `sprint3/s3-45-fatigue-signal-trigger` — pushed to origin
  - **Dependency note:** Exhaustion fallback (all-None MediaPipe) requires S3-38 to merge Optional NormalizedSignal fields. TOCTOU close (D6) requires S3-48 (Lua SET NX).

- [x] **S3-48 — Lua atomic distraction cap check+increment (D6)** — ✓ 2026-08-12
  - `graph.py`: Added `_DISTRACTION_GUARD_LUA` constant (EXISTS + INCR + EXPIRE + 'ok'/'cooldown'/'max_reached'); rewrote `_can_intervene_distraction(session_id, redis, settings)` to use `redis.eval` atomically; removed `_can_intervene_distraction` call from `route_from_teaching` (guard moved to service.py); removed `redis.incr` for distraction from `intervening_node` (Lua owns it); added `nx=True` to fatigue_fired and cooldown SET writes
  - `service.py`: Replaced `redis.exists(cooldown_key)` + `not in_cooldown` condition with `_can_intervene_distraction(session_id, redis, settings)` Lua call; import is lazy inside condition block
  - 18 unit tests, all GREEN; 8 pre-existing tests updated to reflect guard-moved-to-service.py design; ruff clean
  - Branch: `sprint3/s3-48-lua-atomic-distraction-cap` — pushed to origin

- [x] **S3-49 — JSON timestamps {v:float, t:int} in ces_history (D4)** — ✓ 2026-08-12
  - `config.py`: added `ces_cadence_seconds: int = Field(default=5, gt=0)` — gap-check tolerance
  - `tutor/service.py`: lpush now stores `json.dumps({"v": ces, "t": int(_time.time())})` instead of bare float; added `_parse_history_entry()` inner function with backward-compat fallback (bare float → t=0); D4 gap check `abs(t0-t1) <= 2 * ces_cadence_seconds` guards intervention trigger
  - `assessment/service.py`: added `compute_ces_from_session_aggregates()` with JSON parsing + backward-compat bare-float fallback; `from app.config import Settings` added to module imports
  - 13 unit tests in `test_s3_49_ces_history_timestamps.py` — all GREEN; existing tests updated for new JSON format and `ces_cadence_seconds` field
  - Branch: `sprint3/s3-49-ces-history-timestamps` — merged into `sprint3/s3-46-ces-breakdown-redistribution`

- [x] **S3-46 — ces_breakdown weight redistribution when teachback=None (D2)** — ✓ 2026-08-12
  - `assessment/service.py`: added `_build_ces_breakdown(*, quiz_accuracy, teachback_normalised, behavioral_avg, head_pose_avg, blink_avg, settings)` pure helper; nominal path uses weights as-is, redistributed path divides each remaining weight by `1.0 - ces_weight_teachback`; degenerate guard when `remaining <= 0.0` returns all-zeros
  - `get_session_report` Step 5 replaced inline dict with `_build_ces_breakdown` delegation; `teachback_normalised = avg_teachback/100 if teachback_count > 0 else None`
  - `test_session_report_endpoint.py`: `_mock_settings` and inline mock updated with 3 missing weight attributes; `test_get_report_ces_breakdown_quiz_matches_formula` expected updated to redistributed formula
  - 22 unit tests in `test_s3_46_ces_breakdown_redistribution.py` — all GREEN; 76/76 total session report tests GREEN
  - Branch: `sprint3/s3-46-ces-breakdown-redistribution` — pushed to origin

- [x] **S3-47 — formula_applied + signal_coverage in SessionReport (D17)** — ✓ 2026-08-12
  - `router.py`: imported `Literal` from `typing`; added `formula_applied: Literal["full_5_signal", "teachback_redistributed_4_signal"]` and `signal_coverage: int` to `SessionReport` after `learner_dna_snapshot`
  - `service.py`: added D17 computation block after Step 3 (teachback stats); passes both fields to `SessionReport(...)` constructor
  - `docs/openapi-assessment.json`: re-exported; both new fields appear under `SessionReport.properties`
  - 12 unit tests in `test_s3_47_formula_applied_signal_coverage.py` — all GREEN; 148 total regression tests GREEN; ruff clean
  - Branch: `sprint3/s3-47-ces-formula-disclosure` — committed
  - `get_session_report` Step 5 replaced inline dict with `_build_ces_breakdown` delegation; `teachback_normalised = avg_teachback/100 if teachback_count > 0 else None`
  - `test_session_report_endpoint.py`: `_mock_settings` and inline mock updated with 3 missing weight attributes (`ces_weight_behavioral=0.20`, `ces_weight_head_pose=0.12`, `ces_weight_blink=0.08`); `test_get_report_ces_breakdown_quiz_matches_formula` expected updated to redistributed formula (no-teachback → `(2/3)*(0.35/0.75)*100`)
  - 22 unit tests in `test_s3_46_ces_breakdown_redistribution.py` — all GREEN; 76/76 total session report tests GREEN
  - Branch: `sprint3/s3-46-ces-breakdown-redistribution` — committed

- [x] **S3-53 — CES production closure (D1/D62 canonical formula + all remaining audit gaps)** — ✓ 2026-08-12
  - **D1/D62:** ONE canonical `compute_ces` in `assessment/ces.py`; all 5 signals `float|None` with proportional redistribution for any None (including quiz_accuracy). `tutor/service.py` delegates to canonical formula — no inline formula. CI guard (AST scan in test_s3_53) prevents a second divergent implementation.
  - **D64:** `redis.expire()` added for `behavioral_history`, `head_pose_history`, `blink_history` after each lpush+ltrim (same `_CES_WINDOW_TTL=86400` as `ces_history`).
  - **D15:** Test asserts `session_start_ts` SET uses `nx=True` — first-connect wins; reconnects cannot reset the fatigue clock.
  - **D65:** Test exercises the positive distraction trigger path end-to-end (TEACHING + 2 consecutive sub-threshold + guard allows → `dispatch_event` called).
  - **D61:** `_init_session_state` retries `session_start_ts` write 3× with exponential backoff (0.1s, 0.2s); logs WARNING after all retries fail, session continues degraded (fatigue disabled for session).
  - **D63:** Deleted dead `_get_distraction_count` from `assessment/service.py`. `dna_fusion.py` reads intervention counts from `session_events` DB (correct path already).
  - **D19:** `SEMANTIC NOTE` added to `intervention_messages_used` in `router.py`: counts DB trigger events, not WS delivery confirmations. Rename deferred to next 4-dev frozen-contract review.
  - **Finalization fix:** `_finalize_session` writes `ces_final=None` (not `0.0`) for empty `ces_history`. `None` distinguishes no-data from zero-engagement. Logger updated from `%.2f` to `%s` to handle `None` without `TypeError`.
  - **Tests updated:** `test_ces.py` (2 redistribution tests updated for D62), `test_tutor_service.py` (3 tests updated for optional behavioral signals per D13), `test_s3_45_fatigue_trigger.py` (`nx=True` assertion added).
  - 18 new tests in `test_s3_53_ces_production_closure.py` — all GREEN; 168 CES-related tests total GREEN.
  - Branch: `sprint3/s3-53-ces-closure` — committed.

- [x] **S3-55 — Assessment API production-readiness: D71/D72 closures + D102/D103/D104 fixes (renumbered from D92/D93/D94 on merge)** — ✓ 2026-08-13
  - **D71 (register closure):** Confirmed fixed in Story 3-54 (`service.py:1166-1199`); 7/7 `test_onboarding_llm_failure.py` tests pass. Register entry closed in `docs/DEFECT-REGISTER.md` (~~D71~~).
  - **D72 (register closure):** Confirmed fixed in Story 3-54 (`prompts.py:120` uses "HIE"; migration backfills rows); `test_dpdp_disclaimer_uses_hie` + `test_system_prompt_uses_hie` + `test_migration_sql_has_rebrand_update` all pass. Register entry closed (~~D72~~).
  - **D102, was D92 (fix):** Added `.limit(10_000)` to `session_events` SELECT in `dna_fusion.py`. Added `# BOUNDED:` comments to `quiz_attempts` and `teachback_attempts` SELECTs. Registered and closed in defect register. Guarded by `test_dna_fusion_session_events_is_bounded` (AST walk).
  - **D103, was D93 (fix):** Added `"dna_fusion.py"` to `REQUEST_PATH_FILENAMES` in `test_unbounded_queries.py`. Extended `test_request_path_modules_are_where_we_think_they_are` to assert `assessment/dna_fusion.py` in scan scope. Registered and closed in defect register.
  - **D104, was D94 (fix):** Added `@field_validator("lesson_id", mode="before")` to `SessionCreate` in `schemas.py`; rejects non-UUID strings at Pydantic before DB cast; normalises to lowercase RFC 4122. Registered and closed in defect register. Guarded by `test_session_create_validates_uuid_format` + `test_session_create_accepts_uppercase_uuid`.
  - **D105, was D95 (registered, deferred):** EMA `session_count` Python read-modify-write race registered in defect register as open/deferred Sprint 4 (requires Postgres RPC migration for atomic increment). No code change this story. **Note:** possibly the same underlying defect as this tracker's own D93 (was D74, `session_count` read-modify-write, FIXED-GUARDED) — flagged for reconciliation in `docs/DEFECT-REGISTER.md`, not resolved here.
  - 20/20 AC14 tests GREEN: `test_unbounded_queries.py` (10) + `test_onboarding_llm_failure.py` (7) + `test_session_create_schema.py` (3). Zero new failures in test suite.
  - Story: `docs/stories/3-55-dev3-api-production-gaps.md` — status: done
  - Branch: `sprint3/s3-55-learner-dna-production-gaps`

- [x] **S3-42 — CES breakdown accuracy: per-signal Redis histories (D9)** — ✓ 2026-08-14
  - `tutor/service.py process_attention_signal`: per-signal history writes (`behavioral_history`, `head_pose_history`, `blink_history`) inside the TEACHING state guard only (CLAUDE.md §10: CES monitoring ONLY in TEACHING — non-TEACHING states must NOT accumulate history or they create false low-CES pairs)
  - Each history list: `lpush` → `ltrim(0, _CES_HISTORY_MAX-1)` → `expire(_CES_WINDOW_TTL)` — same bounded/TTL pattern as `ces_history` (D64 guard)
  - Signals with `None` value (MediaPipe frame dropped) do NOT write to their history — no phantom 0.0 entries
  - `assessment/service.py get_session_report`: `_signal_avg(key)` reads `lrange(key, 0, 9)` — BOUNDED at 10 entries (Scale Contract Q4); returns `round(sum/len, 4)` or `0.0`; delegates to `_build_ces_breakdown()` helper with real averages
  - `assessment/router.py`: `redis=get_redis()` passed to `get_session_report`; import tagged `# noqa: PLC0415 — S3-42 (D9)`
  - Tests: `test_s3_42_ces_breakdown_accuracy.py` — AC1–AC7 runtime + D108 (was D72) guard + AC1/AC3/AC4/AC5 source-inspection guards
  - AC1 (TEACHING writes), AC1-inverse (non-TEACHING no-write), AC2 (None signals skip), AC3 (signature accepts redis), AC4 (real data breakdown non-zero), AC5 (fallback 0.0), AC6 (router passes redis), AC7 (breakdown values correct), Scale Contract Q4 (ltrim cap)
  - Branch: `sprint3/s3-42-ces-breakdown-accuracy` — merged to main 2026-08-14

- [x] **S3-55 Fallout Fix — Story 3-55 regression patch: 32 red tests fixed + D105 closed** — ✓ 2026-08-14
  - **Issue 1 (29 tests):** Updated mock chains in 5 test files to match `.order("created_at").limit(10_000)` chain added by Story 3-55 to `quiz_attempts`, `teachback_attempts`, and `session_events` queries. Chain shape: `.eq → .order → .limit → .execute`. Special case: `test_reassessment_flag.py` `session_events` branch had neither `.order` nor `.limit` — both added (not just `.order`). Also fixed a second local `_table` in `test_dna_fusion.py::test_async_data_read_failure_is_non_fatal` where `side_effect` was wired to the old chain.
  - **Issue 2 (3 tests):** Replaced `"lesson-001"` with `"123e4567-e89b-12d3-a456-426614174000"` in `test_t26_api_contract_dev2.py` — `_VALID_SESSION_PAYLOAD` (line 86) and two inline POST `/sessions` bodies. `SessionCreate.lesson_id_must_be_uuid` (D104) correctly rejects the old non-UUID placeholder.
  - **Baseline fix (2 tests):** Added `import inspect` to `test_dna_fusion.py` and `test_dna_growth.py` — `test_positional_args_raise_type_error` was failing with `NameError` in both files.
  - **Issue 3 (D105 register):** Closed D105 as stale duplicate of D93 (FIXED-GUARDED 2026-08-13). Scorecard: 52 → 53 closed, 31 → 30 open.
  - Result: 114/114 pass across all 6 affected test files. 0 new failures vs pre-S3-55 baseline.
  - Branch: `sprint3/s3-55-fallout-fix` — merged to main 2026-08-14

---

## Demo Sprint — HIE Demo Preparation (Aug 2026)

> **Source:** `d:/HIE-Demo-Task-Tracker.xlsx` — Dev 3 individual and collaborative tasks.
> **Branch strategy:** Each task gets its own branch targeting `master-demo-dev3` (not main).

- [x] **T15 — Validate quiz+teachback against real LessonPackage schema** — ✓ 2026-08-13
  - 9 unit tests in `apps/api/tests/test_real_package_payload_validation.py`
  - Key finding: simplified fixtures silently scored teachback with `topic=""` and `key_concepts=[]`; schema-accurate fixture uses UUID IDs, namespaced segment/question IDs, all required fields
  - 9/9 PASS; BMAD 6-agent review clean (0 findings)
  - Branch: `dev3-demo-t15-phaseL4` — PR merged to `master-demo-dev3`
  - Story: `docs/stories/demo-t15-quiz-teachback-real-package-validation.md` — status: done

- [x] **T16 — End-to-end session flow with real UUID data** — ✓ 2026-08-13
  - 9 unit tests in `apps/api/tests/test_e2e_session_flow_real_data.py`
  - Validates full lifecycle: `create_session` → `grade_quiz` → `grade_teachback` → `get_session_report`
  - AC coverage: DB-minted session UUID (not client value), IDOR guards, formula disclosure, quiz_score=None when no quiz_attempts
  - 9/9 PASS; BMAD 6-agent review clean (0 findings)
  - Branch: `dev3-demo-t16-phaseL5` — PR merged to `master-demo-dev3`
  - Story: `docs/stories/demo-t16-e2e-session-flow-real-data.md` — status: done

- [x] **T18 — Learner DNA profile generation with real onboarding data** — ✓ 2026-08-13
  - 10 unit tests in `apps/api/tests/test_learner_dna_real_onboarding.py`; 11 review patches applied
  - Tests `process_onboarding` and Learner DNA EMA generation with real-format onboarding payloads
  - Branch: `dev3-demo-t18-phaseL5` — PR merged to `master-demo-dev3`
  - Story: `docs/stories/demo-t18-learner-dna-real-onboarding-data.md` — status: done

- [x] **T19 — DNA fusion real session events (9 tests, 12 review patches)** — ✓ 2026-08-13
  - Test-only story: covers gaps in `dna_fusion.py` not addressed by existing `test_dna_fusion.py` (28 tests)
  - **ACs covered:** AC1–AC9 (compute_signals, mixed session, EMA upsert, teachback, ended_at guard, no-quiz, IDOR, Redis modulo, Redis non-fatal)
  - **12 patches applied during 6-agent review:** P1–P12
  - **Deferred:** D93 (renumbered from D74; session_count read-modify-write race), D94 (renumbered from D75; event aggregation — closed by T20)
  - 37/38 tests GREEN (1 pre-existing D95 (was D76) failure in Python 3.12)
  - Story: `docs/stories/demo-t19-dna-fusion-real-session-events.md` — status: done
  - Branch: `dev3-demo-t19-phaseL5` — PR #132 merged to `master-demo-dev3`

- [x] **T20 — DNA fusion event aggregation DB path — 6 tests, closes D94 (was D75)** — ✓ 2026-08-13
  - Test-only story: covers event aggregation counting loop (lines 289–306) with non-empty `event_rows`
  - **ACs covered:** AC1–AC6 (JARGON_CAP counting, mixed events, empty guard, if-t guard, error propagation, non-neutral help)
  - **8 patches applied during 6-agent review:** P1–P8
  - **Deferred:** D95 (renumbered from D76; asyncio.get_event_loop pre-existing), D96 (renumbered from D77; session_events unbounded), D99 (renumbered from D78; CI guard blind spot)
  - 6/6 T20 tests GREEN; 127/128 assessment GREEN (1 pre-existing D95 (was D76) failure)
  - Story: `docs/stories/demo-t20-dna-fusion-event-aggregation-path.md` — status: done
  - Branch: `dev3-demo-t20-phaseL5` — PR #134 merged to `master-demo-dev3`

- [x] **T26 (Cross-team) — Quiz/teachback API contract review with Dev 2** — ✓ 2026-08-13
  - Confirm Dev 2's player sends payloads matching the frozen API contract
  - 18 HTTP-layer contract tests added: `apps/api/tests/test_t26_api_contract_dev2.py` — 18/18 pass
  - Covers: 422 bounds (answers, response_text, response_index, response_time_ms), banned-field silencing (transcript, duration_seconds), response shapes (feedback is list, rubric_scores are str labels), ApprovedUser 403 gate, security invariant (user_id from body never trusted), extra-field silence
  - Story: `docs/stories/demo-t26-quiz-teachback-api-contract-dev2.md`
  - Branch: `dev3-demo-t26-phaseL8` — PR targets `master-demo-dev3`
  - **Owner:** Dev 3 + Dev 2 (collaborative)

- [x] **T28 (Cross-team) — Learner DNA display review with Dev 2** — ✓ 2026-08-13
  - 18 unit tests in `apps/api/tests/test_t28_dna_display_contract_dev2.py`; 8 review patches applied
  - ACs: no raw dimension scores in GET/POST, DPDP_DISCLAIMER uses "HIE", ONBOARDING_PROFILE_SYSTEM_PROMPT uses "HIE", badge_labels have no IQ/EQ/SQ (word-boundary match), profile_text ends with DPDP_DISCLAIMER, GET returns 200/404, response shape has all 6 required fields
  - Review-added: P7 (Redis failure → 200), P8 (empty badge_labels → 200), DN-1 (profile_text=null → 200), DN-2 (no dimensions/scores container keys)
  - D87 registered (non-atomic Redis reassessment bypass — Dev 4 owned, deferred)
  - 18/18 PASS; 84/84 Demo Sprint tests PASS
  - Story: `docs/stories/demo-t28-learner-dna-crossteam.md` — status: done
  - Branch: `dev3-demo-t28-crossteam` — PR merged to `master-demo-dev3`
  - **Owner:** Dev 3 + Dev 2 (collaborative)

---

## Sprint 4 — Weeks 8–9 (Due: ~2026-08-08)

> **Goal:** Calibration, quality review, tuning. No new features — only data-driven improvements.

- [~] **Analyse 20+ real student test session data** ⚠️ PARTIAL — 2026-08-29 (doc written, 20-session target blocked — see below)
  - Run at least 20 end-to-end test sessions (can use internal team as testers)
  - Export `quiz_attempts`, `teachback_attempts`, `session_events`, `learner_dna` data
  - Look for: score distribution anomalies, CES formula outliers, Learner DNA convergence patterns
  - Document findings in `docs/sprint4-ces-calibration-notes.md`
  - **AC:** Analysis doc written; at least 3 concrete calibration observations documented
  - **Status:** `docs/sprint4-ces-calibration-notes.md` written with 6+ observations. Blocked by 1 remaining bug: behavioral/attention WebSocket signals not reaching Redis ces_history (Dev 2 must apply `?? null` fix in `useAttentionMonitor.ts`). **D116 FIXED 2026-08-31** — ces_final now written on session end. Once Dev 2's fix merges, run 20 sessions and update doc.

- [x] **D116: Wire complete_session → dispatch_event so ces_final is written (Story 4-6)** — ✓ 2026-08-31
  - Root cause: `complete_session` and `_finalize_session` built independently, never connected. ces_final NULL on all 117 sessions.
  - Fix: `route_entry` universal guard + `_finalize_session` owns only ces_final + `complete_session` dispatches lesson_complete.
  - 11 unit tests, ruff+mypy clean, 184 existing tests pass. Branch `sprint4/s4-6-d116-ces-final-wiring` merged to `master-sprint4-dev3`.

- [x] **CES weight tuning against post-session ground truth quiz scores (Story 4-31)** — ✓ 2026-09-05
  - Ground truth: final quiz score per session
  - Objective: tune weights so CES during session correlates with final quiz score (Pearson r > 0.6)
  - Method: try 5 weight combinations, compare correlation; pick best
  - **AC:** Chosen weights improve correlation; documented in calibration notes
  - **Status (done 2026-09-05):** `apps/api/scripts/ces_weight_grid_search.py` implemented (standalone CLI, reads S4-30 CSV). Provisional weights applied to `config.py` (quiz 0.35→0.40, behavioral 0.20→0.15). 42/42 tests PASS (17 S4-31 + 20 test_ces.py + 5 existing). Calibration notes §10 added. Branch: `sprint4/s4-31-ces-weight-tuning`

- [ ] **Update tuned weights in Railway env vars**
  - After weight selection: update `CES_WEIGHT_*` env vars in Railway dashboard (production)
  - No code change required — weights are already env vars
  - Document old → new values in calibration notes
  - **AC:** Railway env vars updated; confirmed via `/health` endpoint or config dump

- [ ] **Learner DNA profile quality review (human review 10 profiles)**
  - Extract 10 real `learner_dna.profile_text` values
  - Review checklist per profile: no clinical claims, no raw numbers, DPDP disclaimer present, tone is encouraging, 2–3 sentences
  - Document any failing profiles and the prompt fix applied
  - **AC:** All 10 profiles pass review checklist; failing cases have documented prompt fixes

- [x] **Onboarding question quality audit (Story 4-5)** — ✓ 2026-08-29
  - Review all 20 questions for: ambiguity, clinical language, cultural bias, response distribution
  - **AC:** Audit complete; 7 questions flagged (2 CRITICAL, 3 HIGH, 2 MEDIUM); all replacements applied
  - Branch: `sprint4/s4-5-onboarding-question-audit` merged to `master-sprint4-dev3`

- [x] **PostHog funnel analysis: where do students drop off? (Story 4-7)** — ✓ 2026-08-31
  - Funnel reconstructed from Supabase (PostHog received 0 events — D118 registered: POSTHOG_API_KEY never set in Railway)
  - **Biggest drop-off: session_start → quiz_submitted: 90.6%** (106/117 sessions never submitted a quiz)
  - Hypothesis 1: Lesson content never reached the quiz slide (player/package delivery failure — no zero-attempt vs. non-zero distinction)
  - Hypothesis 2: Session rows inflated by API test calls, not real lesson attempts (86 sessions in one week, all stage1_only)
  - Analysis written: `docs/sprint4-funnel-analysis.md` · Story: `docs/stories/4-7-posthog-funnel-analysis.md`

  > **Note (2026-07-22):** Sprint 4 originally had 6 tasks (not 5). Now expanded to 9 with addition of S4-6 (D116 fix), S4-7 (funnel analysis), and S4-8 (D60 notification pref) — dashboard updated.

- [x] **Wire `get_notification_preference()` into session report email delivery (D60 guard)** — ✓ 2026-08-31
  - Story 4-8 at `docs/stories/4-8-d60-notification-pref-guard.md` — status: done
  - Created `apps/api/app/modules/assessment/email_delivery.py` — `send_session_report_email(*, user_id, session_id, supabase)` stub
  - Preference gate wired as FIRST call: `get_notification_preference(user_id, "session_report_email", supabase)`
  - Opted-out user (`False`) → early return; opted-in user (`True`) → send stub (logs "provider not configured")
  - D60 Dev 3 portion updated in defect register — trigger fired (Story 4-8, 2026-08-31)
  - 3 unit tests GREEN in `apps/api/tests/test_d60_notification_pref_guard.py` (opted-out skip, opted-in stub, preference-before-send ordering)
  - Branch: `sprint4/s4-8-d60-notification-pref` → PR to `master-sprint4-dev3`

- [x] **Fix 22 pre-existing stale test assertions (Story 4-10)** — ✓ 2026-08-31
  - Full-suite audit on `master-sprint4-dev3`: 223 FAILED + 66 ERROR discovered; 23 in Dev 3 files, all pre-existing on `main`
  - **`tests/test_session_report_endpoint.py` (18 fixed):** `_build_report_supabase` mock chains updated to match current service query shapes (`.limit(500)` on quiz_attempts, `.order().limit(50)` on teachback_attempts, `.order().limit(20)` on intervention rows, `.limit(20)` on dna_update events). `ces_score` assertion updated to `is None` (deliberate design for empty history).
  - **`tests/test_s3_35_session_finalization.py` (2 fixed):** D116 assertions corrected — `ended_at` must NOT appear in `_finalize_session` payload (owned by `complete_session`); `ces_final=None` (not `0.0`) for empty Redis history.
  - **`tests/test_s3_42_ces_breakdown_accuracy.py` (1 fixed):** `getsource` target changed from `get_session_report` to `_build_ces_breakdown` (where the weights actually live).
  - **`tests/test_posthog_events.py` (1 fixed):** Added `formula_applied` + `signal_coverage` required fields to `SessionReport` constructor; added `get_redis` mock (router calls it before `get_session_report`).
  - 89 tests in 4 fixed files: all GREEN. No regressions in remaining Dev 3 suite.
  - Remaining 201 failures (187 Dev 1 FAILED + 66 Dev 1 ERROR + 12 Dev 4 FAILED + 2 integration) documented in `docs/sprint4-pre-existing-failures-report.md`.
  - Branch: `sprint4/s4-dev3-preexisting-test-fixes` → merged to `master-sprint4-dev3`
  - Story: `docs/stories/4-10-dev3-preexisting-test-fixes.md` — status: done

- [x] **Session dedup guard + CES architecture confirmation — ✓ 2026-08-31** (Story S4-11)
  - Item 3 (CES endpoint): confirmed WS-only architecture is correct — no REST endpoint needed
    - `attention_signal` WS → `process_attention_signal()` → `compute_ces()` → `Redis LPUSH session:{id}:ces_history`
    - On SESSION_END, `_finalize_session` reads history, averages, writes `ces_final`
    - Calibration notes §8 Item 3 updated with architecture explanation
  - Item 4 (duplicate sessions): fixed with 3-layer defence
    - Application-level pre-check: `create_session` queries open session before INSERT; returns it on hit
    - Race-safe fallback: concurrent INSERT loser re-fetches and returns the winner; no 500
    - DB backstop: partial UNIQUE INDEX `sessions_open_unique ON sessions(user_id, lesson_id) WHERE ended_at IS NULL`
    - Migration: `supabase/migrations/20260831000000_sessions_open_unique.sql` — apply via Supabase SQL editor before calibration run
  - Re-take invariant preserved: closed sessions excluded from check and index; mutation guard passes
  - 3 new tests pass; ruff GREEN; 2 pre-existing cross-team failures unchanged (D4-JWT, D18)
  - Branch: `sprint4/s4-11-session-dedup-ces-calibration` → merged to `master-sprint4-dev3`
  - Story: `docs/stories/4-11-session-dedup-ces-calibration.md` — status: done

- [x] **D137 — reassessment EMA blend fix (Story S4-12)** — ✓ 2026-09-01
  - Fixed `process_onboarding()` overwriting existing learner_dna with new scores instead of blending
  - `dna_fusion.py._apply_ema()` now called during reassessment; blend = 0.7×old + 0.3×new
  - `session_count` preserved on reassessment (not incremented — reassessment is not a new session)
  - D137 verified end-to-end against real Supabase: all 9 dims=60→72.0 (0.7×60+0.3×100) ✓
  - Branch: `sprint4/s4-12-reassessment-blend` | Story: `docs/stories/4-12-reassessment-blend.md`
  - **AC:** 6 unit tests GREEN; 1246-test full-suite pass, zero regressions; ruff + mypy clean; D137 FIXED-GUARDED in defect register

- [x] **DNA-personalized CES intervention threshold (Story S4-13)** — ✓ 2026-09-01
  - Closes the Learner DNA lifecycle loop: DNA → threshold → interventions → DNA (next session)
  - `compute_personalized_threshold()` in `ces.py`: formula + clamp + None safety (all-None → base)
  - 5 new env-var-tunable Settings fields: `ces_dna_weight_frustration/persistence/goal`, min/max clamp
  - `seed_personalized_ces_threshold()` in `service.py`: Redis cache → Supabase fallback → base (non-fatal)
  - `create_session_endpoint` wired to call seed after session creation; failure never fails the HTTP response
  - `tutor/service.py:process_attention_signal` reads `session:{sid}:ces_threshold` from Redis (O(1) hot path)
  - 14 unit tests, all GREEN; zero regressions (978 passing vs 965 before)
  - Branch: `sprint4/s4-13-dna-ces-threshold` | Story: `docs/stories/4-13-dna-personalized-ces-threshold.md`

- [x] **Learner Mode tier label verify (Story F2-3)** — ✓ 2026-09-04
  - Verified T1="Full-Depth" (45 min), T2="Standard" (30 min), T3="Refresher" (15 min) — labels were correct
  - Added `_TIER_MINUTES: dict[str, int] = {"T1": 45, "T2": 30, "T3": 15}` in `service.py` — makes mapping machine-checkable
  - Fixed inverted descriptions in `config.py`: "beginner/intermediate/advanced" → "Full-Depth 45-min / Standard 30-min / Refresher 15-min"
  - No API surface change (SessionReport unchanged — confirmed internal-only per user decision)
  - 9/9 unit tests GREEN; 6-layer BMAD review passed (2 patches: unused import + AC8 int-type test)
  - Branch: `feature2/f2-3-tier-label-verify` | Story: `docs/stories/f2-3-tier-label-verify.md`
- [x] **Teachback score source flag (Story F2-2)** — ✓ 2026-09-03
  - DB migration `20260903000000_teachback_score_source.sql`: `score_source TEXT NOT NULL DEFAULT 'llm' CHECK IN ('llm','fallback','skipped')` added to `teachback_attempts`
  - `TeachbackSubmission.is_skip: bool = Field(default=False)` — backward-compatible; `@model_validator` enforces non-blank only when `is_skip=False`
  - `grade_teachback()` restructured: count query now first (before lesson load); skip path exits before Steps 3–7 (no lesson JSONB read, no LLM call); fallback path traps all non-HTTPException LLM failures → HTTP 200 not 502
  - All 3 paths write `score_source` to DB; skip/fallback write `score=None`; insert errors are checked and raise HTTP 500 (not silently discarded)
  - `get_session_report`: avg excludes `score=None` rows; `.limit(200)` (was 50, F2-2 breaks 1-row-per-segment assumption); `avg_teachback` UnboundLocalError fixed (was critical bug on all-skip sessions)
  - `TeachbackDetail.score_source` + `TeachbackResult.score_source` added to frozen schema
  - D152 (ces_contribution=0.0 on skip vs CES redistribution) and D153 (HTTPException bypasses fallback) registered in defect register (renumbered from D150/D151 — Dev 4's BR-5 merged and claimed those IDs)
  - 25/25 unit tests GREEN; all 7 BMAD review patches applied; story: `docs/stories/f2-2-teachback-source-flag.md`
  - Branch: `feature2/f2-2-teachback-source-flag` — pushed; ready for PR

- [x] **Learner DNA + behaviour-signal prompt context helper (Story F2-1)** — ✓ 2026-09-03
  - Pure service-layer addition: `get_dna_prompt_context()` + `format_dna_for_prompt()` in `service.py`
  - No new HTTP route; no frozen contract change
  - **Two-path Supabase query:** on Redis cache hit → SELECT only `badge_labels, profile_text, session_count` (`_METADATA_SELECT`); on miss → SELECT all 9 dims + metadata (`_DNA_SELECT`). Fixes silent empty badge_labels for all returning students with a warm Redis cache (SCALE-CONTRACT §2 silent-wrong-result, caught by 6-layer BMAD review)
  - **`signals_capped: bool`** added to session_signals return dict — `True` when any session query hit its `.limit()` boundary; explicit surfaced degradation per SCALE-CONTRACT §2 (not silent truncation)
  - D149 registered: session_id-only filter is intentional (matches `get_session_report` pattern, relies on RLS)
  - 25 unit tests GREEN in `tests/unit/test_f2_1_dna_prompt_context.py`; guard tests 47/48 (pre-existing tinytag absence on this machine — not a code regression); ruff clean
  - Branch: `feature2/f2-1-dna-api-prompt-injection` | Story: `docs/stories/f2-1-dna-api-prompt-injection.md`

---

## Bug Resolution Sprint — Feature 2 (Sep 2026)

> **Goal:** Resolve remaining bugs + deliver learner context API for tutor personalisation.

- [x] **F2-1 — Learner Context API for tutor prompt injection** — ✓ 2026-09-05
  - Story: `docs/stories/f2-1-dna-prompt-context-api.md` — 11 ACs, Scale & Load section ✓
  - Branch: `feature2/f2-1-dna-prompt-context-api` — story-first commit (3d5ad00) before implementation (778888f) ✓
  - New endpoint: `GET /api/assessment/session/{session_id}/learner-context` returns `LearnerContext` ✓
  - IDOR-protected: 404 unified message for wrong-user or missing session (AC2) ✓
  - `LearnerContextDNA`, `LearnerContextSession`, `LearnerContext` added to `schemas.py` + `__all__` (AC10) ✓
  - `get_learner_context()` + `_build_learner_prompt_text()` in `service.py` — pure data aggregation, zero LLM calls (AC9) ✓
  - `dimension_labels` uses descriptive bands (strong/developing/building/emerging) — no raw floats to callers (AC3/AC11) ✓
  - `prompt_text` allowlist-filtered via `BADGE_THRESHOLDS.values()` — prompt injection defence ✓
  - All DB reads bounded: `.maybe_single()` for sessions/dna; `.eq().limit(500)` for quiz_attempts; `.eq().limit(50)` for teachback_attempts (AC8) ✓
  - 6-layer adversarial BMAD review run + R1–R3 patches applied (import dedup, asyncio.run(), .limit() mocks, DPDP endswith) ✓
  - 14/14 unit tests GREEN; guard tests `test_unbounded_queries.py` + `test_node_return_shape.py` pass (21/22 — 1 pre-existing tinytag failure unrelated to F2-1) ✓
  - Commits: story-first (3d5ad00), impl (778888f), R1 import (prev session), R1-R3 patches (4ae32b7) ✓

---

## Week 10 — Launch (Due: ~2026-08-15)

> **Goal:** Verify quality of first real student session end-to-end.

- [ ] **First session report reviewed for quality**
  - Review the session report generated for the first real paying student
  - Verify: all fields populated, CES is non-zero, quiz/teachback scores present, duration correct
  - **AC:** Report looks correct; no null fields; no division-by-zero or NaN values

- [ ] **First Learner DNA profile verified for accuracy**
  - Review the `learner_dna` row for the first real paying student after their first session
  - Verify: `profile_text` is coherent and student-appropriate, DPDP disclaimer present, all 9 dimensions non-null
  - **AC:** Profile approved; no clinical language; student-facing text reads naturally

---

## Update Protocol

When a task is completed:

1. Change `- [ ]` to `- [x]` on the task line
2. Append ` — ✓ YYYY-MM-DD` to the task title line
3. Update the **Quick Status Dashboard** table (increment Done, decrement Remaining)
4. Update the **Last updated** date in the header

Example completed task:
```markdown
- [x] **`POST /api/assessment/quiz` endpoint live** — ✓ 2026-06-25
```

Do not delete task details after completion — they serve as a specification record.

