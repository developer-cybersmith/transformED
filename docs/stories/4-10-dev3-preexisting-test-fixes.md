---
status: in-progress
---

# Story 4-10 — Dev 3 Pre-existing Test Fix: 22 Stale Assertions After Service Additions

**Sprint:** 4 · **Owner:** Dev 3
**Branch:** `sprint4/s4-dev3-preexisting-test-fixes`

## Background

A full-suite audit on 2026-08-31 revealed 223 test failures on `master-sprint4-dev3`
(220 on `main` baseline). 23 of those failures are in Dev 3's test files. All 23 are
pre-existing on `main` — not regressions from Sprint 4 work.

Root cause is a single pattern repeated across four files: **the service layer evolved
(adding `.limit()`, `.order()`, new required Pydantic fields) but the corresponding
tests were never updated.** Mock chains targeting the old DB call sequences now resolve
to auto-created MagicMock objects instead of test fixture data, causing `len()` to return
0, Pydantic to fail validation, and source-inspection assertions to target the wrong
function.

The one remaining failure (`test_unauthenticated_request_is_rejected`, Dev 3 endpoint)
is caused by Dev 4's JWT middleware returning HTTP 403 instead of 401 — it is NOT fixed
here; it is documented and flagged to Dev 4.

## Acceptance Criteria

- **AC1:** `tests/test_session_report_endpoint.py` — all 18 previously failing tests
  pass. Root cause: `_build_report_supabase` mock chains updated to match current
  service query shapes (`.limit()` on quiz, `.order().limit()` on teachback,
  `.order().limit()` on intervention rows, `.limit()` on dna_update events).
- **AC2:** `tests/test_s3_35_session_finalization.py` — both previously failing tests
  updated to match D116 design: `ended_at` is NOT in `_finalize_session` payload
  (written by `complete_session` endpoint), and `ces_final=None` (not `0.0`) when
  Redis history is empty.
- **AC3:** `tests/test_s3_42_ces_breakdown_accuracy.py` — `test_ces_breakdown_uses_
  settings_weights_not_hardcoded` updated to inspect `_build_ces_breakdown` source
  (where the weights actually live) instead of `get_session_report`.
- **AC4:** `tests/test_posthog_events.py` — `test_posthog_session_report_event_fired`
  updated to include the two required `SessionReport` fields added in Story 3-47:
  `formula_applied` and `signal_coverage`.
- **AC5:** `test_session_create_endpoint.py::test_unauthenticated_request_is_rejected`
  is NOT fixed here — it is Dev 4's JWT middleware bug (403 vs 401). Documented in
  `docs/sprint4-pre-existing-failures-report.md`.
- **AC6:** All other Dev 3 tests continue to pass (no regressions).
- **AC7:** `docs/sprint4-pre-existing-failures-report.md` created, classifying all 223
  failures by developer ownership with root cause and fix recommendation per group.
- **AC8:** `docs/dev3-assessment-tracker.md` updated — S4-10 marked done.

## Scale & Load

1. **Unit of work:** Test assertion corrections — zero runtime behaviour change.
2. **Fixed budgets while input varies:** N/A — test-only changes, no runtime budget.
3. **Scope of each limit:** N/A — tests are isolated to one process.
4. **Unbounded reads/writes:** N/A — no DB calls in this story.
5. **Inherited caps re-derived:** N/A.
6. **Concurrent check-then-act:** N/A — tests are single-threaded.

## Tasks

- [x] T1: Create story file, commit alone, push
- [ ] T2: Fix `_build_report_supabase` mock chains in `test_session_report_endpoint.py` (AC1)
- [ ] T3: Fix `test_s3_35_session_finalization.py` assertions (AC2)
- [ ] T4: Fix `test_s3_42_ces_breakdown_accuracy.py` source inspection (AC3)
- [ ] T5: Fix `test_posthog_events.py` SessionReport constructor (AC4)
- [ ] T6: Run full Dev 3 test suite — 22+ tests now GREEN
- [ ] T7: Create `docs/sprint4-pre-existing-failures-report.md` (AC7)
- [ ] T8: Update `docs/dev3-assessment-tracker.md` (AC8)
- [ ] T9: Commit, push, merge into master-sprint4-dev3, raise PR

## Change Log

| Date | Author | Change |
|---|---|---|
| 2026-08-31 | Dev 3 | Story created |
