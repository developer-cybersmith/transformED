# Story 2.35: Mint sessions server-side (D18 — demo blocker)

Status: ready-for-dev

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

- [ ] Task 1 (AC-1, AC-2): `POST /api/assessment/sessions` + service function; ownership check.
- [ ] Task 2 (AC-3, AC-4, AC-5): tests — end-to-end mint→submit, unminted id still 404, re-learn yields a new id.
- [ ] Task 3 (AC-6): handoff note for Dev 2 + register update.
- [ ] Task 4 (AC-7): full suite, lint, types.

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
