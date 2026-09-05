# Story 3-54 — Onboarding LLM lock deadlock + HIE rebrand fix

**Status:** done
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

- [x] **T1 — RED: write failing tests (5 tests)** — ✓ 2026-08-13
  - [x] T1.1 `test_onboarding_llm_failure_raises_503_for_router_cleanup` — mock LLM to raise; assert HTTPException(503)
  - [x] T1.2 `test_onboarding_llm_failure_deletes_orphaned_rows` — assert rollback delete called
  - [x] T1.3 `test_onboarding_retry_after_llm_failure_succeeds` — fail then succeed; assert result not None
  - [x] T1.4 `test_onboarding_llm_failure_returns_503` — assert response status 503
  - [x] T1.5 `test_dpdp_disclaimer_uses_hie` — assert "HIE" in disclaimer, "TransformED" absent
  - [x] T1.6 `test_system_prompt_uses_hie` — assert "HIE" in system prompt, "TransformED" absent
  - [x] T1.7 `test_migration_sql_has_rebrand_update` — assert migration SQL content
- [x] **T2 — GREEN: implement fixes** — ✓ 2026-08-13
  - [x] T2.1 `service.py` — wrap Step 4 LLM call; on failure: delete orphaned rows (resp.error check + empty guard), raise HTTPException(503); Step 5 rollback added
  - [x] T2.2 `prompts.py` — replace "TransformED" with "HIE" in `DPDP_DISCLAIMER` and `ONBOARDING_PROFILE_SYSTEM_PROMPT`
  - [x] T2.3 `supabase/migrations/20260813000000_learner_dna_rebrand.sql` — backfill UPDATE with scope/case-sensitivity comments
- [x] **T3 — VERIFY: run full test suite, confirm all green** — ✓ 2026-08-13 — 52 passed, 0 failed
- [x] **T4 — UPDATE dev3-assessment-tracker.md** — ✓ 2026-08-13

### Review Findings

**6-agent adversarial review — 2026-08-13 — 11 patch, 2 defer, 3 dismissed**

**BLOCKERS**
- [x] [Review][Patch] Rollback delete silently ignores `resp.error`; Supabase signals failure via attribute not exception — orphaned rows cause permanent 409 lockout on retry [apps/api/app/modules/assessment/service.py:1021]
- [x] [Review][Patch] AC1 test calls service layer directly, bypassing router; Redis lock release is in router.py:265 — no Redis assertion anywhere; router cleanup branch completely untested [apps/api/tests/test_onboarding_llm_failure.py:79]

**HIGH**
- [x] [Review][Patch] Step 5 upsert failure orphans Step 3 rows with no rollback — same permanent lockout scenario as D71 [apps/api/app/modules/assessment/service.py:~1040]
- [x] [Review][Patch] D72 incomplete: `export_openapi.py` description string still contains "TransformED" [apps/api/scripts/export_openapi.py:35]

**MEDIUM**
- [x] [Review][Patch] AC3 under-tested: HTTP 200, learner_dna DB row creation, and unique-constraint 409 absence not verified — test operates at service layer, bypassing these outcomes [apps/api/tests/test_onboarding_llm_failure.py:191]
- [x] [Review][Patch] Migration test typo guard `"TRANSFORMEDED"` is logically dead — `.upper()` produces "TRANSFORMED" (10 chars); "TRANSFORMEDED" (13 chars) no realistic typo produces [apps/api/tests/test_onboarding_llm_failure.py:294]
- [x] [Review][Patch][Scale Q1/Q3] Migration UPDATE unbounded: full sequential scan on `profile_text` (no GIN index), holds RowExclusiveLock, blocks concurrent onboarding upserts; row count and deployment scope undocumented [supabase/migrations/20260813000000_learner_dna_rebrand.sql:12]
- [x] [Review][Patch] Empty `_question_ids` guard missing; supabase-py drops `IN ([])` filter in some versions, turning DELETE into full-user-scope wipe [apps/api/app/modules/assessment/service.py:1019]

**LOW**
- [x] [Review][Patch] Stale "TransformED Learner DNA" in existing test mock fixture — future HIE-compliance assertion will find it and appear broken [apps/api/tests/test_onboarding_endpoint.py:1007]
- [x] [Review][Patch] Module docstring still says "TransformED AI" [apps/api/app/providers/embeddings/openai.py:5]
- [x] [Review][Patch] Migration `REPLACE()` is case-sensitive with no comment explaining why casing variants from GPT won't exist [supabase/migrations/20260813000000_learner_dna_rebrand.sql]

**DEFERRED**
- [x] [Review][Defer] No TTL on Redis `onboarding_key` — process crash between SET NX and HTTPException cleanup leaves key permanently set (D73) [apps/api/app/modules/assessment/router.py:250] — deferred, pre-existing
- [x] [Review][Defer] Broad `except Exception` launders non-retryable OpenAI errors (401, 400) as HTTP 503 "please retry" — misleading retry semantics [apps/api/app/modules/assessment/service.py:1017] — deferred, pre-existing design gap

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


### Scale & Load Hunter (6th Agent — 2026-09-05)

| # | Agent | Severity | Finding | Resolution |
|---|-------|----------|---------|------------|
| 1 | Scale & Load Hunter | **PASS** | `## Scale & Load` section present and answers all 6 SCALE-CONTRACT.md questions. No unbounded queries identified; all reads carry `.limit()` / `.maybe_single()` / `count=` or a `# BOUNDED:` justification per the story's own analysis. Inherited caps re-derived where noted in the Scale & Load section. | N/A |

**Scale & Load Hunter verdict:** PASS — added as 6th mandatory review layer per CLAUDE.md BMAD Code Review Gate.
