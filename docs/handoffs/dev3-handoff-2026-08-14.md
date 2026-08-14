# Dev 3 — Handoff: Story 3-55 fallout + open defects

**From:** Dev 1, after merging `sprint3/s3-55-learner-dna-production-gaps` into `main` and
resolving two real ID collisions in `docs/DEFECT-REGISTER.md`.
**Date:** 2026-08-14
**Where things stand:** merge is clean, pushed (`bff389b`), zero failures attributable to the
merge conflict resolution itself. But Story 3-55 landed with **two real regressions of its own**
that are still sitting on `main`, plus **one duplicate register entry** (already resolved below —
just needs you to close it). None of this blocks anything of mine — it's yours to prioritize.

---

## Your one-line status

Story 3-55 fixed three real defects (now D102/D103/D104, renumbered — see below) but its own
`.order("created_at")` addition broke 29 pre-existing tests via a mock-chain gap, and its new
UUID validator broke 3 more via non-UUID test fixtures. **32 new failures on `main`, both
self-inflicted by this story, both mechanical to fix.**

---

## Renumbering note — read this before you search the register by ID

Story 3-55 registered its own findings as **D92–D97**. Those IDs collided with six *different*
Dev 3 defects (originally D74–D80) that got renumbered to **D92–D101** earlier the same day, in
a separate branch that merged first. I renumbered **Story 3-55's set to D102–D107** on merge —
your code comments, test names, and the register rows all now say `D102 (was D92)` etc. If you
have any local notes, Slack messages, or half-written follow-up branches referencing D92–D97 for
Story 3-55's work, they now mean **D102–D107**. Full mapping:

| Was | Now | Defect |
|---|---|---|
| D92 | **D102** | `session_events` SELECT had no `.limit()` — fixed |
| D93 | **D103** | `dna_fusion.py` excluded from CI unbounded-query scanner — fixed |
| D94 | **D104** | `SessionCreate.lesson_id` had no UUID validator — fixed (but see Issue 2 below) |
| D95 | **D105** | EMA `session_count` read-modify-write race — deferred (but see Issue 3 below) |
| D96 | **D106** | `quiz_attempts` accuracy counts all retakes, not latest attempt — deferred, Sprint 4 |
| D97 | **D107** | `teachback_attempts` unlimited retakes, uncapped LLM cost — deferred, Sprint 4 |

---

## Issue 1 — `.order("created_at")` broke 29 pre-existing tests via a mock-chain gap

**Root cause, confirmed by running the actual failure:** `dna_fusion.py` now builds these chains
(`dna_fusion.py:274-279`, `:296-301`, `:317-322`):

```python
supabase.table("quiz_attempts").select(...).eq("session_id", session_id)
    .order("created_at").limit(10_000).execute()
```

Every pre-existing test mock stops at `.eq(...).execute` (or `.eq(...).limit(...).execute` for
`session_events`) — there is no `.order(...)` in the mocked chain. Calling `.order("created_at")`
on a bare `MagicMock` returns a **new, unconfigured child mock**, so `.limit().execute()` off of
it returns a default `MagicMock` instead of your fixture data. `dna_fusion.py:96`
(`accuracy = correct / len(quiz_rows)`) then divides by zero because `quiz_rows` silently came
back empty.

**Confirmed via a real pytest run** (`test_dna_fusion.py::test_async_happy_path_returns_9_dimension_dict`):

```
app/modules/assessment/dna_fusion.py:96: in _compute_signals
    accuracy = correct / len(quiz_rows)
E   ZeroDivisionError: division by zero
```

**Every affected mock, by file and line** (line numbers are the `elif name == "..."` branch
header; the mock assignment itself is 1 line below each):

| File | `quiz_attempts` | `teachback_attempts` | `session_events` |
|---|---|---|---|
| `tests/test_dna_fusion.py` | line 91 | line 94 | line 97 |
| `tests/test_dna_fusion_event_aggregation.py` | line 130 | line 134 | line 138 |
| `tests/test_dna_fusion_real_session.py` | line 66 | line 69 | line 72 |
| `tests/test_dna_growth.py` | line 135 | line 137 | line 139 |
| `tests/test_reassessment_flag.py` | line 90 | line 92 | line 94 |

**The fix — same shape for `quiz_attempts` and `teachback_attempts` everywhere**, e.g.
`test_dna_fusion.py:92` (the assignment under the `elif` at line 91):

```python
# before (broken — missing .order in the chain)
tbl.select.return_value.eq.return_value.execute.return_value = _resp(quiz_rows)

# after
tbl.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = _resp(quiz_rows)
```

And for `session_events` in 4 of the 5 files (already had `.limit`, just needs `.order` inserted
before it):

```python
# before
tbl.select.return_value.eq.return_value.limit.return_value.execute.return_value = _resp(event_rows)

# after
tbl.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = _resp(event_rows)
```

**Exception: `test_reassessment_flag.py`'s `session_events` branch (lines 94-96) is different —
it has no `.limit()` in the chain at all**, unlike the other 4 files:

```python
# before (this one has NEITHER .order NOR .limit — the other 4 files at least have .limit)
tbl.select.return_value.eq.return_value.execute.return_value = _resp([])

# after — needs BOTH inserted, not just .order
tbl.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = _resp([])
```

Applying the generic "just add `.order`" fix to this one branch will silently not fix it — the
missing `.limit()` still leaves the chain shape wrong.

**29 tests, all currently red for this exact reason** — full list, verified via a real regression
diff against the pre-Story-3-55 baseline (74 → 106 failures, these 29 plus the 3 in Issue 2 are
the entire delta):

<details>
<summary>29 tests (click to expand)</summary>

```
tests/test_dna_fusion.py::test_async_data_read_failure_is_non_fatal
tests/test_dna_fusion.py::test_async_happy_path_returns_9_dimension_dict
tests/test_dna_fusion.py::test_async_no_dna_row_uses_neutral_old
tests/test_dna_fusion.py::test_async_session_count_incremented
tests/test_dna_fusion.py::test_async_upsert_failure_raises_503
tests/test_dna_fusion_event_aggregation.py::test_fuse_event_aggregation_3_jargon_hovers_exact_curiosity_ema
tests/test_dna_fusion_event_aggregation.py::test_fuse_event_aggregation_4_jargon_hovers_distinct_from_cap_and_3_event
tests/test_dna_fusion_event_aggregation.py::test_fuse_event_aggregation_all_four_event_types_exact_ema_all_dims
tests/test_dna_fusion_event_aggregation.py::test_fuse_event_aggregation_empty_string_event_type_filtered
tests/test_dna_fusion_event_aggregation.py::test_fuse_event_aggregation_events_read_failure_alone_is_non_fatal
tests/test_dna_fusion_event_aggregation.py::test_fuse_event_aggregation_unknown_event_type_is_harmless
tests/test_dna_fusion_real_session.py::test_fuse_learner_dna_redis_failure_is_non_fatal
tests/test_dna_fusion_real_session.py::test_fuse_learner_dna_redis_reassessment_flag_at_session_10
tests/test_dna_fusion_real_session.py::test_fuse_learner_dna_upsert_payload_contains_exact_ema_values
tests/test_dna_growth.py::test_fuse_learner_dna_calls_record_dna_growth_after_upsert
tests/test_dna_growth.py::test_fuse_learner_dna_growth_failure_does_not_prevent_return
tests/test_dna_growth.py::test_fuse_learner_dna_old_dims_for_growth_none_on_first_session
tests/test_reassessment_flag.py::test_fuse_dna_does_not_set_flag_at_session_1
tests/test_reassessment_flag.py::test_fuse_dna_does_not_set_flag_at_session_11
tests/test_reassessment_flag.py::test_fuse_dna_does_not_set_flag_at_session_19
tests/test_reassessment_flag.py::test_fuse_dna_does_not_set_flag_at_session_5
tests/test_reassessment_flag.py::test_fuse_dna_does_not_set_flag_at_session_9
tests/test_reassessment_flag.py::test_fuse_dna_redis_failure_is_non_fatal
tests/test_reassessment_flag.py::test_fuse_dna_redis_none_skips_step7
tests/test_reassessment_flag.py::test_fuse_dna_redis_param_defaults_to_none
tests/test_reassessment_flag.py::test_fuse_dna_sets_flag_at_session_10
tests/test_reassessment_flag.py::test_fuse_dna_sets_flag_at_session_20
tests/test_reassessment_flag.py::test_fuse_dna_sets_flag_at_session_30
tests/test_reassessment_flag.py::test_log_injection_prevention_strips_newlines
```

</details>

**Why this is worth a shared helper, not five separate patches:** this is the second time a
`dna_fusion.py` chain-shape change has broken five independent hand-rolled mocks (the first was
this session's own `.limit()` addition, caught before merge). Consider factoring
`_supabase_mock`/`_table` into one shared test fixture (e.g. `tests/conftest.py` or a
`tests/_dna_fusion_mock.py` helper) so the next chain change updates one place instead of five.
Not blocking — just flagging the pattern since it's now repeated.

---

## Issue 2 — new UUID validator rejects this codebase's own non-UUID test fixtures

**Root cause:** `SessionCreate.lesson_id_must_be_uuid` (`schemas.py:58-72`, your new validator)
correctly rejects any string that isn't a real UUID. But `tests/test_t26_api_contract_dev2.py`
has used `"lesson-001"` as its placeholder `lesson_id` since it was written — module-level
constant `_VALID_SESSION_PAYLOAD = {"lesson_id": "lesson-001"}` at **line 86**, plus inline uses
at lines 90, 97, 158, 192, 301.

**Confirmed via a real request:**

```
POST /sessions {"lesson_id": "lesson-001"}
→ 422 {"detail":[{"type":"value_error","loc":["body","lesson_id"],
       "msg":"Value error, lesson_id must be a valid UUID ..., got: 'lesson-001'", ...}]}
```

**3 tests fail on this:**
```
tests/test_t26_api_contract_dev2.py::test_sessions_extra_user_id_body_not_rejected
tests/test_t26_api_contract_dev2.py::test_sessions_returns_201_with_correct_fields
tests/test_t26_api_contract_dev2.py::test_user_id_body_field_never_trusted
```

**This is your call, not a mechanical fix** — two real options:
1. **Fix the fixtures** (`"lesson-001"` → a real UUID string, e.g.
   `"123e4567-e89b-12d3-a456-426614174000"`) — probably the more correct direction, since
   `lesson_id` really is a UUID column in production and the validator is doing its job.
2. **Loosen the validator** if there's a reason `lesson_id` needs to accept non-UUID strings
   somewhere I'm not aware of.

I did not pick a direction — this is squarely your module and your validator.

---

## Issue 3 — D105 is a confirmed stale duplicate of D93 (already fixed) — close it

D105 (renumbered from D95, still marked **Deferred — Sprint 4**) describes the exact same defect
as **D93** in this register: `fuse_learner_dna`'s `session_count` Python-side read-modify-write
race. I originally left this as a "you should check" item, then re-verified it directly instead
of asking you to:

- `dna_fusion.py`'s `upsert_payload` (lines 380-383) contains only `user_id` and the 9 EMA
  dimensions — `session_count` is genuinely **not** in it, with a comment at 376-379 explaining
  why (`"D93 (was D74): session_count is intentionally absent..."`).
- Step 5b (lines 413-427) genuinely calls
  `supabase.rpc("increment_learner_dna_session_count", {"p_user_id": str(user_id)})` in a
  non-fatal try/except.
- The migration (`supabase/migrations/20260813000001_dna_session_count_atomic_increment.sql`)
  genuinely creates `increment_learner_dna_session_count(p_user_id uuid)` doing exactly
  `UPDATE public.learner_dna SET session_count = session_count + 1 WHERE user_id = p_user_id` —
  a single atomic statement, so concurrent calls serialize correctly at the DB level.

**D93's FIXED-GUARDED status is accurate. D105 is a stale duplicate — just close it**, pointing
at D93, rather than spending time re-deriving the fix.

One unrelated residual worth a glance while you're in there: Python `old_session_count + 1`
arithmetic still exists at lines 448 and 469, but only for the Redis reassessment-flag threshold
check and a log line — never for the persisted DB value. That's a different, lower-stakes
quantity than what D93/D105 describe, not blocking, just flagging so it doesn't look like the RMW
bug survived somewhere.

---

## Already-registered, lower priority (no urgency, just listed for completeness)

- **D106** (was D96) — `quiz_attempts` accuracy computed over all retakes, not latest attempt.
  Deferred to Sprint 4, has an owner and trigger already.
- **D107** (was D97) — `teachback_attempts` unlimited retakes + uncapped per-retake LLM cost.
  Deferred to Sprint 4, has an owner and trigger already.
- **D59(b)** — `analytics/service.py` unbounded query, still open. (D59(a), the admin cost-report
  one, is mine and already closed.)

---

## What's NOT yours — don't spend time chasing these

The full regression run shows **106 failures total**, but only the 32 above are new from Story
3-55. The other **74 are a pre-existing baseline** (confirmed by running tests against the commit
immediately before Story 3-55 merged — same 74 failures, same tests). Most of that 74 lives in
Dev 4's tutor/CES files: `test_tutor_service.py` (`UnboundLocalError`), `test_tutor_graph.py`,
`test_websocket_session.py`, `test_s3_45_fatigue_trigger.py`, `test_s3_49_ces_history_timestamps.py`,
and similar. Not yours, not new, not something this handoff is asking you to touch.

---

## Suggested order

1. Issue 1 (mechanical, ~10 minutes, unblocks 29 tests — watch the `test_reassessment_flag.py`
   exception above)
2. Issue 2 (your call on direction, then apply it, ~5 minutes)
3. Issue 3 (already resolved above — just close D105 in the register, ~1 minute)
4. D106/D107 whenever Sprint 4 planning gets to them

None of this is blocking my side.

---

## Verification note

Every claim in this document — line numbers, chain shapes, failing-test lists, the 74/32/106
breakdown, and the D93/D105 resolution — was independently re-executed after the first draft (not
just re-read) via 5 parallel agents that re-ran the actual tests, re-derived the baseline from a
fresh worktree at the pre-Story-3-55 commit, and read the current code directly rather than
trusting the draft's prose. Two real gaps were caught and fixed (the `test_reassessment_flag.py`
`session_events` exception, and an off-by-one in one illustrative line citation); everything else
matched exactly.
