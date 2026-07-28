---
id: 4-22
title: Sprint 2 (Dev 4) test-suite green — fix two test-fixture defects
sprint: 2
owner: Dev 4
status: draft
branch: sprint2/s2-8-test-suite-green
base: dev4/s2
depends_on: []
---

# Story 4-22 — Sprint 2 (Dev 4) test-suite green

## Context

The Sprint 2 validation audit (`docs/sprint2-dev4-validation-report.md`) found **19 failing Dev-4
tests** on the `dev4/s2` ("master sprint 2") branch, from **two self-contained test-fixture
defects**. Neither is a product defect — the production code is correct; the tests mock it wrong.
This story fixes the fixtures so the Sprint-2 branch is genuinely green and can be audited/reported
honestly.

Scope is **test files only**. No source/behaviour change. Integration to `main` (rebase vs
cherry-pick) is out of scope — deferred per `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-24.md`.

## Root causes

- **ISSUE-1 (13 tests, `tests/test_tutor_service.py`):** the `_setup` helper's `MagicMock` settings
  sets only `ces_threshold`, never `ces_weight_*`. The real §11 `compute_ces()` reads those weights →
  `weight_sum` is a `MagicMock` → `TypeError` at `service.py:127`.
- **ISSUE-2 (6 tests, `tests/test_auth.py`):** tokens minted with <32-byte secrets
  (`"test-jwt-secret"` 15 B; `"a-completely-different-secret"` 29 B) trip PyJWT ≥2.10
  `InsecureKeyLengthWarning`, promoted to an error by `filterwarnings = error`.

## Acceptance Criteria

- **AC1:** `tests/test_tutor_service.py` `_setup` sets all five `ces_weight_*` on the mock settings,
  matching `config.py` defaults (0.35 / 0.25 / 0.20 / 0.12 / 0.08), so `compute_ces()` on the mock
  equals the module-level `_EXPECTED_CES` computed against real settings.
- **AC2:** `tests/test_tutor_service.py` passes with **0 failures** (target 27 passed).
- **AC3:** `tests/test_auth.py` uses secrets ≥32 bytes everywhere a token is minted (both `_SECRET`
  and the inline wrong-secret literal), and passes with **0 failures** (target 10 passed).
- **AC4:** The full Dev-4 file set — `test_tutor_graph.py`, `test_tutor_service.py`,
  `test_websocket_session.py`, `test_lesson_ready_pubsub.py`, `test_lesson_ready_integration.py`,
  `test_ws_load_test.py`, `test_auth.py` — runs with **0 failing, 0 error**.
- **AC5:** No change to any file under `apps/api/app/` (source untouched — fixtures only).

## Out of scope

- `main`-side Ruff-lint CI failure (separate integration follow-up).
- Merging `dev4/s2` to `main`; the branch-strategy decision.
- Adding new coverage (tracked separately if desired).

## Test plan

```bash
cd apps/api
export SUPABASE_URL=http://localhost:54321 SUPABASE_ANON_KEY=test SUPABASE_SERVICE_ROLE_KEY=test \
       SUPABASE_JWT_SECRET=test-secret-at-least-32-chars-long!! REDIS_URL=redis://localhost:6379 \
       OPENAI_API_KEY=test SARVAM_API_KEY=test HEYGEN_API_KEY=test \
       LANGFUSE_PUBLIC_KEY=test LANGFUSE_SECRET_KEY=test
python -m pytest tests/test_tutor_service.py tests/test_auth.py -p no:cacheprovider -q
```
