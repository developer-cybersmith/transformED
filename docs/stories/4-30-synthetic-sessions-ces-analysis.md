# Story 4-30 — Synthetic Session Generator + CES Calibration Analysis

**Status:** ready-for-dev  
**Sprint:** 4 (Weeks 8–9)  
**Owner:** Dev 3  
**Branch:** `sprint4/s4-30-synthetic-sessions-ces-analysis`

---

## Background

`docs/sprint4-ces-calibration-notes.md` was written on 2026-08-29 with 6+ observations from 117 internal sessions. The AC ("analysis doc written; at least 3 concrete calibration observations documented") is met. However:

- The 20-session calibration run was blocked by D116 (ces_final always NULL). D116 is now **FIXED** in Story S4-6 (2026-08-31).
- Dev 2's `?? null` behavioral-signal fix (PR #161) may or may not be merged into the test environment.
- No script exists to generate reproducible synthetic test sessions against the API, making future re-runs ad hoc.

This story delivers:
1. A synthetic session generator script that can drive the full quiz/teachback/complete lifecycle via HTTP + simulates attention signals via WebSocket.
2. A calibration data export script that queries Supabase directly and produces a structured CSV for analysis.
3. Updated calibration notes (`docs/sprint4-ces-calibration-notes.md`) with a §10 section documenting how to run the 20-session calibration once prerequisites are in place.

---

## Acceptance Criteria

### AC 1 — Synthetic session generator script exists and is documented
- `apps/api/scripts/generate_test_sessions.py` creates a configurable number of sessions via the real API
- Each synthetic session covers: `POST /api/assessment/sessions` → `POST /api/assessment/quiz` (N segments) → `POST /api/assessment/teachback` (N segments) → `POST /api/assessment/sessions/{id}/complete`
- The script accepts `--api-url`, `--auth-token`, `--n-sessions`, `--segments-per-session` CLI args
- Each quiz answer is randomised with a configurable accuracy rate (`--quiz-accuracy`, default 0.7)
- Each teachback response is a fixed stub that produces a predictable score
- The script outputs a CSV summary: `session_id, quiz_accuracy, teachback_avg, ces_final` (ces_final requires D116 wiring to be live)

### AC 2 — Calibration data export script exists
- `apps/api/scripts/export_calibration_data.py` reads from Supabase (requires `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` env vars)
- Exports: `sessions` (with ces_final), `quiz_attempts` (per session accuracy), `teachback_attempts` (per session avg score), `session_events` (count per type per session)
- Output: `ces_calibration_export.csv` with one row per session containing all signals needed for weight grid search

### AC 3 — Calibration notes updated with run instructions
- `docs/sprint4-ces-calibration-notes.md` §10 added: "How to Run the 20-Session Calibration"
- Section documents: prerequisites checklist, command to run generator, command to export, what to hand to the grid search script (Story 4-31)

### AC 4 — Scripts are self-contained and have no dependency on production code import paths
- Scripts import only `httpx`, `csv`, `argparse`, `os`, `json`, `asyncio`, `supabase` (SDK) — no `from app.*` imports
- Both scripts run from repo root with `python apps/api/scripts/generate_test_sessions.py --help`

### AC 5 — Unit tests cover script logic without hitting network
- `apps/api/tests/test_s4_30_synthetic_sessions.py` contains at least 8 unit tests
- Tests cover: quiz accuracy randomisation, teachback stub payload, CSV output format, Supabase export row shape, arg parser defaults
- No tests require a running API or Supabase connection (all network calls mocked)

### AC 6 — Guard tests for existing modules still pass
- `pytest tests/unit/test_unbounded_queries.py tests/unit/test_node_return_shape.py -v` — GREEN (new scripts don't touch any guarded module)
- `ruff check apps/api/app/` — GREEN (no changes to `app/` module)

---

## Scale & Load

**Q1 — Unit of work & range**  
One synthetic session = 4–8 HTTP calls (1 create + N quiz + N teachback + 1 complete). Typical N=3 segments → 8 HTTP calls. Script can generate 1–200 sessions; 20 is the target. Duration: ~30s for 20 sessions at sequential cadence (no parallelism in MVP script).

**Q2 — Fixed budgets vs variable input**  
- `--n-sessions` defaults to 20; any value 1–200 accepted. Beyond 200: script raises `ValueError("n-sessions must be 1–200")` — explicit error, not silent over-spend.
- `--segments-per-session` defaults to 3; any value 1–20 accepted. Beyond 20: `ValueError`.
- CSV output: bounded by `n-sessions × segments-per-session` rows. Max 200×20 = 4,000 rows — small.
- Export script: reads `sessions` with `.limit(10_000)` (same cap as other Dev 3 queries); prints a warning if the limit is hit (`signals_capped=True` surfaced in script output).

**Q3 — Scope of limits**  
Per-run limits (CLI args). Export limit is per-call, not per-user.

**Q4 — Unbounded reads/writes**  
Export script: all Supabase reads carry `.limit(10_000)`. No write in export script. Generator script writes via API (already bounded by `n-sessions`).

**Q5 — Inherited caps**  
N/A — new scripts; no inherited limits from other stories.

**Q6 — Concurrent TOCTOU safety**  
Script runs locally (not on Railway); no concurrent execution risk. Each session created independently; no shared state between iterations.

---

## Dev Notes

### Script architecture

Both scripts are **standalone** (no `from app.*` imports):
- `generate_test_sessions.py`: uses `httpx` for HTTP, `asyncio` for optional concurrency (sequential by default)
- `export_calibration_data.py`: uses `supabase` Python SDK directly (service-role key for admin reads)

### Stub teachback response

The stub teachback text is chosen to produce a predictable score. The text `"The key concept is explained clearly with relevant detail."` has been validated against the rubric (accuracy: high, completeness: moderate, clarity: high) in prior test runs and produces scores in the 70–85 range consistently.

### Authentication

The generator script requires a real JWT. In test environments: `supabase.auth.sign_in_with_password({"email": ..., "password": ...})` to obtain a token. The `--auth-token` arg accepts a pre-obtained bearer token (no password stored in script). The export script uses the service-role key (not a JWT) for admin reads.

### CSV output format

Generator output:
```
session_id,quiz_accuracy_pct,teachback_avg_score,ces_final,n_quiz_attempts,n_teachback_attempts
```

Export output:
```
session_id,user_id,started_at,ended_at,ces_final,quiz_accuracy_pct,quiz_attempts,teachback_avg,teachback_attempts,interventions,tab_switches
```

---

## Tasks

- [ ] Write `apps/api/scripts/generate_test_sessions.py` with CLI interface
- [ ] Write `apps/api/scripts/export_calibration_data.py` with Supabase direct reads
- [ ] Add §10 "How to Run the 20-Session Calibration" to `docs/sprint4-ces-calibration-notes.md`
- [ ] Write `apps/api/tests/test_s4_30_synthetic_sessions.py` (≥ 8 tests)
- [ ] Run guard tests and ruff
- [ ] Update tracker: mark 4-30 partial→done, update dashboard

---

## Senior Developer Review (AI)

*To be completed post-implementation via `/bmad-code-review`.*
