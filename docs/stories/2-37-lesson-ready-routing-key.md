# Story 2.37: Key `lesson_ready` by `lesson_id`, deliberately (D23)

Status: ready-for-dev

## Story

As a student waiting for a lesson to finish generating,
I want the `lesson_ready` push to arrive on a channel someone is actually subscribed to,
so that the player leaves the "generating…" state without a manual page refresh.

**Source:** `docs/DEFECT-REGISTER.md` **D23**. Found 2026-07-29. **Dev 4 chose option A** in
`docs/handoffs/dev4-handoff-2026-07-29.md` §2 — key by `lesson_id`.

## The defect

`app/workers/jobs/content_pipeline.py:81`:

```python
# session_id is the WebSocket routing key; falls back to lesson_id until
# the upload route stores it (Sprint 2 — Dev 4 coordinates)
session_id: str = lesson_row.get("session_id") or lesson_id
```

**`lessons` has no `session_id` column.** Confirmed against `supabase/migrations/` — zero
matches in its `CREATE TABLE` and no later `ADD COLUMN`. So `.get("session_id")` is *always*
`None`, the fallback *always* fires, and the pipeline publishes to `lesson_ready:{lesson_id}`.

Meanwhile `app/core/websocket.py:67-74` registered connections under the **client-supplied**
`session_id` (`crypto.randomUUID()`, `player.machine.ts:142`). The two keys could never match,
so **`lesson_ready` reached no client at all.**

The comment describes a temporary state ("falls back … until the upload route stores it") that
became permanent, and nothing flagged it. This is RC-1 again: the worker's tests assert that a
publish happened; the WebSocket tests assert routing works given a `session_id`; both suites are
green and nothing reconciles the key.

## The decision — Dev 4's, recorded

**Option A: key by `lesson_id`.** Generation completion is a property of the *lesson*, not of a
viewer: a lesson is generated once and can be watched in many sessions. Dev 4's reply:

> "Agree — generation is lesson-scoped, not session-scoped. Your current fallback to `lesson_id`
> is already the right key; nothing to change on your side."

Dev 4 implements the routing half: the WS handler adds `session_id` to a Redis set
`lesson_waiters:{lesson_id}` (24h TTL), and the subscriber that receives `lesson_ready:{lesson_id}`
fans out to every waiting session. No schema change, so the §16 four-dev gate is not triggered.

### Why there is still work on Dev 1's side

"Nothing to change" is true of the **behaviour** and false of the **code**. Today the correct
channel is produced *by accident* — via a `.get()` on a column that does not exist. Two
consequences:

1. **It is one migration away from silently breaking.** The moment anyone adds a `session_id`
   column to `lessons` for any unrelated reason, the publish key changes under Dev 4's routing
   with no test failing. The routing contract must not be a side effect of a schema absence.
2. **It reads as unfinished.** The comment invites the next person to "finish" it by wiring the
   column up — which would re-break the delivery path that was just agreed.

`test_schema_column_guard.py` does **not** cover this: it walks `.table(x).select(...)/.eq(...)`
and this is a `dict.get()` on an already-fetched row. That gap is worth knowing about.

## Acceptance Criteria

1. **AC-1 — The channel is `lesson_ready:{lesson_id}`, by explicit construction.** The
   `session_id` variable and its `lesson_row.get("session_id")` read are removed. The channel is
   built from `lesson_id` directly, with a comment recording that this is Dev 4's option A and
   why (generation is lesson-scoped).
2. **AC-2 — Asserted on the observable publish, not on a variable.** A test must capture the
   actual `redis.publish` call and assert `channel == f"lesson_ready:{lesson_id}"`. Asserting
   that a local variable equals `lesson_id` would pass against the accidental version too, and
   would therefore prove nothing (`DEFECT-REGISTER.md` BD-2).
3. **AC-3 — The premise is pinned: `lessons` must not gain a `session_id` column silently.** A
   test parses `supabase/migrations/*.sql` and asserts `lessons` has no `session_id` column. If
   someone adds one, that test fails and points at this story — turning the trap in §2 above into
   an explicit conversation instead of a silent routing change. Per CLAUDE.md binding rules 3
   and 4: the routing contract depends on a schema fact, so the schema fact gets an executable
   assertion.
4. **AC-4 — The payload shape is unchanged.** `{type: "lesson_ready", payload: {lesson_id,
   lesson}}`, matching `packages/shared/types/ws.ts`. This story changes the **channel**, not the
   contract — no §16 gate.
5. **AC-5 — No regression.** Full suite shows exactly the pre-existing failures. `ruff check`,
   `ruff format --check` and `mypy app` produce no findings not already at baseline, measured
   **repo-wide** (CLAUDE.md binding rule 1).

## Tasks / Subtasks

- [ ] Task 1 (AC-3): premise test — `lessons` has no `session_id` column.
- [ ] Task 2 (AC-1, AC-2, AC-4): remove the dead read; assert on the captured publish call.
- [ ] Task 3 (AC-5): full suite, lint, types.

## Dev Notes

- **Do not add a `session_id` column to `lessons` to "make the code honest".** That is option B,
  which Dev 4 did not choose; it also triggers the §16 four-dev gate and makes a generation job
  care about a viewer. The fix is to delete the read, not to satisfy it.
- **Do not publish to both channels** (option C). Two keys for one event is the shape that rots —
  one of them stops being maintained and nobody knows which.
- **The `session_id`-in-payload comment at line 139 is now stale** and must be corrected in the
  same change: it explains why `session_id` is not duplicated into the payload because it is
  "already the channel suffix". After this story the channel suffix is `lesson_id`. Leaving it
  would be a comment that actively misleads the next reader about the routing contract.
- Every new test needs `@pytest.mark.unit` (and `asyncio` where async).

### Explicitly OUT of scope

- Dev 4's `lesson_waiters:{lesson_id}` set and the subscriber fan-out — their module.
- `app/core/pubsub.py`'s channel-name parsing — Dev 4 confirmed they own the routing half.
- Story 2-35 / D18 session minting. Related, but neither blocks the other (Dev 4 agrees).

### Project Structure Notes

Touches `apps/api/app/workers/jobs/content_pipeline.py` and tests. **No**
`packages/shared/*`, **no** `supabase/migrations/*` — §16 gate not triggered. Zero `apps/web/**`.

### Branching

`sprint2/dev1-d23-lesson-ready-routing-key`, based on `main`.

### References

- [Source: docs/DEFECT-REGISTER.md — D23; RC-1]
- [Source: docs/handoffs/dev4-handoff-2026-07-29.md §2 — the three options and Dev 4's answer]
- [Source: CLAUDE.md binding rules 1, 3, 4]

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-29 | Story created for D23 after Dev 4 chose option A. Scope is deleting an accidental correctness, not changing behaviour. | Dev 1 |
