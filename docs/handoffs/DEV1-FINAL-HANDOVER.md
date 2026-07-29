# Dev 1 — final handover

**From:** Dev 1 (infra · content pipeline · 11 nodes · providers · embeddings · Langfuse)
**Date:** 2026-07-30
**Status:** **Dev 1 has nothing outstanding that Dev 1 can act on.** Everything below is either
merged, owned by someone else, or has a named trigger.

This is the single document to read. If something contradicts an older handoff, this wins.

---

## 1. The one-paragraph version

Sprint 0, 1 and 2 are complete and merged. Every defect Dev 1 owned is fixed, guarded by a test
that fails if it returns, and on `main`. CI's lint, format and web jobs are green — the first
green web job in the repo's history was 2026-07-30. **Three things block the demo and none of
them are Dev 1's:** Dev 2's `player.machine.ts` change (§4), Dev 3's review of PR #119 (§3), and
24 mypy errors split between Dev 3 and Dev 4 (§5).

---

## 2. State of `main` — measured, not assumed

Run these yourself; they are the same commands CI runs.

| Gate | Command (from `apps/api`) | Result 2026-07-30 |
|---|---|---|
| Lint | `ruff check .` | **All checks passed** |
| Format | `ruff format --check .` | **164 files already formatted** |
| Types | `mypy app` | ❌ **24 errors in 3 files** — see §5 |
| Tests (gating) | `pytest tests/unit tests/integration` | **793 passed**, 1 skipped |
| Tests (advisory) | `pytest tests` | 22 failed, **1485 passed** — see §5 |
| Web | `pnpm test` / `pnpm build` in `apps/web` | **506 passed** · build green |

**The 22 failures are not Dev 1's and not new.** `test_dna_growth.py` 18 + `test_dna_fusion.py` 1
(Dev 3), `test_tutor_service.py` 3 (Dev 4). They have never been investigated by Dev 1 because
guessing at another dev's intent would be worse than saying so.

### CI history — context that matters

CI failed **60 of its last 60 runs** before 2026-07-29, and merges proceeded anyway. It died at
`ruff check` — *step 5 of 9* — so it had **never reached a test step at all**. The web job died
even earlier, at `setup-node`, on a lockfile path that pointed inside `apps/web` when this is a
pnpm workspace with one lockfile at the repo root. That was Dev 1's bug and it meant
`apps/web` **had never produced a production build and was never deployable**.

Cleared in sequence: Dev 4 (`a1ebbbe`), Dev 3 (#115), Dev 1 (#117 format), Dev 2 (#158e51f,
the `/signin` Suspense boundary). **mypy is now the only remaining API gate.**

Each gate cleared revealed the next. That is why "the lint is broken" was never one number.

---

## 3. ⚠️ PR #119 — the only Dev 1 PR still open, and it needs Dev 3

**`feat(s2-35): mint sessions server-side — POST /api/assessment/sessions (D18)`**

This is the **last live-in-production defect**. Nothing anywhere created a `sessions` row, so
quiz and teach-back returned **404 for every student, always**. The demo cannot complete.

Dev 3 chose **option B** — Dev 1 implements, Dev 3 reviews before merge. The code lands in
`app/modules/assessment/`, Dev 3's module, which is a deliberate CLAUDE.md §5.4 crossing.

**Dev 1 will not merge this unilaterally.** That was the agreement, and merging it would make the
agreement worthless. Three questions are waiting in the PR:

1. Is `create_session` in the right place in `service.py`, and does the signature match your conventions?
2. Sessions are **attempt-scoped** — re-learning the same lesson creates a new row. Correct for your CES history?
3. `ended_at` is deliberately out of scope (Dev 4, WS disconnect). Agreed?

**If Dev 3 is unavailable and the demo is needed, the call to merge without review is the project
lead's, not Dev 1's.** Say so explicitly rather than letting it happen quietly.

---

## 4. What each dev needs to do — the complete list

### Dev 2 — one change, and it is the demo blocker's other half

`apps/web/src/stores/player.machine.ts:142`:

```ts
// before — this UUID has never existed in any database
sessionId: crypto.randomUUID(),

// after — the server mints it
const { session_id } = await api.post('/api/assessment/sessions', { lesson_id: lessonId })
```

**Call it once when the lesson starts, not per segment.** Each call creates a new attempt row,
which is intentional — re-learning must produce a new session for CES history.

Returns `201` with `{ session_id, lesson_id, started_at }`. A lesson you don't own returns `404`
(not 403 — deliberate, so it can't be used to enumerate lesson ids).

**Blocked on PR #119 merging.** Until both halves land, quiz and teach-back still 404.

Also still open from the 2026-07-29 handoff, unchanged:
- **Virtual playback clock** — the fix for the 0:00-quiz-fires-instantly symptom. Backend half shipped; you will see no difference until this lands.
- **`retryAudio()` can't recover from an expired URL** — signed-URL expiry raised 1h → 8h so the window shrank, but there is still no re-sign path anywhere.

### Dev 3 — one review, and the mypy debt

1. **Review PR #119** (§3). This is the demo blocker.
2. **19 mypy errors in `app/modules/assessment/service.py`** — the only substantive static work
   left in the repo. All the same shape: indexing a `JSON` union without narrowing first. A
   formatter won't touch them. Dev 1 offered to share the pattern (same class of fix was done in
   `content/router.py`) and that offer stands.
3. **19 failing tests** — `test_dna_growth.py` 18, `test_dna_fusion.py` 1. Advisory, not gating.

### Dev 4 — routing half, session close, and 5 mypy

1. **`lesson_ready` fan-out.** Dev 4 chose option A and Dev 1 has landed the publish side: the
   channel is now `lesson_ready:{lesson_id}`, built explicitly. Dev 4's `lesson_waiters:{lesson_id}`
   set + subscriber fan-out is the other half.
   ⚠️ **`lessons` has no `session_id` column, and a test now enforces that.** If anyone adds one,
   `test_lesson_ready_routing_key.py` fails and points at Story 2-37 — read it before changing
   the routing key.
2. **`sessions.ended_at` is never written.** Session termination belongs with WS disconnect. Dev 3's
   duration and CES-final logic has never run against a real end time.
3. **5 mypy errors** — `core/websocket.py` 4, `tutor/state_machine/graph.py` 1.
4. **3 failing tests** in `test_tutor_service.py`. Advisory, not gating.

**Retraction that still stands:** the `{**state, ...}` duplication bug is **not** live in the
tutor graph. Six sites exist but there are no `operator.add` reducer channels, so `LastValue`
overwrites and the spread is a no-op. It is a loaded gun with no round in it — the day anyone adds
one list-shaped reducer channel to `TutorState`, all six become duplication bugs simultaneously.
`tests/unit/test_node_return_shape.py` can be pointed at `modules/tutor/` as cheap insurance.

### Project lead / whoever runs spend

**Every cost figure in this repo is an estimate.** The `$3.00/lesson` ceiling is *enforced* at
runtime but was never *measured*: until 2026-07-30 the eval harness contained zero references to
cost. Story 2-38 built the meter. The baseline lands when someone runs, with live credentials:

```
pytest tests/evals/test_live_run.py -v --run-live-eval
```

Real money, ~15 min/lesson × 5 PDFs. The run now reports total, mean, and **names any lesson that
breached the ceiling**.

---

## 5. Open register items — all 5, with owners and triggers

`docs/DEFECT-REGISTER.md` is authoritative. **22 closed, 5 open, 1 live in production.**

| ID | What | Owner | Trigger to act |
|---|---|---|---|
| **D18** | `sessions` has no writer → quiz/teach-back 404 for every student | **Dev 3 review + Dev 2** | Now. PR #119 + `player.machine.ts`. |
| D21 | Embed truncation assumes ~4 chars/token; measured Hindi **1.06**, Tamil **0.71** | Dev 1 | **The first Indic-language lesson.** English-only was an explicit decision. One-line fix already specified. |
| D24 | Full-suite + web test steps land advisory, not gating | Dev 3 / Dev 4 | The 22 failures reach zero. Then drop `continue-on-error`. |
| D26 | CI red for 60 straight runs | Dev 3 / Dev 4 | mypy reaches zero — the last API gate. |
| D28 | `detect_headings` ranks a chapter **below its own subsections** | Dev 1 | **The Sprint 3 docling migration.** Pinned as current behaviour so the fix cannot land silently. |

**None of these is a "documented limitation".** Every one carries a condition that reopens it —
that distinction is CLAUDE.md binding rule 5, and it exists because 131 `[Review][Defer]` markers
once produced **zero** registered items.

---

## 6. Things only Dev 1 knows — the ones that would be lost

Written down because they are not derivable from the code.

1. **9 of 11 pre-existing defects never worked for a single minute.** Only 1 of 17 was a true
   regression. This is not an unstable codebase; it is one whose verification never confirmed
   anything worked, so the same never-tested assumption resurfaces in a new subsystem and *feels*
   like recurrence. Median time-to-discovery was 13 days — which measures when a human read the
   code, not when anything detected anything.

2. **RC-1 explains 12 of 17 defects: mocks are written by the consumer and never reconciled with
   the producer.** CLAUDE.md's Week-1 rule *"each dev mocks the other's interface"* was correct at
   the time and has **no expiry clause**. It is now the primary bug-concealment mechanism. 567 of
   2,328 assertions (24%) describe a conversation with a mock rather than an outcome.
   D18 is the pure case: Dev 3 seeded the session row in fixtures, Dev 2 mocked the POST, both
   suites green, product 404s for every student.

3. **Mutation-test your own guards.** Every fix in this final push was mutated. It caught, among
   others: a schema guard that skipped `.select(_LIST_COLUMNS)`; a "no LLM call" test that watched
   one method while `provider.complete()` sailed past; a re-learning test whose two independent
   stubs made a reuse-if-exists implementation undetectable; and a cost test that passed via the
   failure path without ever exercising the success path. **All four were green before mutation.**

4. **A finding can be wrong.** D15 was rejected: a reviewer called a test a mathematical
   tautology, and mutation testing showed it catches three distinct implementation changes. It is
   redundant, not tautological. Deleting a working test on a false premise is worse than keeping a
   redundant one — that rejection is recorded so the claim isn't re-raised.

5. **Verification scope = CI scope.** Dev 1 broke this on 2026-07-29 — measured "no regression"
   against the gating scope, merged, and put a broken root test on `main` for an hour. The cost is
   recorded against D24. The gating scope does not cover root `tests/`; use `pytest tests`.

---

## 7. What Dev 1 deliberately did **not** do

Each of these is a decision, not an omission.

| Not done | Why |
|---|---|
| Merge PR #119 | Dev 3 chose option B. Merging without review makes the agreement worthless. |
| Fix D28 (chapter/subsection inversion) | Story 2-34's premise is that removing an inert LLM call is behaviour-**preserving**. Changing detection precedence contradicts it. Parked for Sprint 3 docling, pinned by a test. |
| Fix D21 (Indic tokenisation) | Explicit English-only decision. Fix is one line and already specified. |
| Touch `apps/web` source | Dev 2's domain. The only exception is one added line in `package.json` (`"type-check": "tsc --noEmit"`), which CI already assumed existed. |
| Investigate the 22 failing tests | Dev 3's and Dev 4's files. Guessing at their intent would be worse than reporting the number. |
| Run the live eval | Costs real money; deferred by explicit decision. The meter is built and tested. |
| Fix Dev 3's/Dev 4's mypy errors | Substantive, not mechanical — a wrong narrowing changes behaviour in their modules. |

The one line Dev 1 **did** cross: `ruff format` on 5 files owned by Dev 3 and Dev 4 (PR #117),
after saying in both handoffs it wouldn't. The formatter has no judgement in it, nothing was in
flight, and it was the last thing between the repo and a green run. The whole diff was read
rather than trusted — every change was line-joining or redundant parens.

---

## 8. Where things live

| | |
|---|---|
| Authoritative defect record | `docs/DEFECT-REGISTER.md` |
| Binding engineering rules | `CLAUDE.md` → *Defect Register — READ BEFORE FIXING ANYTHING* |
| Per-dev handoffs (2026-07-29) | `docs/handoffs/dev{2,3,4}-handoff-2026-07-29.md` |
| Dev 1 task tracker | `docs/dev1-tracker.md` |
| Stories | `docs/stories/2-3{1..8}-*.md` |
| Eval harness | `apps/api/tests/evals/` |

---

## 9. Sprint 3 / Sprint 4 — not started, and correctly so

`docs/dev1-tracker.md` shows Sprint 3 at 2/6 and Sprint 4 at 0/7. That is **not** outstanding
work from Sprints 1–2 — those are future-sprint tasks. Two carry hard prerequisites worth
surfacing now:

- **Railway has no India region.** FastAPI/ARQ must migrate to an India-region provider (Fly.io
  Mumbai, Render Singapore, or AWS ap-south-1) **before** Sprint 3 real students. This is a
  DPDP-adjacent deployment constraint, not a performance preference.
- **The `user_consents` audit table does not exist.** `users.attention_consent` (a boolean) is
  insufficient for DPDP Act 2023. It is required **before any attention data is collected** —
  i.e. before MediaPipe ships in Sprint 3.

---

## What Dev 1 needs from the team

**Nothing to unblock Dev 1.** One thing to unblock the demo:

> **Dev 3: review PR #119. Dev 2: the one-line `player.machine.ts` change once it merges.**

That is the entire critical path to a lesson that completes end to end.
