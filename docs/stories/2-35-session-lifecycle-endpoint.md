# Story 2.35: Mint sessions server-side (D18 — demo blocker)

Status: done

## Story

As any student attempting a lesson,
I want the backend to create my session row when the lesson starts,
so that quiz and teach-back submissions stop returning 404 and a lesson can actually be completed.

**Source:** `docs/DEFECT-REGISTER.md` **D18**. Found 2026-07-29 by root-cause analysis, verified by hand.

## The defect

**Nothing anywhere creates a `sessions` row.** Verified across the whole repo:

- All **7** `table("sessions")` references in `apps/api` are `.select(...)`. Zero writers.
- `apps/web` never inserts it either — the frontend has no Supabase write path for it.
- `apps/web/src/stores/player.machine.ts:142` invents one: `sessionId: crypto.randomUUID()`.
- `app/modules/assessment/service.py:175` then does:

```python
session_row = single_row(session_resp)
if session_row is None:
    raise HTTPException(404, detail=f"Session {session_id!r} not found.")
```

**So quiz and teach-back 404 for every student, always. The demo path cannot complete.**

Both test suites are green: Dev 3 seeds the row in fixtures, Dev 2 mocks the POST. This is
`DEFECT-REGISTER.md` RC-1 in its purest form — three developers, three green suites, one
broken product, because no test ever reconciled the two sides of the contract.

The schema shows the intended design was always server-side minting:

```sql
session_id  uuid  PRIMARY KEY DEFAULT gen_random_uuid()
user_id     uuid  NOT NULL REFERENCES public.users(id)
lesson_id   uuid  NOT NULL REFERENCES public.lessons(lesson_id)
started_at  timestamptz NOT NULL DEFAULT now()
```

A client-chosen UUID cannot satisfy those foreign keys or make `started_at` meaningful.

## Ownership — a deliberate crossing, not an accident

`sessions` is read by `assessment` and `analytics`, both **Dev 3's** modules. CLAUDE.md §5.4:
*"modules communicate only through the service layer, never via direct DB access into another
module's tables."*

This story therefore lands in `app/modules/assessment/` — **Dev 3's module** — because that is
where the table's reads already live and where a `sessions` writer belongs. Dev 1 is
implementing it only because it blocks the demo and Dev 1 found it.

**This must be reviewed by Dev 3.** It is flagged in the Change Log and in the handoff.

## Acceptance Criteria

1. **AC-1 — `POST /api/assessment/sessions` creates a session and returns its id.** Body:
   `{lesson_id}`. `user_id` comes from the verified JWT (`CurrentUser`) and is **never**
   accepted from the client. `session_id` and `started_at` are database-generated — do not
   send them.
2. **AC-2 — Lesson ownership is enforced, and absence is indistinguishable from non-ownership.**
   A lesson that does not exist and a lesson owned by someone else must both return the
   **same 404**, matching the existing IDOR pattern in `content/router.py:get_lesson` and
   `media/router.py:get_signed_url`. A distinct 403 would leak lesson existence to a non-owner.
3. **AC-3 — Quiz submission succeeds end-to-end against a minted session.** The assertion that
   matters: create a session via the endpoint, then submit a quiz with the returned id, and
   assert **200 rather than 404**. This is the demo path; a test that only checks the insert
   was called proves nothing (`DEFECT-REGISTER.md` BD-2).
4. **AC-4 — A client-invented session id is still rejected.** Submitting a random UUID that
   was never minted must still 404. The fix must not become "accept any id", which would
   restore the 404 as a silent data-integrity problem instead.
5. **AC-5 — Re-learning is supported.** The same user starting the same lesson again gets a
   **new** `session_id`. Sessions are attempt-scoped, not lesson-scoped — `analytics` and the
   CES history depend on that. Do not add a unique constraint on `(user_id, lesson_id)`.
6. **AC-6 — The frontend contract is written down.** `player.machine.ts` must stop calling
   `crypto.randomUUID()` and use the returned id. That is Dev 2's change; this story does not
   make it, but must record it as a hard prerequisite for calling D18 closed.
7. **AC-7 — No regression.** Full suite shows exactly the pre-existing failures. `ruff check`,
   `ruff format --check` and `mypy app` produce no findings not already at baseline, measured
   **repo-wide** (CLAUDE.md binding rule 1).

## Tasks / Subtasks

- [x] Task 1 (AC-1, AC-2): `POST /api/assessment/sessions` + service function; ownership check.
- [x] Task 2 (AC-3, AC-4, AC-5): tests — end-to-end mint→submit, unminted id still 404, re-learn yields a new id.
- [x] Task 3 (AC-6): handoff note for Dev 2 + register update.
- [x] Task 4 (AC-7): full suite, lint, types.

### Review Findings (2026-08-03)

- [x] [Review][Patch] `SessionCreate`/`SessionCreated` missing from `schemas.py` `__all__` [apps/api/app/modules/assessment/schemas.py:14] — **applied**: added both to `__all__` for consistency with all other exported schemas.
- [x] [Review][Defer] `SessionCreate.lesson_id` has no `min_length=1` validator [apps/api/app/modules/assessment/schemas.py:51] — deferred, pre-existing pattern (all other session/lesson_id string fields also lack min_length; `""` always 404s via Postgres UUID comparison, not a security issue).

## Dev Notes

- **Do not "fix" this by upserting on submit.** Creating the row lazily inside `submit_quiz`
  when it is missing would remove the 404 without fixing anything: `started_at` becomes the
  time of the first answer rather than the lesson start, any client-chosen id becomes a valid
  session, and the identity problem is buried instead of solved. AC-4 exists to forbid it.
- **`session_id` must not be client-supplied.** It is already flagged in
  `docs/dev2-narration-playback-handoff.md` §3: no collision or replay protection, and no
  durable link to Dev 3's session-report data. Server-minting closes all three.
- **Match the established IDOR pattern.** `content/router.py:get_lesson` returns an identical
  404 for missing and unowned. Copy it exactly; do not invent a 403.
- **`ended_at` is out of scope.** Session *termination* belongs with Dev 4's WebSocket
  disconnect handling. This story only opens sessions. Record it, do not build it.
- Every new test needs `@pytest.mark.unit` (and `asyncio` where async).

### Explicitly OUT of scope

- Session end / `ended_at` (Dev 4, WebSocket lifecycle).
- Changing `player.machine.ts` (Dev 2 — AC-6 records it).
- Any `sessions` RLS policy change — that is `supabase/migrations/`, the §16 four-dev gate.

### Project Structure Notes

Touches `apps/api/app/modules/assessment/router.py`, `.../service.py`, `.../schemas.py` and
tests. **No** `packages/shared/*`, **no** `supabase/migrations/*` — §16 gate not triggered.
Zero `apps/web/**` (AC-6 is a handoff, not a change).

### Branching

`sprint2/dev1-d18-session-lifecycle`, based on `main`.

### References

- [Source: docs/DEFECT-REGISTER.md — D18, RC-1, BD-2]
- [Source: docs/dev2-narration-playback-handoff.md §3 — session_id identity]
- [Source: CLAUDE.md §5.4 one-discipline rule; §18 IDOR]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-29 | Story created for D18, the demo blocker. **Lands in Dev 3's `assessment` module — needs Dev 3 review.** Dev 1 is implementing only because it blocks the demo. | Dev 1 |

## Dev Agent Record

### Completion Notes

**Ownership.** Dev 3 chose **option B** — Dev 1 implements, Dev 3 reviews before merge. The
deliberate CLAUDE.md §5.4 crossing is unchanged and still needs their sign-off.

**Where the code went.** `schemas.py` (`SessionCreate` / `SessionCreated`), `service.py`
(`create_session` — now the ONLY writer of `sessions` in the codebase), `router.py`
(`POST /sessions`, 201). No migration, no `packages/shared` change — §16 gate not triggered.

**AC-2 is one branch, not two.** `lesson_row is None or user_id mismatch` raises a single
identical 404. Splitting it "for clarity" is the leak: a distinct 403 turns the endpoint into an
existence oracle for lesson ids. A mutation doing exactly that is caught by
`test_a_missing_lesson_returns_the_same_404_as_an_unowned_one`, which compares body as well as
status.

**AC-3 asserts the demo path, not the insert.** `test_a_minted_session_is_accepted_by_grade_quiz_ownership_check`
mints through the endpoint and hands the id to `grade_quiz` backed by a store that only knows
rows the endpoint actually created. It asserts **422, not 200** — reaching answer validation
proves the ownership check passed, which is the thing D18 broke. A first draft of this test was
failing on a *different* 404 (grade_quiz step 2, missing lesson `content`), so it would have
"passed as red" for the wrong reason; the stub now carries real content.

### Mutation testing

9 mutants; **2 initial survivors, both investigated rather than accepted**:

| Mutation | Result |
|---|---|
| D18 restored — no `sessions` writer | CAUGHT (7 tests) |
| unowned lesson gets a distinct 403 | CAUGHT |
| ownership check removed | CAUGHT |
| client-chosen `session_id` sent to DB | CAUGHT |
| client-chosen `started_at` sent to DB | CAUGHT |
| empty-insert guard removed | **SURVIVED → real gap, test added** |
| `user_id` trusted from body (via `getattr`) | survived — **bad mutation**, `SessionCreate` has no such field so it was a no-op |
| `user_id` trusted from body (schema field added too) | CAUGHT — the faithful version |
| reuse-if-exists instead of insert | **survived → the AC-5 test used two independent stubs, so a lookup found nothing and inserted anyway. Rewritten to share one store; the faithful reuse mutation now fails 5 tests.** |

Both survivors were genuine weaknesses in the tests, not in the code — which is the point of
running them.

### Verification (repo-wide, CLAUDE.md binding rule 1)

- `pytest tests/unit tests/integration` — **785 passed**, 1 skipped
- `pytest tests` — 22 failed, **1487 passed** (was 1477; +10 new). Failure set unchanged: Dev 3 19, Dev 4 3.
- `ruff check .` — All checks passed · `ruff format --check .` — clean · `mypy app` — 24 in 3 files, unchanged

Measured on the FULL suite this time. On PR #113 earlier today I measured only the gating scope
and merged a broken root test; that cost is recorded against D24.

### File List

- `apps/api/app/modules/assessment/schemas.py` (modified)
- `apps/api/app/modules/assessment/service.py` (modified)
- `apps/api/app/modules/assessment/router.py` (modified)
- `apps/api/tests/test_session_create_endpoint.py` (new)

### Still required before D18 can be called closed

**AC-6 is not satisfied by this PR and cannot be.** `player.machine.ts:142` must stop calling
`crypto.randomUUID()` and use the returned id — that is Dev 2's change. Until it lands, the
backend is correct and the product still 404s.
