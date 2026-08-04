# Story 1.15: `lesson_ready` actually reaches a client (book-scale Phase 6.5)

Status: review

**Branch:** `book-scale/track-w` (see Gate note) · **Phase:** 6.5 of 9
**Closes:** D34 · **Owner:** Dev 1, Dev 4 notified (this is Dev 4's `websocket.py` boundary)

> ### Gate note — a second recorded exception, deliberately narrow
> The tracker says Phase 6.5 **Depends on: Phase 6 ✅ Verified**, and Phase 6 is `🧪 Implemented`
> — its exit items 3–4 need one paid generation run, folded into Phase 7 by **D43**.
> Proceeding on Phase 6's *implementation*, at the user's direction, on the same terms as D43:
> **6.5 may be built, and may not be marked Verified, until the Phase 7 run.**
> This is the second use of that exception. It is recorded here rather than assumed because the
> Story Quality review layer flagged precisely this risk — that a narrow exception becomes a
> general rule by being reached for twice without comment. If a third phase needs it, that is the
> signal that the gate rule itself needs amending rather than exempting.

## Story

As a **student who asked for a chapter to be generated**,
I want **the app to tell me the moment my lesson is ready**,
so that **I am not left polling a spinner for the fifteen minutes generation takes**.

### The defect, traced

`content_pipeline_job` publishes to `lesson_ready:{lesson_id}` (`content_pipeline.py:159`) —
deliberately lesson-keyed since D23. One line in the subscriber renames the value:

```python
session_id: str = channel.removeprefix("lesson_ready:")   # pubsub.py:67  ← it is a LESSON id
...
await manager.send(session_id, message)                   # pubsub.py:80
```

`ConnectionManager` keys `_connections` by the `/ws/{session_id}` path param
(`websocket.py:62-63, 72`), which is a real `sessions.session_id`. A lesson id is never a key
there, so `send()` iterates an empty list (`:108-110`) and returns silently. No error, no failed
delivery log — only the misleading `manager.send called session_id=<lesson uuid>` at `:81-84`.

**The register understated it.** The same wrong id is the cache key at `pubsub.py:96-98`, and two
real consumers read that key by **session** id and therefore always miss:
`_seed_learner_tier` (`websocket.py:279`) — so learner tier and `qa_phase` are never seeded from
the package — and `_segment_intervention_messages` (`tutor/service.py:253`) — so the Sprint 3
intervention hot path never finds its pre-generated messages and always returns `{}`. The "dead
code" verdict is true of the WebSocket push only; the cache half is on the Sprint 3 critical path.

**`lesson_waiters:{lesson_id}` does not exist.** `content_pipeline.py:102,168` and D23's closure
notes both describe it as Dev 4's fan-out mechanism. It is referenced only in comments — there is
no writer, no reader, and no key. Do not code against it.

### Why this must land before Phase 7

The frontend currently no-ops `lesson_ready` and gets readiness from polling. So Phase 7's
acceptance run **would pass on polling alone and certify a broken push path**. Fixing it after
the acceptance run means the run proved something that was never true.

## Acceptance Criteria

**AC1 — The id keeps its name.** `pubsub.py` extracts `lesson_id`, not `session_id`. The rename
at `:67` is the entire defect; a variable whose name lies is how it survived review. No value
derived from the channel may be called `session_id` anywhere in the subscriber.

**AC2 — Waiting sessions are resolved from `sessions`, not invented.**
`sessions.lesson_id` is `uuid NOT NULL REFERENCES lessons(lesson_id) ON DELETE CASCADE`
(`20260611000000_initial_schema.sql:177`) and is indexed (`:300`). Resolve
`SELECT session_id FROM sessions WHERE lesson_id = <id>` and deliver to each.
Rejected alternatives, with reasons — do not silently pick one of these instead:
- a `lesson_waiters:{lesson_id}` Redis set — it does not exist and would need a writer in Dev 4's
  connect path, i.e. a second source of truth for something Postgres already knows;
- changing the channel back to session-keyed — D23 made it lesson-keyed deliberately, because the
  worker knows no session.

**AC3 — Zero waiting sessions is a normal outcome, logged as such.** A student who closed the tab
mid-generation has no session. That must log at DEBUG/INFO as "0 sessions waiting", never as an
error, and must not raise. **But it must be distinguishable in the logs from "delivery failed"** —
the current code cannot tell those apart, which is why the defect survived.

**AC4 — Delivery is observable.** Log the resolved count and the ids delivered to. The existing
`manager.send called session_id=…` line is actively misleading and must go. A test asserts
`manager.send` is called with an id a client actually connected under — that assertion is what
closes D34.

**AC5 — The cache is written under every waiting session id.** `_seed_learner_tier` and
`_segment_intervention_messages` read `lesson_package:{session_id}`. Write one entry per resolved
session so both consumers hit. Do **not** change those two consumers — they are Dev 3/Dev 4 code
and their key shape is correct; the writer was wrong.

**AC6 — A session created AFTER the lesson is ready gets nothing, and that is registered.**
The cache is written at publish time, so a student who starts a session on an already-`ready`
lesson has no `lesson_package:{session_id}` entry and `_seed_learner_tier` silently returns.
This story does not fix it (the durable fix is a read-through in `_seed_learner_tier`, which is
Dev 4's file). Register it with an owner and a trigger — binding rule 5.

**AC7 — The existing test that cannot fail is fixed.**
`tests/test_lesson_ready_integration.py:194-211` uses **one string for both ids** and asserts
against a `MagicMock`, so it encodes the defect as its premise and passes either way. Rewrite it
to use a distinct `lesson_id` and `session_id` — with the lesson id NOT registered as a
connection — so the old behaviour fails. This is the guard; without it the fix is
`FIXED-UNGUARDED` under binding rule 7.

**AC8 — Mutation check.** Revert `pubsub.py` to sending the lesson id and confirm the suite goes
red. Record the observed failure. A fix whose guard cannot fail is not fixed.

**AC9 — Gates.** `pytest tests/unit tests/integration` (baseline **1018 passed, 1 skipped**),
`ruff check .` clean repo-wide, `mypy app` no worse than 24 errors in 3 files. Note
`tests/test_lesson_ready_integration.py` lives in the root `tests/` directory, which is CI's
**advisory** step (D24) — so state plainly whether the guard gates or merely reports, and if it
does not gate, say what would make it.

**AC10 — End to end, and it may not be marked Verified here.** Connect a real WebSocket under a
real `session_id` whose `sessions.lesson_id` matches, generate a chapter lesson, and observe the
message arrive. That requires a completed generation — i.e. the Phase 7 paid run. Build and unit-
prove the path now; the live observation is Phase 7's, per the Gate note.

## Tasks / Subtasks

- [x] **T1** — `pubsub.py`: keep the id's name, resolve sessions, deliver per session (AC1–AC4)
- [x] **T2** — cache write per resolved session (AC5)
- [x] **T3** — rewrite the test that cannot fail; mutation-check it (AC7, AC8)
- [x] **T4** — register the late-session gap (AC6); update tracker + D34 (AC9)

## Dev Notes

- The subscriber is a long-lived reconnecting loop. A Supabase read now sits in its hot path —
  it must be wrapped so a DB blip cannot kill the subscriber. Note the existing structure:
  `except asyncio.CancelledError: raise` is a deliberate shutdown signal (DECISION 3) and must
  stay exactly as it is; only the delivery body gains error handling.
- The cache write is already best-effort (`try/except` + warning). Keep that shape: a cache
  failure must never break message forwarding.
- `manager.send` (`websocket.py:108-118`) already tolerates dead sockets and prunes them.
- Do **not** touch `websocket.py` or `tutor/service.py`. The wrong key was written by `pubsub.py`;
  fix the writer.
- Payload shape is frozen: `{type: "lesson_ready", payload: {lesson_id, lesson}}`, matching
  `packages/shared/types/ws.ts`. This story changes routing, not the message.

## Dev Agent Record

### Agent Model Used

claude-opus-5[1m] — 2026-08-04. Implemented directly, not delegated: the change is one function
and one test file, and the whole defect was a naming error that a hand-off would likely reproduce.

### Debug Log References

| | |
|---|---|
| Gating suite | **1029 passed, 1 skipped** (was 1018 / 1) |
| Mutation (AC8) | revert `pubsub.py` to sending the lesson id → **4 tests red**; revert back → 7 pass |
| ruff / mypy | clean repo-wide / 24 errors in 3 files, unchanged |

**AC9 turned up something the AC only asked me to describe.** The guard lived in root `tests/`,
which is CI's **advisory** step (`ci.yml:148`, `continue-on-error: true` per D24) — so the test
closing D34 would have reported and never gated. It is now at
`tests/integration/test_lesson_ready_integration.py`, inside the gating
`pytest tests/unit tests/integration` step. One path constant inside it (`parents[1]` → `[2]`)
moved with it. Binding rule 7 is about a guard that *fails*, not one that merely runs.

**Three tests, not one, were asserting through the defect.** Beyond the named
`test_end_to_end_pubsub_delivery`, both `test_message_shape_forwarded_without_mutation` and
`test_malformed_json_does_not_kill_subscriber` used a single id for channel and session. Each is
re-pointed at distinct ids rather than merely stubbed, so a routing regression fails in three
places instead of one.

**Two tests added** beyond the ACs: every waiting session receives the lesson (two tabs on one
lesson — delivering only to the first leaves the other spinning on a built lesson), and zero
waiting sessions is quiet rather than a failure.

### Completion Notes List

- D34 **closed**. Neither consumer (`_seed_learner_tier`, `_segment_intervention_messages`) was
  touched — their key shape was correct; the writer was wrong.
- `lesson_waiters:{lesson_id}` was deliberately **not** built. It has no writer, no reader and no
  key anywhere — only comments in `content_pipeline.py:102,168` describing it as Dev 4's fan-out.
  `sessions.lesson_id` is the same fact, NOT NULL and indexed.
- The session lookup **never raises**: it runs inside the subscriber's listen loop, and a Supabase
  blip must not tear down the only path delivering lesson-ready events. It degrades to "nobody was
  waiting", which the caller already handles — and logs at `exception` so the degradation is not
  silent, which is the failure mode this whole story is about.
- **Not Verified.** AC10 needs a real socket, a real session and a real completed generation —
  Phase 7. Second use of the D43 exception, recorded in the Gate note rather than assumed.
- **D55** registered: a session started *after* a lesson is `ready` gets no cache entry. Owner
  Dev 4; the fix is a read-through in `_seed_learner_tier`, which this story does not own.

### File List

- `apps/api/app/core/pubsub.py` (modified — `_sessions_awaiting`, routing, per-session cache)
- `apps/api/tests/integration/test_lesson_ready_integration.py` (moved from `tests/`, rewritten)
- `docs/DEFECT-REGISTER.md` (D34 closed, D55 added) · `docs/book-scale-phase-tracker.md`
