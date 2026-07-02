---
baseline_commit: ""
---

# Story 3-17: DPDP Act 2023 — user_consents Audit Table

**Status:** in-progress
**Epic:** Sprint 1 Production Readiness — DPDP Compliance
**Branch:** `sprint1/s1-17-dpdp-user-consents`
**Depends on:** all Sprint 1 stories merged to main
**Audit source:** Sprint 1 Audit Report blocker — DPDP consent gap (CLAUDE.md §18)

---

## User Story

As a platform operator,
I want a `user_consents` audit table that records each user's explicit consent (type, policy version, timestamp) before any personal data collection begins,
so that TransformED AI complies with DPDP Act 2023 and can demonstrate an auditable consent trail for attention tracking and Learner DNA.

---

## Context

CLAUDE.md §18 flags a DPDP consent gap:
> `users.attention_consent` boolean is insufficient — a `user_consents` audit table (columns: user_id, consent_type, policy_version, consented_at) is required before any attention data is collected. Sprint 2 priority.

The `attention_events` table RLS currently gates on `users.attention_consent = true` (a single boolean). This provides no audit trail — there is no record of *when* consent was given, to *which policy version*, or for *what specific purpose*. DPDP Act 2023 requires these fields.

This story unblocks Sprint 2 attention tracking work by creating the audit table before any real attention data is collected.

---

## Acceptance Criteria

### AC 1 — user_consents table created
- Table `public.user_consents` exists with columns:
  - `id uuid PRIMARY KEY DEFAULT gen_random_uuid()`
  - `user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE`
  - `consent_type text NOT NULL CHECK (consent_type IN ('attention_tracking', 'learner_dna'))`
  - `policy_version text NOT NULL`
  - `consented_at timestamptz NOT NULL DEFAULT now()`
  - `created_at timestamptz NOT NULL DEFAULT now()`

### AC 2 — RLS: INSERT + SELECT only (no UPDATE / DELETE — immutable audit records)
- RLS enabled on `user_consents`
- `SELECT` policy: `user_id = auth.uid()`
- `INSERT` policy: `user_id = auth.uid()`
- No `UPDATE` policy — rows are immutable once created (DPDP audit immutability requirement)
- No `DELETE` policy — rows are immutable once created

### AC 3 — Indexes
- Index on `(user_id)` for fast foreign-key lookup
- Index on `(user_id, consent_type)` for the RLS consent-check sub-query

### AC 4 — Trigger: sync users.attention_consent
- Function `public.sync_attention_consent_on_insert()` exists (SECURITY DEFINER, search_path=public)
- Trigger `user_consents_sync_attention` fires AFTER INSERT on `user_consents` FOR EACH ROW
- When `NEW.consent_type = 'attention_tracking'`, updates `users.attention_consent = true` for that user_id
- This keeps the existing boolean fast-lookup in sync with the audit table

### AC 5 — attention_events INSERT RLS hardened with dual consent check
- Old policy `"attention_events: insert own"` is replaced with a new policy containing two conditions:
  1. Session ownership + `users.attention_consent = true` (existing check, unchanged)
  2. `EXISTS (SELECT 1 FROM public.user_consents uc WHERE uc.user_id = auth.uid() AND uc.consent_type = 'attention_tracking')` (new DPDP check)
- Both conditions must be true for an INSERT to succeed
- This ensures no attention data can be inserted without an explicit consent record, even if the boolean was set by other means

### AC 6 — Migration file on disk
- File `supabase/migrations/20260702000000_dpdp_user_consents.sql` exists
- File is NOT a modification of any existing migration
- File header includes migration name, date, and warning comment

### AC 7 — Migration applied to Supabase project
- Migration applied to project `kxhgvwopdszclfyrrkqm` via Supabase MCP
- `mcp__supabase__list_migrations` confirms `dpdp_user_consents` in the applied list
- `mcp__supabase__list_tables` confirms `user_consents` in `public` schema

### AC 8 — No regressions
- `pytest -m unit` exits 0 on main (no assessment tests broken by schema change)
- Existing migrations unchanged

---

## Tasks / Subtasks

- [x] Task 1: Write story file — story-first gate — ✓ 2026-07-02
  - [x] 1.1 Create `docs/stories/3-17-dpdp-user-consents.md`
  - [x] 1.2 Commit story-only, push to remote

- [ ] Task 2: Create migration SQL file — AC 1, 2, 3, 4, 5, 6
  - [ ] 2.1 Write `supabase/migrations/20260702000000_dpdp_user_consents.sql`
  - [ ] 2.2 Include: CREATE TABLE, indexes, RLS enable, SELECT + INSERT policies
  - [ ] 2.3 Include: sync trigger function + trigger
  - [ ] 2.4 Include: DROP + recreate attention_events INSERT policy

- [ ] Task 3: Apply migration via Supabase MCP — AC 7
  - [ ] 3.1 Call `mcp__supabase__apply_migration` with project `kxhgvwopdszclfyrrkqm`
  - [ ] 3.2 Verify with `mcp__supabase__list_migrations` — dpdp_user_consents present
  - [ ] 3.3 Verify with `mcp__supabase__list_tables` — user_consents in public schema

- [ ] Task 4: Verify schema correctness — AC 1, 2, 5
  - [ ] 4.1 Execute SQL: check user_consents columns, constraints, RLS policies
  - [ ] 4.2 Execute SQL: check attention_events INSERT policy body contains user_consents check

- [ ] Task 5: Commit migration file + update tracker — AC 6, 8
  - [ ] 5.1 `git add supabase/migrations/20260702000000_dpdp_user_consents.sql`
  - [ ] 5.2 Commit, push branch
  - [ ] 5.3 Update `docs/dev3-assessment-tracker.md` — add Story 3-17 entry, update Sprint 1 dashboard

---

## Dev Notes

### Why INSERT-only RLS (no UPDATE/DELETE)?

DPDP Act 2023 requires consent records to be immutable for audit purposes. Once a consent is recorded, it cannot be altered. Revocation of consent is handled at the application layer by:
1. Setting `users.attention_consent = false` (stops new inserts via RLS)
2. Inserting a new `user_consents` row with `consent_type = 'attention_tracking_revoke'` (future) OR recording the revocation in a separate event

This story implements only the consent grant path. Revocation handling is a Sprint 2 story.

### Why keep users.attention_consent boolean?

The boolean is a denormalized fast-lookup used by `attention_events` RLS on every INSERT. Replacing it with a sub-query on every RLS check would be slower. The trigger syncs the boolean from user_consents, keeping the two in agreement with no application-layer coordination needed.

### Trigger: SECURITY DEFINER requirement

The trigger runs after INSERT on user_consents (which the user can do via RLS). It then UPDATEs the `users` table. Although the user has an UPDATE policy on their own row, RLS evaluation inside a trigger depends on the session context. SECURITY DEFINER with `SET search_path = public` ensures the UPDATE on `users` always succeeds when the owning user's consent row is inserted.

### Migration timestamp

Using `20260702000000` — today's date. Applied migrations use timestamps in the `YYYYMMDDHHMMSS` format. The Supabase MCP `apply_migration` does not require the file timestamp to match the DB version; the DB version is assigned at apply time.

### Files Changed

| File | Change |
|------|--------|
| `docs/stories/3-17-dpdp-user-consents.md` | This file |
| `supabase/migrations/20260702000000_dpdp_user_consents.sql` | New migration |
| `docs/dev3-assessment-tracker.md` | Sprint 1 addendum |

**Files NOT changed:**
- `supabase/migrations/20260611000000_initial_schema.sql` — never modify applied migrations
- `supabase/migrations/20260625000000_chunks_inline_embedding.sql` — never modify applied migrations
- `supabase/migrations/20260630000000_unique_attempt_constraints.sql` — never modify applied migrations
- Any application code — this is a schema-only change

---

## Senior Developer Review (AI)

*(to be filled after implementation)*

---

## Dev Agent Record

### Completion Notes
*(to be filled)*

### File List
- `docs/stories/3-17-dpdp-user-consents.md`
- `supabase/migrations/20260702000000_dpdp_user_consents.sql`

### Change Log
- 2026-07-02: Story created — DPDP user_consents audit table, Sprint 1 production readiness blocker
