---
id: "4-35"
title: "Fix _apply_ema MagicMock regression — patch dna_ema_retain in test mocks"
status: "in-progress"
sprint: 4
story_points: 1
owner: Dev3
priority: P0
depends_on: []
---

# Story 4-35 — Fix _apply_ema MagicMock Regression

## Context

Story 4-34's audit (2026-09-07) identified a live regression in `main`:
10 tests across two files fail with:

```
TypeError: '>' not supported between instances of 'MagicMock' and 'float'
```

**Root cause:** The EMA reassessment blend story (D137 fix) added this call to
`service.py:1701`:

```python
retain = get_settings().dna_ema_retain
for dim in ALL_NINE_DIMENSIONS:
    scores[dim] = _apply_ema(existing_dna.get(dim), scores[dim], retain)
```

`_apply_ema` clamps its result with `max(0.0, min(100.0, result))`. When
`retain` is a `MagicMock` (because the test's `get_settings()` mock does not
set `dna_ema_retain`), arithmetic produces a MagicMock, and the comparison in
`max/min` raises `TypeError`.

`dna_ema_retain` IS a proper Settings field (`config.py:511`, default `0.7`).
The production code path is correct. Only the test mocks are missing the field.

**Affected files (confirmed by live test run):**
- `apps/api/tests/test_onboarding_endpoint.py` — 6 failures
- `apps/api/tests/test_posthog_events.py` — 4 failures

## Story

**As a** Dev 3 maintaining the assessment test suite,
**I want** all mocks of `get_settings()` that exercise code paths through
`service.py:1701` to set `dna_ema_retain = 0.7`,
**so that** `_apply_ema` receives a real float and the 10 broken tests in
`main` are restored to green.

## Acceptance Criteria

- [ ] **AC 1.** `_fake_settings()` in `test_onboarding_endpoint.py` (line ~43)
  sets `settings.dna_ema_retain = 0.7`.
- [ ] **AC 2.** Every `with patch("app.modules.assessment.service.get_settings")`
  block in `test_onboarding_endpoint.py` sets
  `mock_settings.return_value.dna_ema_retain = 0.7`.
- [ ] **AC 3.** The `_mock_settings` fixture in `test_posthog_events.py` sets
  `mock_s.dna_ema_retain = 0.7`.
- [ ] **AC 4.** After the fix, `test_onboarding_endpoint.py` has **0 failures**
  (all previously-passing tests still pass, 6 regressions restored).
- [ ] **AC 5.** After the fix, `test_posthog_events.py` has **0 failures**
  (all previously-passing tests still pass, 4 regressions restored).
- [ ] **AC 6.** `tests/test_ces.py` guard — all 26 tests still pass.
- [ ] **AC 7.** `ruff` check clean on both modified files.

## Scale & Load

**Q1** — Unit of work: patching a MagicMock field in test fixtures. No runtime
unit of work; no scale dimension applies.

**Q2** — No budget or limit. Pure test file change.

**Q3** — Scope: these two test files only. No other file is modified.

**Q4** — No reads or writes. N/A.

**Q5** — No inherited caps. N/A.

**Q6** — No concurrent paths. N/A.

## Tasks

- [ ] T1 — Story file created (this file), committed, pushed
- [ ] T2 — Run failing tests to confirm exact failure set before patching
- [ ] T3 — Patch `test_onboarding_endpoint.py`: `_fake_settings` + every `service.get_settings` mock block
- [ ] T4 — Patch `test_posthog_events.py`: `_mock_settings` fixture
- [ ] T5 — Run both test files: confirm 0 failures
- [ ] T6 — Run `tests/test_ces.py` guard
- [ ] T7 — Commit, push, open PR

## Change Log
- 2026-09-07: Story created (story-first BMAD gate)
