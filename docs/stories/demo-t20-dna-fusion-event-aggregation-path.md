# Demo T20 — Learner DNA Fusion: event aggregation DB path with non-empty event_rows

**Status:** done
**Sprint:** Demo Sprint
**Owner:** Dev 3
**Branch:** `dev3-demo-t20-phaseL5`
**Depends on:** T19 (DNA fusion real session events), D94 (was D75) (event aggregation coverage gap)

---

## Problem Statement

`test_dna_fusion.py` (Story 3-25) and `test_dna_fusion_real_session.py` (Demo T19) together
have 37 passing tests for `fuse_learner_dna`. None of them verify that the **event aggregation
counting loop** in `dna_fusion.py` (lines 301–306) correctly converts `event_rows` from the
Supabase mock into `event_counts` that propagate to the final upsert payload.

**The specific gap (D94 (was D75)):**

```python
event_counts: dict[str, int] = {}
for r in event_rows:
    t = r.get("event_type", "")
    if t:
        event_counts[t] = event_counts.get(t, 0) + 1
```

- `test_async_happy_path_returns_9_dimension_dict` passes `event_rows=[{"event_type":
  "jargon_hover"}, {"event_type": "jargon_hover"}]` but only asserts `0 ≤ v ≤ 100`.
  A bug that counts all events as 1 (instead of 2) produces a different EMA value that
  still passes the weak assertion.
- All `fuse_learner_dna` integration tests in T19 pass `event_rows=[]` — the counting
  loop is exercised with the empty-list trivial case only.

A regression in this loop (wrong dict key, off-by-one, missing `if t:` filter) is invisible
to the current test suite. T20 closes D94 (was D75) with 6 tests that assert concrete, arithmetically-derived
EMA values that depend on the counting loop being correct.

---

## Acceptance Criteria

### AC1 — 3 jargon_hover events → curiosity_index EMA = 32.0 in upsert payload

**Given** `event_rows = [{"event_type": "jargon_hover"}] * 3` (3 rows),
a prior `learner_dna` row with `curiosity_index = 20.0`, and `retain = 0.7`,
**When** `fuse_learner_dna` is called (session has `ended_at` set),
**Then** the captured upsert payload must have:
- `curiosity_index == pytest.approx(32.0, rel=1e-3)`
  — formula: signal = (3/5)*100 = 60.0; EMA = round(0.7×20.0 + 0.3×60.0, 4) = 32.0

*Why:* A counting bug that counts all events as 1 regardless of actual row count produces
signal=(1/5)*100=20.0, EMA=round(0.7×20.0+0.3×20.0,4)=20.0 ≠ 32.0 → test fails, bug caught.

### AC2 — 4 jargon_hover events → curiosity_index signal = 80.0, not 60.0 or 100.0

**Given** `event_rows = [{"event_type": "jargon_hover"}] * 4` (exactly `_JARGON_CAP - 1 = 4`),
a prior `learner_dna` row with `curiosity_index = 50.0`, and `retain = 0.7`,
**When** `fuse_learner_dna` is called,
**Then**:
- signal = (4/5)*100 = 80.0
- `curiosity_index` in upsert == `pytest.approx(round(0.7*50.0 + 0.3*80.0, 4), rel=1e-3)`
  = `pytest.approx(59.0, rel=1e-3)`
- Verify it is NOT the cap-value (100.0) and NOT the 3-event value (60.0-based)

*Why:* Distinguishes between count=3, count=4, count=5 (cap) — catches off-by-one in the loop.

### AC3 — Unknown event_type is harmless: fuse succeeds, known dims unaffected

**Given** `event_rows = [{"event_type": "unknown_event_type_xyz"}, {"event_type": "another_unknown"}]`,
no prior `learner_dna` row (first session), quiz_rows=[], tb_rows=[],
**When** `fuse_learner_dna` is called,
**Then**:
- No exception raised (the `if t:` guard + `event_counts.get(key, 0)` in `_compute_signals` mean
  unknown types are counted but never read → silent, no KeyError)
- Return value is not None
- `curiosity_index` == `pytest.approx(round(0.7*50.0 + 0.3*0.0, 4), rel=1e-3)` = 35.0
  (0 jargon_hover events despite non-empty event_rows → curiosity signal = 0.0 → neutral EMA from 50.0)

*Why:* Guards against future event types breaking the fusion loop. Also verifies that the 
counting loop runs to completion (no early exit or crash) when unknown types appear.

### AC4 — event_type empty string filtered by `if t:` guard

**Given** `event_rows = [{"event_type": ""}, {"event_type": "jargon_hover"}, {"event_type": ""}]`,
a prior `learner_dna` row with `curiosity_index = 0.0`, `retain = 0.7`,
**When** `fuse_learner_dna` is called,
**Then**:
- Only 1 jargon_hover is counted (the two empty strings are filtered)
- `curiosity_index` in upsert == `pytest.approx(round(0.7*0.0 + 0.3*20.0, 4), rel=1e-3)` = 6.0
  — signal = (1/5)*100 = 20.0; EMA = round(0.0 + 0.3*20.0, 4) = 6.0

*Why:* The `if t:` guard on line 305 of `dna_fusion.py` exists precisely to filter these. If it
were removed, the empty string would be stored in `event_counts` under key `""`, which `_compute_signals`
doesn't read — the signal would still be correct. But the guard is part of the production contract
and removing it could introduce subtle dict pollution in future refactors. Testing it explicitly
pins the behaviour.

### AC5 — session_events DB read failure → event_counts={} → neutral signals → upsert succeeds

**Given** only the `session_events` table read raises an `Exception` (quiz_attempts and
teachback_attempts succeed with empty lists), a prior `learner_dna` row with **all dimensions
= 50.0** (including `curiosity_index = 50.0`),
**When** `fuse_learner_dna` is called,
**Then**:
- No exception raised (non-fatal path per production code line 298–300)
- Return value is a dict with exactly 9 dimensions
- `curiosity_index` in upsert == `pytest.approx(35.0, rel=1e-3)`
  — signal=0.0 (empty event_counts); old=50.0; EMA=round(0.7×50.0+0.3×0.0,4)=35.0

*Why:* AC18 in `test_dna_fusion.py` fails all three reads simultaneously. This test isolates
the individual `session_events` read failure to verify the fallback path independently.
A code change that accidentally makes the events read fatal (e.g., removing the try/except)
would be caught.

### AC6 — All four event types in one session: exact EMA for all four signal dims verified

**Given** `event_rows` containing:
- 3 × `jargon_hover`
- 2 × `help_seeking`
- 1 × `skip_segment`
- 1 × `intervention_triggered`

A prior `learner_dna` row:
```
curiosity_index = 40.0
help_seeking = 50.0
study_independence = 50.0
goal_orientation = 80.0
frustration_tolerance = 90.0
```
`retain = 0.7`, all other dims = 50.0 (neutral),

**When** `fuse_learner_dna` is called with quiz_rows=[], tb_rows=[],
**Then** the captured upsert payload must match all of the following:
- `curiosity_index`: signal=(3/5)*100=60.0; EMA=round(0.7×40.0+0.3×60.0,4)=**46.0**
- `help_seeking`: signal=(1/4)*100=25.0; EMA=round(0.7×50.0+0.3×25.0,4)=**42.5** (≠50.0 neutral — verifies loop)
- `study_independence`: signal=100.0-25.0=75.0; EMA=round(0.7×50.0+0.3×75.0,4)=**57.5** (≠50.0 — verifies inversion)
- `goal_orientation`: signal=100-(1/4)*100=75.0; EMA=round(0.7×80.0+0.3×75.0,4)=**78.5**
- `frustration_tolerance`: signal=100-(1/3)*100≈66.667; EMA=round(0.7×90.0+0.3×66.667,4)=**83.0** exactly (IEEE 754)

*Why:* This is the comprehensive D94 (was D75) closure — verifies that all four event-type signal
dimensions are correctly computed end-to-end from DB event_rows through the counting loop
to the upsert payload. A single regression in any event-type's key name, counting logic,
or signal formula causes at least one assertion to fail.

---

## Scale & Load

**Q1 — What is ONE unit of work, and what is its range?**
One unit = one `fuse_learner_dna` call in a test. `event_rows` ranges from 0 to N where N
is bounded by session length (≤ a few hundred events per session in practice). Tests use N ≤ 7.

**Q2 — Which budgets are FIXED while the input VARIES?**
`_JARGON_CAP`, `_HELP_CAP`, `_SKIP_CAP`, `_INTERVENTION_CAP` are compile-time constants.
When event counts exceed the cap, the signal is clamped to 100.0 (explicit, not silent).
T20 is tests-only — no new budgets introduced.

**Q3 — What is the SCOPE of every limit?**
All limits in `dna_fusion.py` are per-session, per-user. Tests are isolated per function
(no shared state). Scope is N/A for test code.

**Q4 — Which reads and writes are UNBOUNDED?**
The mock event_rows list is fixed-size in every test. No production reads are introduced. N/A.

**Q5 — Which caps were INHERITED from an earlier design?**
`_JARGON_CAP=5`, `_HELP_CAP=4`, `_SKIP_CAP=4`, `_INTERVENTION_CAP=3` — all defined in
Story 3-25, Sprint 2. T20 exercises intermediate values (not just cap/zero), which is the
gap D94 (was D75) identified. No re-derivation needed — tests exercise constants, not change them.

**Q6 — Is every check-then-act sequence safe under CONCURRENT requests?**
T20 is tests-only. The `session_events` read is a plain SELECT; concurrent reads are safe
at DB level. The Python-layer race on `session_count` (D93 (was D74)) is pre-existing and unrelated to
the event aggregation path T20 adds coverage for.

---

## Tasks

- [x] **T1 — STORY: Create `docs/stories/demo-t20-dna-fusion-event-aggregation-path.md`** — ✓ 2026-08-13
  - Story-first commit (no implementation in same commit)

- [x] **T2 — IMPLEMENT: Write `apps/api/tests/test_dna_fusion_event_aggregation.py` (6 tests)** — ✓ 2026-08-13
  - AC1: 3 jargon_hover → curiosity_index EMA = 32.0 in upsert
  - AC2: 4 jargon_hover → curiosity_index EMA = 59.0, not 60.0-based or cap-based
  - AC3: unknown event_type → harmless, curiosity_index reflects 0 known events
  - AC4: empty-string event_type filtered → only real jargon_hover counted
  - AC5: session_events read failure alone → non-fatal, returns 9 dims
  - AC6: all four event types → exact EMA for all four signal dims (help=1 event→42.5≠neutral)

- [x] **T3 — VERIFY: run full test suite, confirm no regressions** — ✓ 2026-08-13
  - 6/6 T20 tests PASS; assessment module regression GREEN

---

## Dev Notes

### Patch targets

- Production code under test: `apps/api/app/modules/assessment/dna_fusion.py`
- Test file to create: `apps/api/tests/test_dna_fusion_event_aggregation.py`
- No production code changes — tests-only story

### Mock pattern (from T19 P2 — list-based upsert capture)

Use the same table-routing pattern as T19/T18:

```python
def _supabase_mock(
    *,
    session_row: dict,
    event_rows: list[dict],
    dna_row: dict | None,
    quiz_rows: list[dict] | None = None,
    tb_rows: list[dict] | None = None,
    capture_upsert: list[dict] | None = None,
    events_raises: bool = False,
) -> MagicMock:
    supabase = MagicMock()

    def _resp(data):
        r = MagicMock()
        r.data = data
        r.error = None
        return r

    def _spy_upsert(payload, **kwargs):
        if capture_upsert is not None:
            capture_upsert.append(dict(payload))
        m = MagicMock()
        m.execute.return_value = _resp([])
        return m

    def _table(name: str) -> MagicMock:
        tbl = MagicMock()
        if name == "sessions":
            (tbl.select.return_value
                 .eq.return_value
                 .maybe_single.return_value
                 .execute.return_value) = _resp(session_row)
        elif name == "quiz_attempts":
            tbl.select.return_value.eq.return_value.execute.return_value = _resp(quiz_rows or [])
        elif name == "teachback_attempts":
            tbl.select.return_value.eq.return_value.execute.return_value = _resp(tb_rows or [])
        elif name == "session_events":
            if events_raises:
                tbl.select.return_value.eq.return_value.execute.side_effect = Exception(
                    "events DB down"
                )
            else:
                tbl.select.return_value.eq.return_value.execute.return_value = _resp(event_rows)
        elif name == "learner_dna":
            (tbl.select.return_value
                 .eq.return_value
                 .maybe_single.return_value
                 .execute.return_value) = _resp(dna_row)
            if capture_upsert is not None:
                tbl.upsert.side_effect = _spy_upsert
            else:
                tbl.upsert.return_value.execute.return_value = _resp([])
        return tbl

    supabase.table.side_effect = lambda name: _table(name)
    return supabase
```

### asyncio.to_thread shim

`fuse_learner_dna` uses `asyncio.to_thread()` for all Supabase calls. In tests, the
MagicMock is synchronous so `to_thread(lambda: ...)` returns the lambda's result wrapped in
a coroutine. This works automatically in `asyncio_mode = "auto"` (no patching needed).

### EMA arithmetic reference (AC6)

All values derived from constants in `dna_fusion.py`:
- `_JARGON_CAP = 5`, `_HELP_CAP = 4`, `_SKIP_CAP = 4`, `_INTERVENTION_CAP = 3`
- `_NEUTRAL = 50.0`, `retain = 0.7`

| event_type | count | signal formula | signal | old | EMA |
|---|---|---|---|---|---|
| jargon_hover | 3 | (3/5)*100 | 60.0 | 40.0 | round(0.7×40+0.3×60,4)=46.0 |
| help_seeking | 1 | (1/4)*100 | 25.0 | 50.0 | round(0.7×50+0.3×25,4)=**42.5** |
| skip_segment | 1 | 100-(1/4)*100 | 75.0 | 80.0 | round(0.7×80+0.3×75,4)=78.5 |
| intervention | 1 | 100-(1/3)*100 | 66.6̄ | 90.0 | round(0.7×90+0.3×66.6̄,4)=83.0 |
| study_independence | — | 100-help_signal | 75.0 | 50.0 | round(0.7×50+0.3×75,4)=**57.5** |

Note: `help_seeking` uses count=1 (not 2) so signal=25.0 ≠ _NEUTRAL=50.0. With count=2,
signal=50.0=_NEUTRAL → EMA=50.0, indistinguishable from a neutral fallback or wrong-key bug.

For AC6 `frustration_tolerance`: signal = 100 - (1/3)*100 ≈ 66.6̄.
IEEE 754: round(0.7×90.0 + 0.3×(100-(1/3)×100), 4) = round(63.0 + 20.000000000000004, 4) = **83.0** exactly.
Use `pytest.approx(frustration_ema, rel=1e-3)` — consistent with all other assertions.

### Known pre-existing test failure (D95 (was D76))

`test_dna_fusion.py::test_positional_args_raise_type_error` — uses `asyncio.get_event_loop().run_until_complete()` which fails in Python 3.12 with `asyncio_mode=auto`. Pre-existing from Story 3-25; not introduced by T20. Also in `test_dna_growth.py::test_positional_args_raise_type_error` and `test_dna_growth.py::test_record_dna_growth_inserts_9_rows_for_all_dims` (same pattern). Expected count: 3 pre-existing failures total. Registered as **D95 (was D76)** in `docs/DEFECT-REGISTER.md`.

---

## Senior Developer Review (AI)

**Review date:** 2026-08-13
**Outcome:** Approve (8 patches applied)
**Layers run:** 6 — Story Quality, Blind Hunter, AC Completeness, Edge Case Hunter, Process Integrity, Scale & Load Hunter

### Action Items (all resolved before commit)

- [x] **P1 (HIGH)** — Wire `session_events` INSERT chain in mock so `record_dna_growth` (Step 6) does not silently fail in all 6 tests. Added `tbl.insert.return_value.execute.return_value = _resp([])`.
- [x] **P2 (MED)** — Assert `on_conflict="user_id"` in `_spy_upsert`. Without this, changing to `on_conflict="id"` would create duplicate `learner_dna` rows silently.
- [x] **P3 (MOD)** — AC6 `help_seeking` count changed 2→1. Count=2 produces signal=50.0=_NEUTRAL; EMA=50.0 is indistinguishable from a neutral fallback bug. Count=1 → signal=25.0 → EMA=42.5 ≠ 50.0. Also verifies `study_independence` inversion (57.5 ≠ 50.0).
- [x] **P4 (LOW)** — AC2: added spec-pin literal `assert expected_ema == pytest.approx(59.0, rel=1e-6)` (consistent with AC1/AC3/AC4 pattern).
- [x] **P5 (LOW)** — Fixed `# ≈ 83.0001` comment (actual IEEE 754 result is 83.0 exactly). Changed `rel=1e-2` → `rel=1e-3` for frustration_tolerance (consistent with all other assertions).
- [x] **P6 (MOD)** — Added `# MOCK-CONTRACT:` comment to AC4 explaining that the `if t:` guard is untestable via EMA output alone (`_compute_signals` ignores unknown keys via `.get()`).
- [x] **P7 (LOW)** — AC5 story text updated to pin prior `curiosity_index=50.0` and expected EMA=35.0.
- [x] **P8 (VIOLATION)** — Registered D95 (was D76) (3 pre-existing asyncio.get_event_loop() failures) in defect register; added `(D95 (was D76))` reference to Dev Notes paragraph (Process Integrity binding rule 5).

### Deferred findings (pre-existing, not introduced by T20)

- **D96 (was D77)** (Scale & Load Q4): `session_events` SELECT in `dna_fusion.py` has no `.limit()`. 50,000 events → all rows materialised; no error raised. Pre-existing; fix: add `.limit(10000)` + `# BOUNDED:` justification.
- **D99 (was D78)** (Scale & Load guard gap): `test_unbounded_queries.py` `REQUEST_PATH_FILENAMES` excludes `dna_fusion.py`. D96 (was D77) and similar unbounded reads in `dna_fusion.py`, `ces.py`, `dna_growth.py` are invisible to CI. Pre-existing; fix: add `dna_fusion.py` to scanned filenames or switch to module-directory scan.
- **Blind Hunter F1** (IDOR guard never tested): `fuse_learner_dna` ownership check at lines 242–246 has no cross-user test case. Pre-existing gap in the assessment test suite; separate story.
- **Blind Hunter F2** (mock `.eq()` args unverified): all 5 mock query chains accept any column/value in `.eq()` — filter regression is invisible. Systemic mock pattern issue across assessment tests; separate story.

---

## Change Log

| Date | Change |
|------|--------|
| 2026-08-13 | Story created — T20 scope: D94 (was D75) event aggregation DB path, 6 ACs |
