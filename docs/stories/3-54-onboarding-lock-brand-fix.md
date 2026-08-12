# Story 3-54 — Onboarding LLM lock deadlock + HIE rebrand fix

**Status:** in-progress
**Sprint:** Sprint 3
**Owner:** Dev 3
**Branch:** `sprint3/s3-54-onboarding-lock-brand-fix`
**Defects closed:** D71 (permanent lock), D72 (stale brand)

---

## Problem Statement

Two live bugs reported by Dev 2 after hitting them on a real account.

**Bug 1 — D71 — Permanent lock after LLM failure:**
`POST /api/assessment/onboarding/submit` → 409 Conflict forever, even though
`GET /api/assessment/user/dna` → 404 Not Found. Contradictory state; student
permanently locked out with no profile and no path forward.

Root cause: `process_onboarding()` Step 4 calls `generate_onboarding_profile()`
with no `try/except`. When the provider fails (rate limit, timeout, no credits),
a raw OpenAI SDK exception escapes. The router's cleanup only catches
`HTTPException`, so the Redis idempotency lock (`user:{id}:onboarding_done`)
stays set forever. Step 3's 20 `onboarding_responses` rows are already committed
when Step 4 runs, so releasing the lock alone is not enough — the retry's re-insert
immediately hits the unique constraint and 409s again.

Two independent fixes required:
1. Catch any exception from the LLM call; convert to `HTTPException(503)` so the
   router's existing cleanup fires (lock released).
2. Before raising, roll back the 20 orphaned `onboarding_responses` rows by
   `question_id` (precise delete, not a blanket `user_id` wipe) so the retry can
   re-insert cleanly.

The LLM provider's `complete()` already has `@with_retry(max_attempts=3)`.
Transient 429/5xx are already retried at that layer. The permanent lock only
occurs when all 3 attempts fail — the exception that escapes must be caught here.

**Bug 2 — D72 — Stale "TransformED" brand:**
`DPDP_DISCLAIMER` (shown verbatim on every Learner DNA page) and
`ONBOARDING_PROFILE_SYSTEM_PROMPT` (fed to GPT-4o-mini) both contain
"TransformED". GPT-4o-mini echoes the old name into `learner_dna.profile_text`
for every new onboarding submission. Existing `profile_text` rows in the DB still
carry the old name. Product is now HIE.

Fix: two string replacements in `prompts.py` + one SQL migration to backfill
existing `learner_dna.profile_text` rows.

---

## User Story

As a student who encounters an error during onboarding (network blip, provider
outage), I should be able to re-submit the onboarding form and get a working
profile — not be permanently locked out with contradictory 409/404 responses.

As a student viewing my Learner DNA, the brand name in my profile and the DPDP
disclaimer should say "HIE", not "TransformED".

---

## Acceptance Criteria

**AC1 — Lock released on LLM failure:**
When `generate_onboarding_profile()` raises any exception (including OpenAI SDK
errors after all retries), the Redis key `user:{user_id}:onboarding_done` must be
absent after the request returns. Test: mock the LLM to raise
`openai.RateLimitError`; call `process_onboarding()`; assert Redis key gone.

**AC2 — Orphaned rows rolled back on LLM failure:**
When the LLM call fails, all 20 `onboarding_responses` rows inserted in Step 3
must be deleted before the request returns. Test: mock LLM failure; assert DB has
0 rows for that user after request.

**AC3 — Retry after LLM failure succeeds:**
A second `POST /api/assessment/onboarding/submit` after a Step 4 LLM failure must
succeed with HTTP 200, a `learner_dna` row created, and no unique-constraint 409.
Test: simulate failure then success sequence end-to-end.

**AC4 — Response code on LLM failure is 503, not 500:**
The failed onboarding call must return `HTTP 503 Service Unavailable` (transient
outage semantics — client may retry) rather than 500. Test: assert response status.

**AC5 — DPDP disclaimer uses HIE brand:**
`DPDP_DISCLAIMER` must not contain the string "TransformED". Must contain "HIE".
Test: assert string content.

**AC6 — System prompt uses HIE brand:**
`ONBOARDING_PROFILE_SYSTEM_PROMPT` must not contain the string "TransformED".
Must contain "HIE". Test: assert string content.

**AC7 — DB backfill migration updates existing profile text:**
Migration `20260813000000_learner_dna_rebrand.sql` replaces "TransformED" with
"HIE" in any existing `learner_dna.profile_text` row. Test: assert migration SQL
contains the correct UPDATE/REPLACE pattern.

---

## Scale & Load

**Q1 — ONE unit of work and its range:**
One onboarding submission = 20 rows inserted to `onboarding_responses` + 1 GPT
call + 1 `learner_dna` upsert. The rollback path deletes exactly those 20 rows
(bounded by the 20 `question_id`s from the same request; `.in_("question_id", _question_ids)` is
a fixed-size IN clause, max 20 elements). Range is always exactly 20 rows;
never variable.

**Q2 — Fixed budgets while input varies:**
The Redis lock is a single key — no growth. The rollback `IN` clause is always 20
elements (the onboarding question set is fixed). The migration UPDATE is a one-time
batch — bounded by the total `learner_dna` row count (one row per user; typically
<10,000 at launch). No silent truncation.

**Q3 — Scope of every limit:**
- Redis lock: per user (keyed by `user_id`)
- Rollback delete: per user, per question set (20 rows max)
- Migration: per deployment (runs once at startup via Supabase)

**Q4 — Unbounded reads/writes:**
None introduced. The rollback delete uses `.eq("user_id", user_id).in_("question_id", _question_ids)` —
doubly bounded. The migration UPDATE is the only write; it runs once and is bounded by
the table row count.

**Q5 — Inherited caps re-derived:**
No caps inherited. The `with_retry(max_attempts=3)` in the LLM provider is an
existing cap; this story does not change it. The 20-question limit is fixed by the
onboarding form design, not this story.

**Q6 — Check-then-act concurrency:**
The Redis `SET NX` in the router is already atomic — no TOCTOU gap there.
The rollback delete (Step 4 failure path) runs within the same request context,
after the lock is held; no concurrent request can hold the same lock (SET NX
guarantees exclusivity). Safe.

---

## Tasks / Subtasks

- [ ] **T1 — RED: write failing tests (5 tests)**
  - [ ] T1.1 `test_onboarding_llm_failure_releases_redis_lock` — mock LLM to raise; assert key gone
  - [ ] T1.2 `test_onboarding_llm_failure_deletes_orphaned_rows` — assert 0 rows after failure
  - [ ] T1.3 `test_onboarding_retry_after_llm_failure_succeeds` — fail then succeed; assert 200 + DNA row
  - [ ] T1.4 `test_onboarding_llm_failure_returns_503` — assert response status 503
  - [ ] T1.5 `test_dpdp_disclaimer_uses_hie` — assert "HIE" in disclaimer, "TransformED" absent
  - [ ] T1.6 `test_system_prompt_uses_hie` — assert "HIE" in system prompt, "TransformED" absent
  - [ ] T1.7 `test_migration_sql_has_rebrand_update` — assert migration SQL content
- [ ] **T2 — GREEN: implement fixes**
  - [ ] T2.1 `service.py` — wrap Step 4 LLM call; on failure: delete orphaned rows, raise HTTPException(503)
  - [ ] T2.2 `prompts.py` — replace "TransformED" with "HIE" in `DPDP_DISCLAIMER` and `ONBOARDING_PROFILE_SYSTEM_PROMPT`
  - [ ] T2.3 `supabase/migrations/20260813000000_learner_dna_rebrand.sql` — backfill UPDATE
- [ ] **T3 — VERIFY: run full test suite, confirm all green**
- [ ] **T4 — UPDATE dev3-assessment-tracker.md**

---

## Dev Notes

### Files touched
| File | Change |
|---|---|
| `apps/api/app/modules/assessment/service.py` | Wrap Step 4 LLM call in try/except; rollback rows; raise HTTPException(503) |
| `apps/api/app/modules/assessment/prompts.py` | Replace 2× "TransformED" → "HIE" |
| `supabase/migrations/20260813000000_learner_dna_rebrand.sql` | UPDATE learner_dna backfill |
| `apps/api/tests/test_onboarding_llm_failure.py` | New test file (5+ tests) |

### service.py Step 4 patch pattern

```python
# Step 4 — Generate profile_text via GPT-4o-mini
provider = OpenAILLMProvider(lesson_id="onboarding")
try:
    profile_text = await generate_onboarding_profile(
        badge_labels=badge_labels,
        provider=provider,
    )
except Exception:  # noqa: BLE001
    logger.exception("onboarding: generate_onboarding_profile failed for user=%s", user_id)
    _question_ids = [r["question_id"] for r in rows]
    try:
        await asyncio.to_thread(
            lambda: supabase.table("onboarding_responses")
                .delete()
                .eq("user_id", user_id)
                .in_("question_id", _question_ids)
                .execute()
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "onboarding: rollback of onboarding_responses failed user=%s — "
            "user may need manual cleanup",
            user_id,
        )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Profile generation temporarily unavailable — please retry.",
    )
```

### Why 503 not 500?
`503 Service Unavailable` is the correct semantics for a transient provider outage —
tells the client (and Dev 2's frontend) this is retriable, not a permanent error.
`500 Internal Server Error` implies a code defect, not a provider outage.

### Why delete by question_id IN, not blanket user_id delete?
A blanket `eq("user_id", user_id)` would delete ALL of a user's historical
onboarding_responses, including from a legitimate previous session (e.g.,
a re-assessment flow). The IN clause is scoped to exactly the 20 rows this
request inserted. Safe even if `onboarding_responses` accumulates historical rows.

### Migration SQL pattern
```sql
UPDATE learner_dna
SET profile_text = REPLACE(profile_text, 'TransformED', 'HIE')
WHERE profile_text LIKE '%TransformED%';
```

### DPDP_DISCLAIMER target (after fix)
```
"This assessment reflects your personal learning preferences, not your intelligence
or capability. HIE Learner DNA is not a clinical assessment and does not diagnose
any learning or psychological condition. — Pursuant to DPDP Act 2023."
```

### ONBOARDING_PROFILE_SYSTEM_PROMPT change
Line 131: `"...learn more effectively in TransformED"` → `"...learn more effectively with HIE"`

---

## Dev Agent Record

### Completion Notes
*To be filled on completion.*

### Debug Log
*Empty.*

---

## Change Log

| Date | Change |
|---|---|
| 2026-08-13 | Story created (story-first gate) |
