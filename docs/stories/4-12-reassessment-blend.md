# Story 4-12 — Reassessment Blends Into Existing Learner DNA (D137 Fix)

**Status:** in-progress
**Branch:** `sprint4/s4-12-reassessment-blend`
**Defect:** D137 — Reassessment fully overwrites learner_dna instead of blending
**Owner:** Dev 3
**Sprint:** Sprint 4 (Weeks 8–9)

---

## Background

When a student re-takes the onboarding diagnostic after 10 sessions (`reassessment_due=true`),
`process_onboarding()` runs identically for first-time and reassessment paths:

- Step 5 upserts all 9 dimension scores from raw self-report (full overwrite)
- `session_count` is reset to `0` — destroying the accumulated count

This throws away all DNA fusion data accumulated across real behavioral sessions.
The D137 defect was identified by Dev 2 during Sprint 4 review.

**Root cause:** no branch exists in `process_onboarding()` for the reassessment path.

**Agreed fix (confirmed with team):** When an existing `learner_dna` row is present,
blend fresh self-report scores into existing scores via `_apply_ema()` (same EMA used
by `fuse_learner_dna`) and do NOT reset `session_count`.

---

## Acceptance Criteria

### Functional

**AC1 — First-time onboarding:** When no prior `learner_dna` row exists for the user,
the fresh self-report scores are written verbatim and `session_count` is set to 0.
(No change from current behaviour.)

**AC2 — Reassessment blend:** When an existing `learner_dna` row is present,
each of the 9 dimension scores is blended:
`blended = round(retain * old_score + (1 - retain) * new_score, 4)`
where `retain = settings.dna_ema_retain` (default 0.7).

**AC3 — session_count preserved:** On reassessment, the existing `session_count` value
is read from the DB and used unchanged in the upsert. It is never reset to 0.

**AC4 — badge_labels from blended scores:** Badge labels are recomputed from the blended
scores (not the raw self-report scores). A badge appears only when the blended score ≥ 70.

**AC5 — profile_text from blended scores:** The GPT-4o-mini profile is generated using
the blended scores' badge_labels. The DPDP Act 2023 disclaimer is still appended.

**AC6 — Upsert payload is complete:** The upsert to `learner_dna` contains all 9 dimension
columns, `badge_labels`, `profile_text`, `session_count`, and `last_updated`. No column
is silently omitted on either path.

**AC7 — Old scores unavailable degrades to first-time write:**
If the existing row cannot be read (DB error), the fallback is to write raw scores with
`session_count=0` — same as first-time onboarding. An explicit WARNING is logged.
This prevents a broken DB query from blocking reassessment entirely.

**AC8 — OnboardingResult returns correct session_count:**
`OnboardingResult.session_count` reflects the existing session_count (not 0) on reassessment.

### Security / Data Integrity

**AC9 — No new IDOR surface:** The existing row lookup is scoped to `user_id` from the
verified JWT. The `user_id` is never read from the request body.

**AC10 — onboarding_responses still written:** Step 3 (bulk-insert to `onboarding_responses`)
runs identically on both first-time and reassessment paths — the historical answers are
always stored.

**AC11 — D71 rollback still applies:** If Step 4 (LLM call) or Step 5 (upsert) fails,
the Step 3 `onboarding_responses` rows are still rolled back on error (D71 fix intact).

### Tests

**AC12 — Unit test: first-time path writes raw scores, session_count=0.**

**AC13 — Unit test: reassessment path blends scores via EMA formula, verifying each
of the 9 dimensions individually.**

**AC14 — Unit test: reassessment path preserves session_count from existing row.**

**AC15 — Unit test: if existing row SELECT returns None, falls back to first-time write
and logs WARNING.**

**AC16 — Existing `test_process_onboarding_success` (and all existing onboarding tests)
continue to pass without modification.**

---

## Scale & Load

**Q1 — What is ONE unit of work, and what is its range?**
One `process_onboarding()` call = 20 responses submitted by one user.
Range: always exactly 20 responses (enforced by `OnboardingDiagnosticSubmission`).
For reassessment: +1 SELECT from `learner_dna` (single row, keyed by `user_id` UNIQUE index).
The added SELECT reads exactly 0 or 1 rows. Min=0 (first-time), max=1 (reassessment).

**Q2 — Which budgets are FIXED while the input VARIES?**
`dna_ema_retain` env var (default 0.7) — fixed per deploy, applied once per dimension.
9 EMA computations are O(1) arithmetic. No budget breach possible.
No LLM calls are added by this fix. Profile generation cost is unchanged.

**Q3 — What is the SCOPE of every limit?**
The added SELECT is per-user, per-call. One user re-taking onboarding = 1 extra DB read.
The `learner_dna` table has a UNIQUE index on `user_id` — the lookup is an index scan, not a seq scan.

**Q4 — Which reads and writes are UNBOUNDED?**
None added. The SELECT reads at most 1 row (UNIQUE constraint makes it structurally bounded).
`# BOUNDED: learner_dna has UNIQUE(user_id) — at most 1 row returned by .eq("user_id").maybe_single()`

**Q5 — Which caps were INHERITED from an earlier design, and have they been re-derived?**
The `dna_ema_retain=0.7` constant was chosen for `fuse_learner_dna()` to weight behavioral
data at 30%. Reusing it for self-report blend is intentional: self-report is one more
EMA input, not a replacement. The retain value applies once, not per-session.

**Q6 — Is every check-then-act sequence safe under CONCURRENT requests?**
The reassessment path's Redis SET NX idempotency guard (router level) prevents concurrent
reassessment submissions for the same user. The learner_dna SELECT + upsert is already
protected by that gate — no additional TOCTOU surface is introduced.

---

## Implementation Notes

**File changed:** `apps/api/app/modules/assessment/service.py` — `process_onboarding()` only.

**New helper import:** `_apply_ema` from `apps/api/app/modules/assessment/dna_fusion.py`.
`ALL_NINE_DIMENSIONS` (already imported) used to iterate dimensions.

**New SELECT before Step 1:**
```python
existing = await _fetch_existing_dna(user_id=user_id, supabase=supabase)
```

**Blend logic (added between Step 1 and Step 2):**
```python
is_reassessment = existing is not None
if is_reassessment:
    retain = get_settings().dna_ema_retain
    existing_session_count = int(existing.get("session_count") or 0)
    for dim in ALL_NINE_DIMENSIONS:
        scores[dim] = _apply_ema(existing.get(dim), scores[dim], retain)
```

**Step 5 upsert uses `session_count = existing_session_count if is_reassessment else 0`.**

**No changes to router.py** — the reassessment bypass (delete onboarding_done key) is
already present and correct (Story 3-31). This story fixes only the service layer.

**No new migration required** — all columns already exist in `learner_dna`.

---

## Test File

`apps/api/tests/unit/test_reassessment_blend.py`
