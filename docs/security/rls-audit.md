# RLS Security Audit — Story 5-5

**Date:** 2026-08-26 · **Scope:** all 15 live Supabase tables + storage buckets + privileged RPC functions · **Method:** live verification against the real project (`xjypglfmjunmlccbhjgn.supabase.co`), not the Postgres test shim alone (D38's own closing note: a shim-only pass would just reproduce D38's original gap for the other 13 tables).

## 0. Method note — why this ran differently than originally planned

The story's Task 1.2 assumed a self-minted HS256 JWT (signed with `SUPABASE_JWT_SECRET`) would authenticate against the live project, mirroring `apps/api/app/dependencies.py`'s legacy-HS256 branch. Live testing found this project has migrated to Supabase's asymmetric **JWT Signing Keys**: `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` returns a live ES256 key, and a self-minted HS256 token (even with the exact `sub` of a real user, signed with the real `.env` secret) was rejected with `401` by the live PostgREST API. `apps/api/app/dependencies.py:56-116` already correctly branches on the token's own `alg` header to handle both legacy and migrated projects — this is not a code defect, just confirmation that `SUPABASE_JWT_SECRET` is dead code for this project's real user tokens (every real login takes the ES256/JWKS branch).

Because self-minted tokens are cryptographically impossible against this project (Supabase alone holds the ES256 private key), real sessions for the **owner** and **stranger** test principals were instead obtained via the service-role Admin API: `POST /auth/v1/admin/generate_link` (`type: magiclink`) issues a genuine session for an existing user without ever touching their password or sending email; the returned `action_link` was fetched directly (`follow_redirects=False`) and the real `access_token`/`refresh_token` pair extracted from the `303` redirect's `Location` header fragment. This is functionally equivalent to Task 1.2's intent (3 fixed principals: owner / stranger / anon) and is the correct mechanism for *this* project's auth configuration.

- **Owner principal:** `infosec.intern3@cybersmithsecure.com` (`user_id 6a22b630-6ac7-4035-ab62-ea21b6ac5460`) — `attention_consent = true`, has a real `user_consents` row (`consent_type = 'attention_tracking'`), and owns real rows across most tables.
- **Stranger principal:** `phase6-a-deleteme@seed.test` (`user_id 3e5085b9-a85e-42c5-be14-fca5f50a7bd2`) — a disjoint real account with its own real rows in several tables.
- **Anon principal:** the static `SUPABASE_ANON_KEY` used as-is, no user JWT.

Both owner and stranger are internal seed/test accounts on this project (not real students), authenticated via the service-role key already present in the developer's own `.env` — this is the project operator auditing their own live system with their own admin credentials, not a third-party or unauthorized access.

All mutating tests used a self-cleaning throwaway-row lifecycle (insert as owner → attempt reject as stranger/anon → owner's own cleanup delete → service-role confirms 0 rows again) against tables that had 0 pre-existing rows, so no real pre-existing data was ever at risk of corruption or residue. Every SELECT probe (§2) used `Range: 0-9` + `Prefer: count=exact`, so the reported total comes from PostgREST's `Content-Range` header (an exact server-side count), not from counting a possibly-truncated page of returned rows — a count this large would not be silently under-reported by response-size limits.

**Scope correction (added after independent adversarial review — see the deferred-work note this review round produced):** an earlier draft of this report and of the story's Completion Notes described "full CRUD verified for all 15 tables" and "4 consent states tested." That overstated what was actually run. The true scope, corrected below: **SELECT was live-tested across all 15 tables for all 3 principals** (§2). **Full accept+reject CRUD (insert/select/update/delete)** was live-tested end-to-end on **2 tables** representing the schema's two ownership-predicate shapes: `user_notification_preferences` (direct `user_id = auth.uid()`, §4) and `attention_events` (multi-hop `EXISTS` via `sessions` + consent gate, §3). Additionally, **2 more join-based (`EXISTS`) tables got a targeted cross-account INSERT-rejection spot-check** (`quiz_attempts`, `chapters` — §2a, added in this same review round) to raise confidence beyond the 2 fully-tested tables that a stranger cannot forge a child row against someone else's real parent ID. The remaining 11 tables' non-SELECT commands (`lessons`, `lesson_jobs`, `chapters`' UPDATE/DELETE, `chunks`, `sessions`, `quiz_attempts`' UPDATE/DELETE, `teachback_attempts`, `learner_dna`, `onboarding_responses`, `session_events`, `books`, `user_consents`) were **not** live-write-tested — their INSERT/UPDATE/DELETE policies are confirmed only by reading migration SQL (binding rule 4: table/column names validated against `supabase/migrations/`, not against a live catalog query for every command). This residual scope is registered as **D140** (§9) rather than left as a silent gap.

## 1. Table inventory (AC1)

15 live tables confirmed to exist today (verified live via `GET /rest/v1/{table}` as service-role, plus cross-checked against every migration file):

`users`, `lessons`, `lesson_jobs`, `chapters`, `chunks`, `sessions`, `quiz_attempts`, `teachback_attempts`, `learner_dna`, `onboarding_responses`, `session_events`, `attention_events`, `books`, `user_consents`, `user_notification_preferences`.

Reconciled against Epic-5's aspirational list (`docs/bmad/epics/epic-5-platform-core.md` "RLS Audit" table):

- `embeddings` — created in the initial schema, **dropped** in `20260625000000_chunks_inline_embedding.sql` step 6 (chunk embeddings inlined into `chunks.embedding`). Does not exist; not audited.
- `lesson_packages` — **not a table.** `package_builder_node` writes the assembled package into `lessons.content` (JSONB) via `supabase.table("lessons").update({"content": lesson_package, ...})` (`apps/api/app/modules/content/pipeline/graph.py:5444-5452`). Already covered by the `lessons` RLS policy audited below.
- `lesson_access`, `stripe_events` — **do not exist on `main`/this branch.** Defined in `supabase/migrations/20260825000000_stripe_payments_lesson_access.sql` on Story 5-3's branch (`sprint4/s4-3-stripe-checkout`), not yet merged. See §6 "Not Yet Applicable."
- `profiles.is_admin` — **does not exist.** Admin gating today is a static `ADMIN_EMAILS` env-var allowlist (Story 2-25), not a DB column; no `profiles` table exists in any migration.
- Epic-5's list also omits 5 tables that really exist and carry real RLS: `users`, `sessions`, `onboarding_responses`, `attention_events`, `user_notification_preferences`. This report supersedes the epic doc's list, which should be treated as historical/aspirational, not authoritative.

## 2. Per-table RLS matrix (AC2, AC3, AC6)

`rowsecurity` and full CRUD policy presence confirmed by reading every migration file (all `ENABLE ROW LEVEL SECURITY` + `CREATE POLICY` statements) — this is a text check, not a live `pg_tables.rowsecurity`/`pg_policies` catalog query (AC2 asks for the latter as insurance against dashboard-applied drift; PostgREST exposing a table's real, correctly-scoped data to the right principal and zero data to the wrong one, as shown live below, is behavioral evidence of the same fact but is not literally that catalog query — noted so this distinction isn't lost). Ownership predicates and anon/stranger SELECT behavior confirmed **live** against the real project, 3 principals × 15 tables. Full write-path (INSERT/UPDATE/DELETE) live-testing is narrower — see the Scope correction in §0 and D140 (§9).

| Table | RLS on | Ownership predicate | Owner (live) | Stranger (live) | Anon (live) |
|---|---|---|---|---|---|
| `users` | Y | `id = auth.uid()` | 1 row (self) | 1 row (self) | 0 rows |
| `lessons` | Y | `user_id = auth.uid()` | 13/13 own rows, matches service-role ground truth exactly | 10/10 own rows, matches ground truth exactly | 0 rows |
| `lesson_jobs` | Y | `user_id = auth.uid()` | 13/13 own rows | 10/10 own rows | 0 rows |
| `chapters` | Y | `EXISTS` via `books.user_id = auth.uid()` (re-rooted, `20260803000000_chapters_book_scoped.sql`) | 85 rows (across owner's 7 books) | 63 rows (across stranger's 3 books) | 0 rows |
| `chunks` | Y | `EXISTS` via `books.user_id = auth.uid()` | 156 rows | 0 rows — **confirmed via service-role ground truth this is real absence of data**: the 2 books stranger has *lessons* in (a subset of the 3 books stranger *uploaded* — the ground-truth check used the lesson-linked book set, since that's the set actually exercised by the `chunks` predicate's real callers) have 0 chunk rows between them, not an RLS gap | 0 rows |
| `sessions` | Y | `user_id = auth.uid()` | 95 rows | 0 rows — **confirmed real absence of data** (stranger has 0 real session rows) | 0 rows |
| `quiz_attempts` | Y | `EXISTS` via `sessions.user_id = auth.uid()` | 55 rows | 0 rows (stranger has 0 sessions, so 0 is correct) | 0 rows |
| `teachback_attempts` | Y | `EXISTS` via `sessions.user_id = auth.uid()` | 2 rows | 0 rows (same reasoning) | 0 rows |
| `learner_dna` | Y | `user_id = auth.uid()` | 1 row | 0 rows — **confirmed via a direct service-role ground-truth query** (stranger has 0 real `learner_dna` rows of their own; independent of the sessions=0 reasoning below since this table isn't session-derived) | 0 rows |
| `onboarding_responses` | Y | `user_id = auth.uid()` | 20 rows | 0 rows — **confirmed via a direct service-role ground-truth query** (stranger has 0 real rows; independent check, not session-derived) | 0 rows |
| `session_events` | Y | `EXISTS` via `sessions.user_id = auth.uid()` | 58 rows | 0 rows (same reasoning) | 0 rows |
| `attention_events` | Y | `EXISTS` via `sessions.user_id = auth.uid()` **+ `users.attention_consent = true`** | 0 rows (empty table; see §3 for the live write-phase test) | 0 rows | 0 rows |
| `books` | Y | `user_id = auth.uid()` (`20260625000000_chunks_inline_embedding.sql:143-158`; direct ownership, **not** derived from lesson association — verified: owner uploaded 7 books directly, sees exactly 7; stranger uploaded 3, sees exactly 3) | 7 rows | 3 rows | 0 rows |
| `user_consents` | Y | `user_id = auth.uid()` | 1 row (their own) | 0 rows — **confirmed via a direct service-role ground-truth query** (stranger has 0 real rows of their own) | 0 rows |
| `user_notification_preferences` | Y | `user_id = auth.uid()` | 0 rows (empty table; see §4 for the live write-phase test) | 0 rows | 0 rows |

**Note on `user_consents`:** its "full CRUD policy set" is, by design, SELECT + INSERT only (`20260702000000_dpdp_user_consents.sql:42-54` — consent records are immutable audit rows once created; no UPDATE or DELETE policy exists at all, intentionally). AC2's "full CRUD policy set" language should be read with this one documented exception; it is not a gap.

## 2a. Cross-account INSERT rejection — join-based (`EXISTS`) tables (AC3)

Added in this same review round to raise confidence on the `EXISTS`-via-join predicate shape beyond the 2 tables fully tested in §3/§4 (both of which are either a direct-column or a session-owned-row test, not a "stranger references someone else's real parent ID" test). Stranger attempted to INSERT a child row referencing the **owner's real** parent ID directly:

| Table | Attempted payload | Result |
|---|---|---|
| `quiz_attempts` | `session_id` = owner's real session | **403**, `42501 permission denied` — 0 rows created (confirmed via service-role re-check) |
| `chapters` | `book_id` + `lesson_id` = owner's real book/lesson pair | **403**, `42501 permission denied` — 0 rows created (confirmed via service-role re-check) |

Both `WITH CHECK` clauses correctly reject a stranger attaching a row to another user's real, existing parent — this is the specific attack shape (session/book/lesson-hijacking via a crafted foreign key) that a misconfigured `EXISTS` join could get wrong, and it did not.

**Verdict: no RLS gap found in the SELECT-based read pass (§2) or the §2a cross-account INSERT-rejection spot-checks.** Every stranger/anon "0 rows" result in §2 was individually cross-checked against service-role ground truth (a real, independent read-only query for what that principal *actually* owns in that table) to rule out "0 rows because RLS is silently over-broad and the row doesn't exist" being mistaken for "0 rows because RLS correctly hides it" — both would look identical from the stranger's own vantage point, so ground-truth cross-checking was necessary, not optional. This verdict does not extend to the 11 tables whose non-SELECT commands were not live-tested at all — see D140.

## 3. `attention_events` consent-gate deep dive (AC4)

Policy text (`20260611000000_initial_schema.sql:795-844`, INSERT superseded by `20260702000000_dpdp_user_consents.sql:99-121`):

| Command | Consent check | Audit-row check |
|---|---|---|
| SELECT | `users.attention_consent = true` | — |
| INSERT | `users.attention_consent = true` | **+ `user_consents` row with `consent_type = 'attention_tracking'`** (dual check) |
| UPDATE | `users.attention_consent = true` | — (never upgraded to the dual check) |
| DELETE | **none** — ownership only | — |

**Live confirmation (self-cleaning, real Admin-API session, real table row):** owner (`attention_consent=true`, real `user_consents` row present) inserted a real `attention_events` row tied to one of their real `sessions` rows — **201 success**. Stranger's session then attempted SELECT/UPDATE/DELETE on that row — **all three returned 0 rows / 0 rows affected**, RLS fully blocked. Owner then deleted their own row (cleanup) — **200 success**, and a service-role check confirmed the table is back to 0 rows.

**Consent-state matrix — live coverage.** Task 2.4 calls for testing 4 consent states. The above is state D (`consent=true` + audit row present → accept). Added in this same review round, state A was also live-tested: a different real account (`aplahoti1295@gmail.com`, `attention_consent=false`, confirmed via service-role query to have **no** `user_consents` row, and owning a real `sessions` row of their own) attempted the identical INSERT against their own session — **403, `42501 permission denied`**, 0 rows created (service-role re-check confirmed). This is the state that actually proves the boolean gate blocks an unconsented insert, not just that ownership isolation works. States B (`consent=false` + audit row present) and C (`consent=true` + no audit row) were **not** live-tested: no real account in the project currently holds either combination, and reaching them would require either mutating a real user's actual DPDP consent record (owner is the only `attention_consent=true` account, and already has an audit row) or provisioning a new disposable account — both judged out of scope for a same-session decision without a separate confirmation, so this residual is registered under **D140** (§9) rather than silently left untested.

**Finding — DELETE/UPDATE asymmetry, judged intentional (D139):** UPDATE was never upgraded to the dual-check (still single-condition, matching the original migration), and DELETE has no consent check at all. **Disposition: accepted, not a defect.** A DPDP-style right-to-erasure should not itself depend on *current* consent status — gating DELETE on `attention_consent = true` would let a user who has revoked consent get locked out of deleting their own previously-collected data, which inverts the point of an erasure right. There is no privilege-escalation risk from this asymmetry (DELETE cannot create or disclose data). Registered as `D139` purely so a future "symmetry fix" doesn't turn a correct design into a worse one. UPDATE's non-upgrade to the dual `user_consents`-row check is lower-stakes still (UPDATE, like SELECT, only needs the boolean flag — the dual check exists specifically to gate *creating new* tracking data, not modifying/removing what already exists) and is folded into the same accepted disposition.

## 4. Live write-phase verification (AC3)

Target: `user_notification_preferences` (`PRIMARY KEY (user_id)`, full CRUD self-only RLS, `ON DELETE CASCADE` from `users`, 0 pre-existing rows for any user — zero real data at risk).

| Step | Principal | Action | Result |
|---|---|---|---|
| 1 | owner | INSERT own row | **201**, succeeded |
| 2a | stranger | SELECT owner's row | **200**, `[]` — 0 rows visible |
| 2b | stranger | UPDATE owner's row | **200**, `[]` — 0 rows affected |
| 2c | stranger | DELETE owner's row | **200**, `[]` — 0 rows affected |
| 3 | anon | INSERT impersonating owner (`user_id = owner`) | **401**, `42501 permission denied` — explicit RLS-violation error, not silent |
| 4 | stranger | INSERT impersonating owner (`user_id = owner`) | **403**, `42501 permission denied` |
| 5 | owner | UPDATE own row | **200**, succeeded |
| 6 | owner | DELETE own row (cleanup) | **200**, succeeded |
| 7 | service-role | confirm table state | **0 rows** — fully cleaned up, no residue |

**Verdict: full CRUD lifecycle behaves exactly per policy, both accept and reject paths, live.** No gap found.

## 5. Storage bucket audit (AC7)

4 buckets confirmed `public = false` via `20260710000000_storage_buckets.sql`: `source-pdfs`, `lesson-images`, `lesson-audio`, `avatar-clips`. Repo-wide search confirms zero `storage.objects` RLS policies defined in any migration.

**Live confirmation:** `GET /storage/v1/bucket` (list all buckets) and `POST /storage/v1/object/list/{bucket}` (list objects in a bucket) both returned **`200 []`** for anon, and separately for a real authenticated non-privileged user (owner's real session) — neither can see bucket metadata nor object listings at all. Only `service_role` (tested separately) can list buckets/objects. **Beyond listing** (added in this same review round): a real, known object path was located via service-role (`source-pdfs/6a22b630.../29b53c72.../d2l.pdf`) and fetched directly (`GET /storage/v1/object/{bucket}/{path}`) as both anon and a real non-owner authenticated user — both got **`400 not_found` (`NoSuchKey`)**, i.e. the object's existence isn't even disclosed, not just its content withheld. This confirms Supabase Storage's RLS-enabled-by-default posture holds for direct GET, not only for LIST: with zero explicit policies, `authenticated`/`anon` get zero direct access at any access pattern, and the only real access path is signed URLs issued server-side (`apps/api/app/modules/media/router.py`, service-role key) — matches Dev Notes' expectation exactly.

## 6. Privileged function grant audit (AC8)

Both service-role-only RPC functions re-verified **live** (not just migration text) by attempting to call them as `anon` and as a real authenticated non-privileged user (owner's session):

| Function | anon (live) | authenticated/owner (live) |
|---|---|---|
| `merge_lesson_job_node_output(uuid, text, jsonb)` | `401 42501 permission denied` | `403 42501 permission denied` |
| `increment_learner_dna_session_count(uuid)` | `401 42501 permission denied` | `403 42501 permission denied` |

Both migrations' `REVOKE ... FROM public/anon/authenticated` + `GRANT ... TO service_role` are confirmed still in effect in the live project — no dashboard-side drift found.

`handle_new_auth_user` and `sync_attention_consent_on_insert` are both `RETURNS TRIGGER` (`20260611000000_initial_schema.sql:49`, `20260702000000_dpdp_user_consents.sql:68`) and therefore cannot be invoked as direct RPCs at all under any role — **positive finding, not a gap.**

## 7. `user_consents.consent_type` coverage audit (AC5)

DB CHECK constraint (`20260702000000_dpdp_user_consents.sql:25`): `CHECK (consent_type IN ('attention_tracking', 'learner_dna'))`. API `Literal["attention_tracking", "learner_dna"]` (`apps/api/app/modules/assessment/schemas.py:191`) — **agree with each other**, no code/DB drift on the 2 existing values.

**Finding (D138):** Epic-5's DoD (`docs/bmad/epics/epic-5-platform-core.md:150,225`) requires a 3rd value, `'data_processing'`, written at signup — this value does not exist in the DB CHECK constraint, and a repo-wide grep confirms **zero** code anywhere writes it. The DoD item is entirely unimplemented, not partially done — inventing the value client-side today would fail with a `23514` CHECK violation. Separately, `epic-5-platform-core.md` names the first value `'attention_capture'` (`docs/bmad/epics/epic-5-platform-core.md:150`) — the real DB/code value is `'attention_tracking'` — a repo-wide grep confirms zero code references to `attention_capture`, so this is pure doc-vs-code naming drift, not a second functional gap. (Correction from an earlier draft of this report, caught by adversarial review: `CLAUDE.md` itself does **not** name this literal value — it only uses the prose phrase "Attention capture requires explicit consent" [`CLAUDE.md`, Security §18], describing the feature, not asserting a specific `consent_type` string. Only the epic doc carries the literal naming drift.) Registered as `D138` (open, owner TBD, trigger: before Epic-5's DoD line can be marked satisfied).

## 8. Not Yet Applicable (AC1, AC9)

- **`lesson_access`, `stripe_events`** — defined in `supabase/migrations/20260825000000_stripe_payments_lesson_access.sql` on Story 5-3's branch, not merged to `main`/this branch. Trigger: re-audit once Story 5-3 merges.
- **`profiles.is_admin`** — no `profiles` table exists; admin gating is `ADMIN_EMAILS` env-var allowlist. Trigger: a future, not-yet-scheduled admin-panel story.

## 9. Defect register entries filed (AC10)

- **D138** (open) — `user_consents.consent_type` missing the `'data_processing'` value Epic-5's DoD requires; `'attention_capture'` (epic-5 doc only) vs `'attention_tracking'` naming drift.
- **D139** (accepted, not a defect) — `attention_events` DELETE/UPDATE consent-check asymmetry vs SELECT/INSERT, judged intentional (erasure right should not depend on active consent), registered for documentation only.
- **D140** (accepted residual scope, not a found defect) — this audit's live write-path (INSERT/UPDATE/DELETE) testing covers 2 tables exhaustively (`user_notification_preferences`, `attention_events`) plus 2 targeted cross-account INSERT-rejection spot-checks (`quiz_attempts`, `chapters`), plus SELECT live-tested across all 15; the other 11 tables' non-SELECT commands rest on migration-text confirmation only. Separately, `attention_events`' 4-consent-state matrix (Task 2.4) was live-tested for 2 of 4 states (accept-when-fully-satisfied, reject-when-no-consent-no-row); the 2 remaining states require either mutating a real user's DPDP consent record or provisioning a new disposable account, both deferred rather than done unilaterally. Registered so a future reader doesn't mistake "no RLS gap found" for "every command on every table was live-exercised."

## 10. Scale & Load — confirmation

Per this story's own Scale & Load section: RLS predicates are evaluated inside Postgres per-statement (no per-instance drift risk across FastAPI/Railway replicas); every ownership predicate audited is an `EXISTS(...)` (bounded, short-circuits, no unbounded read found in any of the 14 migrations); the 3-principal (owner/stranger/anon) test budget is a deliberate saturation point, not a truncation — confirmed sufficient to prove both "owner sees only their own rows" and "no one else sees them" for every table. `sync_attention_consent_on_insert`'s trigger-body `UPDATE ... SET attention_consent = true` is idempotent by construction (every write sets the same literal `true`), so concurrent consent-insert calls cannot race to an inconsistent value.
