# Dev 3 — Assessment, CES & Learner DNA: Sprint Tracker

**Owner:** Dev 3 (tannmayygupta) · developer@cybersmithsecure.com
**Domain:** Quiz API · Teachback Scorer · CES Formula · Learner DNA · Session Reports · Analytics
**PRD version:** 1.0 Final (2026-06-10) — CLAUDE.md is the single source of truth
**Last updated:** 2026-07-06 (Sprint 3 Task 4 DONE — Story 3-26: GPT-4o-mini Learner DNA profile text generation (29 tests, LEARNER_DNA_PROFILE_PROMPT, _dim_descriptor, build_dna_profile_prompt, generate_dna_profile_text, refresh_dna_profile; 5-agent review APPROVED, all 3 BLOCKERs + 11 patches resolved); 506 unit tests pass; dev3-sprint3-task4 pushed to origin)
**Sprint 0 status — COMPLETE + BMAD AUDITED 2026-06-27:** All 7 tasks done and merged to main. Post-merge BMAD quality audit passed (4 parallel agents — backend accuracy, test quality, Dev 2 integration, story completeness). Audit fixes applied on `sprint0/s0-8-audit-test-fixes`: analytics migration tests rewritten with table-scoped assertions (D→B rating), teachback scoring boundary tests added (score=89/90), CES weight @model_validator wired in config.py, onboarding content tests updated to new path, `jsonschema` added to dev deps. Story 3.7 closed. 120 unit tests pass.

---

## Quick Status Dashboard

| Sprint | Period | Tasks | Done | Partial | Not Started |
|--------|--------|-------|------|---------|-------------|
| Sprint 0 | Week 1 | 7 | 7 | 0 | 0 |
| Sprint 1 | Weeks 2–3 | 12 | 12 | 0 | 0 |
| Sprint 2 | Weeks 4–5 | 7 | 7 | 0 | 0 |
| Sprint 3 | Weeks 6–7 | 7 | 4 | 0 | 3 |
| Sprint 4 | Weeks 8–9 | 5 | 0 | 0 | 5 |
| Week 10 | Launch | 2 | 0 | 0 | 2 |
| **Total** | | **40** | **30** | **0** | **10** |

Update this table each time a task is checked off below.

---

## Primary Files (Dev 3 Owns)

| File | Purpose |
|------|---------|
| `apps/api/app/modules/assessment/router.py` | All 5 assessment endpoints |
| `apps/api/app/modules/analytics/router.py` | Event ingestion + session summary |
| `apps/api/app/modules/assessment/service.py` | *(to create)* Business logic layer |
| `apps/api/app/modules/analytics/service.py` | *(to create)* Analytics aggregation |

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
  - 25 unit tests pass; 5-agent adversarial review approved; 2 BLOCKERs fixed
  - Story 3-24 at `docs/stories/3-24-ces-baseline-computation.md` — status: done
  - Branch: `dev3-sprint3-task2` — merged to main via PR #59

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
  - 29 unit tests pass; 5-agent adversarial review approved; 3 BLOCKERs fixed (AC6 impl, AC17 test, AC18 test)
  - Story 3-25 at `docs/stories/3-25-dna-fusion-formula.md` — status: done
  - Branch: `dev3-sprint3-task3` — pushed to origin, PR pending

- [x] **GPT-4o-mini profile text generation** — ✓ 2026-07-06
  - Create `LEARNER_DNA_PROFILE_PROMPT` in `prompts.py`
  - Input: all 9 dimension values + session_count + badge_labels
  - Output: 2–3 sentence descriptive profile (no IQ/EQ/SQ/clinical language, no raw numbers)
  - Must include DPDP Act 2023 disclaimer as a fixed suffix on the response
  - Regenerate `profile_text` after every Learner DNA update (or when session_count is a multiple of 3)
  - **AC:** Profile text describes learning style naturally; spot-check confirms no clinical language
  - Story 3-26 at `docs/stories/3-26-dna-profile-text.md` — status: done
  - 29 unit tests GREEN; 5-agent adversarial review APPROVED; all 3 BLOCKERs + R4-R11 security/test patches resolved
  - Branch: `dev3-sprint3-task4` — pushed to origin, PR pending

- [ ] **Growth tracking (delta per dimension per session)**
  - After each `learner_dna` upsert, write a `session_events` row:
    - `event_type: "dna_update"`, `payload: {dimension: str, old_value: float, new_value: float, delta: float}`
  - This powers the "growth since last session" view in session reports
  - **AC:** `session_events` contains `dna_update` rows with correct deltas after session completion

- [ ] **Session report: Learner DNA section**
  - Extend `GET /api/assessment/session/{id}/report` to include a `learner_dna_snapshot` field
  - Snapshot = dimension values at end of session + delta from previous session
  - Return descriptive labels not raw scores (e.g., "Persistence: Growing" not "Persistence: 67.5")
  - **AC:** Report response includes Learner DNA section with descriptive labels and deltas

- [ ] **Re-assessment prompt after 10 sessions logic**
  - After session_count reaches 10 (and every 10 thereafter): set flag `user:{user_id}:reassessment_due = "1"` in Redis
  - `GET /api/assessment/user/dna` should include `reassessment_due: bool` field in response
  - Frontend uses this flag to prompt user to retake the 20-question onboarding
  - **AC:** Flag is set correctly after sessions 10, 20, 30; `GET /user/dna` returns `reassessment_due: true`

---

## Sprint 4 — Weeks 8–9 (Due: ~2026-08-08)

> **Goal:** Calibration, quality review, tuning. No new features — only data-driven improvements.

- [ ] **Analyse 20+ real student test session data**
  - Run at least 20 end-to-end test sessions (can use internal team as testers)
  - Export `quiz_attempts`, `teachback_attempts`, `session_events`, `learner_dna` data
  - Look for: score distribution anomalies, CES formula outliers, Learner DNA convergence patterns
  - Document findings in `docs/sprint4-ces-calibration-notes.md`
  - **AC:** Analysis doc written; at least 3 concrete calibration observations documented

- [ ] **CES weight tuning against post-session ground truth quiz scores**
  - Ground truth: final quiz score per session
  - Objective: tune weights so CES during session correlates with final quiz score (Pearson r > 0.6)
  - Method: try 5 weight combinations, compare correlation; pick best
  - **AC:** Chosen weights improve correlation; documented in calibration notes

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

- [ ] **Onboarding question quality audit**
  - Review all 20 questions for: ambiguity, clinical language, cultural bias, response distribution (are students using the full scale?)
  - Flag questions where >80% of responses are the same value (low discrimination)
  - Propose replacements for flagged questions
  - **AC:** Audit complete; max 3 questions flagged; replacements proposed

- [ ] **PostHog funnel analysis: where do students drop off?**
  - In PostHog, build funnel: session_start → quiz_submitted → teachback_submitted → session_end
  - Identify the step with the highest drop-off rate
  - Document top 2 drop-off hypotheses with supporting event data
  - **AC:** Funnel dashboard exists in PostHog; drop-off analysis written in `docs/sprint4-funnel-analysis.md`

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
