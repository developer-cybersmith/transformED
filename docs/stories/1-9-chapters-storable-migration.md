# Story 1.9: Make chapters storable without a lesson (book-scale Phase 2)

Status: ready-for-dev

**Sprint:** Book-scale ingestion, Phase 2 of 7
**Owner:** Dev 1
**Branch:** `book-scale/phase-2-chapters-storable`
**Depends on:** Phase 1 `✅ Verified` 2026-08-03 (`docs/reports/PHASE-1-TOC-SPIKE.md`)
**Blocks:** Phase 3 (`docs/bmad/phase-3-chapter-detection-plan.md`)

> ## ⚠️ FROZEN CONTRACT — 4-developer review required
>
> `supabase/migrations/` is one of the four frozen interface contracts (`CLAUDE.md` §16).
> This story changes it. The PR requires review by **all four developers** and the 5-agent
> `/bmad-code-review` gate before merge.
>
> **Never modify an applied migration.** This is a new file only.

---

## Story

As **Dev 1 building book-scale ingestion**,
I want **a chapter row to exist against a book without requiring a lesson**,
so that **Phase 3 can write N real chapters at upload time, before any lesson exists**.

## Context

Today a chapter is impossible without a lesson. `chapters.lesson_id` is
`NOT NULL REFERENCES lessons ON DELETE CASCADE`
(`supabase/migrations/20260611000000_initial_schema.sql:132`), and `chunks.chapter_id` is
`NOT NULL` (`:147`) — that chain is why the pipeline creates exactly one chapter per lesson
ingestion, hardcoded at `apps/api/app/modules/content/pipeline/graph.py:609-638` with
`"chapter_index": 1` (`:624`).

The spec has always been the reverse: upload a book once, generate any chapter on demand
(`CLAUDE.md` §9). Phase 1 proved chapter detection works — 164 chapters across 5 real
textbooks at 99.4 % start-page accuracy, plus a prototyped fallback resolving 22/22 chapters
in three bookmark-less NCERT books. **This story is the schema change that lets those rows be
written.** It writes no application code.

Direction of every change is **permissive** — nullable-ising, adding columns, adding
constraints that current data already satisfies. No existing row can be invalidated.

---

## Acceptance Criteria

**Schema**

1. A new migration file `supabase/migrations/20260803000000_chapters_book_scoped.sql` exists.
   No existing migration file is modified — verified by `git diff --stat` touching only the
   new file under `supabase/migrations/`.
2. `chapters.lesson_id` is nullable. Inserting a chapter with `lesson_id = NULL` and a valid
   `book_id` succeeds.
3. `chapters.lesson_id` retains `REFERENCES lessons(lesson_id) ON DELETE CASCADE` — dropping
   `NOT NULL` must not drop the FK.
4. `lessons.chapter_id uuid` exists, nullable, `REFERENCES chapters(chapter_id) ON DELETE SET NULL`
   (a lesson survives deletion of its source chapter, matching `lessons.book_id`'s
   `ON DELETE SET NULL` at `20260625000000_chunks_inline_embedding.sql:69-70`).
5. `UNIQUE (book_id, chapter_index)` exists on `chapters`. A duplicate insert is rejected with
   SQLSTATE `23505`.
6. `chapters.boundary_confidence` exists, `NOT NULL DEFAULT 'fallback'`, constrained to
   `('toc','contents','heading','font','fallback')`. An out-of-enum value is rejected with
   SQLSTATE `23514`.
7. An index exists on `lessons.chapter_id`.

**Data safety**

8. The migration replays cleanly on a database that already contains rows in `chapters`,
   `lessons`, `chunks` and `books`. All pre-existing chapter rows remain readable and keep
   their original `lesson_id`, `book_id`, `title`, `page_start`, `page_end`, `chapter_index`.
9. Pre-existing chapter rows receive `boundary_confidence = 'fallback'` — which is accurate:
   they were produced by the hardcoded single-chapter path, not by detection.
10. The migration **fails loudly** rather than silently dropping data if duplicate
    `(book_id, chapter_index)` pairs already exist. The dev must confirm none exist before
    adding the constraint, and the migration must not contain a `DELETE`, `TRUNCATE`, or
    `ON CONFLICT DO NOTHING` that would paper over one.

**Verification**

11. Every one of AC2–AC9 is proven against **real PostgreSQL**, not by parsing SQL text and
    not against a Supabase mock (binding rule 4 — a mock has no catalog and cannot raise
    42703/23505/23514).
12. The **full migration chain replays from empty** in order, cleanly, with no error.
13. Repo-wide `ruff`, `mypy` and the full `pytest` suite pass (binding rule 1 — verification
    scope is CI scope, never "touched files").

---

## RLS re-rooting — IN SCOPE (signed off by Dev 1, 2026-08-03)

**Not in the tracker's original Phase 2 spec — added to this story by decision, because we are
already paying for one 4-developer frozen-contract review and deferring would require a second.**

All four `chapters` RLS policies and all four `chunks` RLS policies root through
`lessons.user_id` (`20260611000000_initial_schema.sql:429-522`):

```sql
CREATE POLICY "chapters: select own" ON public.chapters FOR SELECT
  USING (EXISTS (SELECT 1 FROM public.lessons l
                 WHERE l.lesson_id = chapters.lesson_id AND l.user_id = auth.uid()));
```

With `lesson_id = NULL`, that `EXISTS` can never be true. Every book-scoped chapter is
invisible and un-insertable **to any RLS-bound caller**.

**This is not a blocker today, and the story must not claim it is.** `apps/api/app/core/db.py:42`
constructs a single Supabase client with the **service-role key**, which bypasses RLS, and the
web app makes exactly one direct table read (`apps/web/src/proxy.ts:40` → `learner_dna`) —
it never reads `chapters`, `books` or `lessons` directly. So Phase 3's ARQ job will write
these rows successfully with the policies left as they are.

**The argument for doing it now** is that we are already inside a frozen-contract migration
requiring a 4-developer review. Re-rooting is small — `chapters.book_id` is `NOT NULL` with an
FK to `books` (`20260625000000:57-59`), and `books.user_id` exists — so the policies become
`EXISTS (SELECT 1 FROM books b WHERE b.book_id = chapters.book_id AND b.user_id = auth.uid())`,
with `chunks` re-rooted `chunks → chapters → books`. Deferring means a second frozen-contract
review later, and a latent trap that only surfaces when Phase 6 adds
`GET /books/{book_id}/chapters` or the frontend reads chapters directly.

### Additional acceptance criteria

14. All four `chapters` policies (`select`/`insert`/`update`/`delete` own) root through
    `books.user_id` via `chapters.book_id`, not through `lessons.user_id`. The four old
    policies are **dropped by name** before the new ones are created — Postgres does not
    replace a policy on `CREATE`, and two policies on the same command OR together, which
    would widen access rather than change it.
15. All four `chunks` policies root `chunks → chapters → books`. Same drop-then-create rule.
16. With RLS **enabled**, on a connection that is *not* service-role and carries user A's
    identity: a chapter with `lesson_id = NULL` belonging to A's book is selectable by A, and
    **not** selectable by user B. A service-role connection proves nothing here — it bypasses
    the exact mechanism under test, so the test must set the role/JWT explicitly and assert
    that a service-role run and a user run give *different* results.
17. `lessons`, `books` and every other table's policies are untouched — asserted by name
    against `pg_policies`, so a stray `DROP POLICY` cannot pass unnoticed.

**Why this is safe to do now:** `chapters.book_id` is `NOT NULL` with an FK to `books`
(`20260625000000:57-59`) and `books.user_id NOT NULL → users` (`:28-37`), so the re-rooted
predicate is total — it resolves for every existing chapter row, including ones that still
carry a `lesson_id`. The change is a strict generalisation, not a narrowing: nothing readable
before becomes unreadable.

**Ordering constraint for the migration file:** re-root the policies **after** the DDL changes,
so the new policies are created against the final column set.

---

## Tasks / Subtasks

- [x] **T1 — RLS scope confirmed in scope by Dev 1, 2026-08-03.** (AC14–17)
- [ ] **T2 — Pre-flight the data** (AC10)
  - [ ] Query for existing duplicate `(book_id, chapter_index)` pairs; record the count in the
        Dev Agent Record. Do not proceed if any exist — report instead.
  - [ ] Record the current row counts of `chapters`, `lessons`, `chunks`, `books`. The tracker's
        Phase 2 test list expects **23** existing chapter rows — if the real count differs, record
        the actual number rather than the expected one, and say so.
- [ ] **T3 — Write the migration** `supabase/migrations/20260803000000_chapters_book_scoped.sql` (AC1–7)
  - [ ] `ALTER TABLE public.chapters ALTER COLUMN lesson_id DROP NOT NULL;`
  - [ ] `ALTER TABLE public.lessons ADD COLUMN chapter_id uuid REFERENCES public.chapters(chapter_id) ON DELETE SET NULL;`
  - [ ] `ALTER TABLE public.chapters ADD CONSTRAINT chapters_book_chapter_idx_key UNIQUE (book_id, chapter_index);`
  - [ ] `ALTER TABLE public.chapters ADD COLUMN boundary_confidence text NOT NULL DEFAULT 'fallback' CHECK (boundary_confidence IN ('toc','contents','heading','font','fallback'));`
  - [ ] `CREATE INDEX ON public.lessons (chapter_id);`
  - [ ] Header comment in the style of `20260625000000` — what changes, why, and the ADR/plan links
  - [ ] **After** the DDL: `DROP POLICY` the 4 `chapters` + 4 `chunks` policies by name, then
        `CREATE POLICY` re-rooted through `books.user_id` (AC14, AC15, AC17)
- [ ] **T4 — RED: real-Postgres verification harness** (AC11, AC12)
  - [ ] `apps/api/tests/integration/test_migration_chapters_book_scoped.py`
  - [ ] Spin Postgres 15 + pgvector in Docker, replay **every** file in
        `supabase/migrations/` in filename order, then assert AC2–AC9 by executing real SQL
        and asserting on SQLSTATEs
  - [ ] Register a `postgres` marker in `apps/api/pyproject.toml` (`--strict-markers` is on)
        and skip cleanly when Docker is unavailable — **skip must be visible, never silent**
  - [ ] Run it and watch it FAIL before T3 is applied
  - [ ] RLS cases (AC16, AC17) need two identities. Create two `users` rows + two `books`, then
        exercise the policies on a non-service-role connection — a service-role run must be
        included as a *contrast* case, showing it sees rows the user connection does not.
- [ ] **T5 — GREEN** — apply T3, re-run T4 until green (AC1–12)
- [ ] **T6 — Regression + repo-wide gates** (AC13)
  - [ ] Seed a pre-migration DB with representative `books`/`lessons`/`chapters`/`chunks` rows,
        replay, assert AC8/AC9 field-by-field
  - [ ] `ruff check .` + `mypy` + full `pytest` from `apps/api`, repo-wide
- [ ] **T7 — Tracker update, same response as completion** (`docs/book-scale-phase-tracker.md`)
  - [ ] Phase 2 Status, **Observed result** with real numbers (row counts, SQLSTATEs seen,
        replay time) — never "works"
  - [ ] Status Dashboard row, Totals line, header **Last updated** and **Overall status**
  - [ ] Phase 2 → `🧪 Implemented` on merge; only an end-to-end run moves it to `✅ Verified`

---

## Dev Notes

### The verification precedent in this repo is not sufficient here — do not copy it

`apps/api/tests/test_migration_assessment_schema.py` and `test_migration_analytics_schema.py`
are the only existing "migration tests". Their own docstring says:

> *These tests parse the initial migration SQL file directly — no live DB connection required.*

They `.find()` substrings in a `.sql` file. That is a test of a string, not of a schema — it
cannot observe a constraint firing, and it would pass against a migration that Postgres
rejects. The defect register's finding that **24 % of assertions describe a conversation with
a mock** is this exact shape.

You may add text-parse tests as a cheap smoke layer, but **AC11 is not satisfiable by them.**
The Phase 2 gate requires real Postgres.

### Exact current DDL you are altering

```sql
-- 20260611000000_initial_schema.sql:129-138
CREATE TABLE public.chapters (
  chapter_id     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  book_id        uuid        NOT NULL,                    -- FK added in 20260625000000:57
  lesson_id      uuid        NOT NULL REFERENCES public.lessons(lesson_id) ON DELETE CASCADE,
  title          text        NOT NULL,
  page_start     integer     NOT NULL,
  page_end       integer     NOT NULL,
  chapter_index  integer     NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);
-- :295-296  CREATE INDEX ON public.chapters (lesson_id); CREATE INDEX ON public.chapters (book_id);
-- :147      chunks.chapter_id uuid NOT NULL REFERENCES chapters(chapter_id) ON DELETE CASCADE
```

`books` (`20260625000000:28-37`) has `book_id`, `user_id NOT NULL → users`, `filename`,
`page_count`, `status CHECK IN ('processing','ready','failed')`.

### Two-way nullable FK is intentional

After this migration `chapters.lesson_id → lessons` and `lessons.chapter_id → chapters` point
at each other. **Both are nullable**, so there is no chicken-and-egg on insert: Phase 3 writes
chapters with `lesson_id = NULL`, and Phase 5 later sets `lessons.chapter_id` when a lesson is
generated. Do not add `DEFERRABLE` — it is not needed and complicates PostgREST.

### Why `boundary_confidence` has five values, not three

The tracker originally specified `toc | font | fallback`. Phase 1 measured five distinct
detection provenances and the Phase 3 re-plan requires all five
(`docs/bmad/phase-3-chapter-detection-plan.md` §6). Collapsing them destroys the only signal
that tells us which detector is failing in production. `'fallback'` is the default precisely
so pre-existing single-chapter rows are labelled truthfully.

### Migration file naming

Latest applied is `20260714020000_add_lesson_tier.sql`. Use `20260803000000_` — today's date,
strictly after every existing file. Filename order **is** apply order.

### What this story must NOT do

- No application code. No `graph.py` edits — deleting the hardcoded chapter insert at
  `graph.py:609-638` is **Phase 3**, not this story.
- No `POST /lessons` changes — Phase 3.
- No `chunks.chapter_id` nullable-ising. It stays `NOT NULL`; chunks always belong to a chapter.
- No re-pathing of storage, no `progress_pct`, no cost-tracking split — all explicitly deferred
  in the brief §3.

### Testing standards

- Markers are `--strict-markers`; existing markers are `unit`, `integration`, `slow`,
  `live_eval`. Adding `postgres` requires registering it in `apps/api/pyproject.toml:123-128`.
- `filterwarnings = ["error"]` is on — a warning fails the suite.
- Test DB image must include `pgvector`: `chunks.embedding vector(1536)` and its HNSW index are
  created by `20260625000000`, so a plain `postgres:15` image will fail the replay at AC12.
  Use `pgvector/pgvector:pg15`.
- Docker 29.1.3 is available; the Supabase CLI is **not** installed, so `supabase db reset`
  (named in the tracker's Phase 2 test list) is not runnable as written — replay the migration
  files directly against the container instead, and say so in the Observed result.

### Project Structure Notes

- Migration → `supabase/migrations/` (frozen contract).
- Real-Postgres test → `apps/api/tests/integration/` (existing dir; `test_howto_pipeline_e2e.py`
  and `test_tier_differentiation_and_cost.py` are the neighbours).
- Optional text-parse smoke test → `apps/api/tests/` alongside the two existing
  `test_migration_*_schema.py` files.

### References

- [Source: docs/book-scale-phase-tracker.md#Phase-2] — exit criterion, e2e test list, gate rule
- [Source: docs/bmad/book-scale-implementation-brief.md#5] — Phase 2 scope, §3 deferrals
- [Source: docs/bmad/phase-3-chapter-detection-plan.md#6] — the five-value enum and why
- [Source: docs/reports/PHASE-1-TOC-SPIKE.md] — Phase 1 evidence this phase rests on
- [Source: supabase/migrations/20260611000000_initial_schema.sql#L129-L154,L295-L297,L429-L522]
- [Source: supabase/migrations/20260625000000_chunks_inline_embedding.sql#L28-L70,L141-L158]
- [Source: CLAUDE.md#Security] — RLS on all tables; [Source: CLAUDE.md#Defect-Register] — binding rules 1, 2, 4, 5, 7
- [Source: apps/api/app/core/db.py#L40-L47] — service-role client, RLS bypassed server-side

---

## Dev Agent Record

### Agent Model Used

claude-opus-5[1m] — 2026-08-03

### Debug Log References

**BLOCKED at T4 (RED). No migration written. Story remains `in-progress`.**

Three environment findings, in the order they were hit:

1. **Docker daemon is not running.** The CLI is installed (29.1.3) but
   `docker info` fails at `npipe:////./pipe/dockerDesktopLinuxEngine`. Docker Desktop was
   launched from `C:\Program Files\Docker\Docker\Docker Desktop.exe`; after 5+ minutes
   `tasklist` shows **zero** docker processes, so it did not start — likely needs an
   interactive login or elevation.
2. **A local PostgreSQL 18 server IS running on `localhost:5432`** (`C:\Program Files\PostgreSQL\18`,
   PID 10552 listening). It would satisfy binding rule 4 without Docker, but the `postgres`
   password is unknown — auth fails. Not brute-forced.
3. **The migration chain cannot replay on stock Postgres at all** — this is true regardless of
   which server is used, and it changes the harness design. The chain depends on three
   Supabase-provisioned objects:

   | Object | Needed by |
   |---|---|
   | `auth.users` | FK `20260611000000:69`, trigger `:75-77` |
   | `auth.uid()` | **66** references — every RLS policy in the chain |
   | `storage.buckets` | insert at `20260710000000:18` |

   Without a shim, `psql -f 20260611000000_initial_schema.sql` fails at line 69 and nothing
   downstream is verifiable. `supabase db reset` — named in the tracker's Phase 2 test list —
   is not runnable either: the Supabase CLI is not installed.

**Verification actually performed:** `pytest tests/integration/test_migration_chapters_book_scoped.py -m postgres`
→ **25 tests collected, 25 skipped**, each with the visible reason
`Docker daemon not reachable — cannot start a Postgres container`. Repo-wide
`ruff check .` → **All checks passed**. `mypy` on the new test → **Success: no issues found**.

**RED was not observed.** Per the phase gate and story AC11, the migration is deliberately
not written: writing DDL whose constraints have never been seen to fire is exactly the
"success-shaped result without a check" this effort exists to eliminate.

**To unblock, either:**
- start Docker Desktop (then `pytest -m postgres` runs the whole harness unattended), **or**
- supply the local Postgres 18 superuser password — the harness needs a ~3-line change to
  point at `localhost:5432` and create/drop a throwaway database instead of a container.

### Completion Notes List

- T1 ✅ RLS re-rooting confirmed in scope (AC14–17).
- T4 🔨 Harness written, collects and skips visibly; **cannot execute** — see Debug Log.
- T2, T3, T5, T6, T7 ⬜ not started. T2 (row-count pre-flight) is itself blocked on DB access.
- Deliberately **not** done: no `supabase/migrations/` file was created. A migration is not
  written before its RED run under this story's AC11.
- Known limitation to carry into review: the shim reproduces the *contract* of Supabase's
  `auth.uid()`/`auth.users`/`storage.buckets`, not their implementation. Guarded by
  `test_shim_auth_uid_reads_jwt_claims`, and by `test_service_role_and_user_role_disagree`
  which fails if the role switch silently does nothing and the RLS assertions become vacuous.

### File List

- `apps/api/tests/integration/test_migration_chapters_book_scoped.py` (new)
- `apps/api/tests/integration/supabase_shim.sql` (new)
- `apps/api/pyproject.toml` (modified — registered the `postgres` marker)
