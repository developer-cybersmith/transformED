# Dev 3 — Lesson Delivery handoff

**Sprint goal:** one student, one complete lesson, generated from one real book.
**Your phases:** **L4** (quiz + teach-back on a real package) · **L5** (CES, with Dev 4)
**Master doc:** `docs/LESSON-DELIVERY-TRACKER.md`

> **Naming, once.** This sprint is often called "video generation". What we ship is the **narrated
> interactive lesson**; a compiled MP4 is re-watch-only and out of scope. Your quiz, teach-back and
> CES only exist in the interactive mode — see the tracker §0.

---

## Your one-line status

Your endpoints are built and wired. **The CES formula, however, exists twice — and your copy is dead
code that disagrees with the live one.** That is the highest-value thing you own this sprint.

---

## Deviation 1 — two CES implementations, and yours is unreachable

| | Yours | Dev 4's |
|---|---|---|
| File | `apps/api/app/modules/assessment/ces.py:19-87` | `apps/api/app/modules/tutor/service.py:106-136` |
| Imported by production code? | **No — zero importers.** Only `tests/test_ces.py` | **Yes**, from `tutor/service.py:296` ← `core/websocket.py:393` |
| `quiz_accuracy is None` | keeps the 0.35 weight, feeds it `0.0` | **drops it and redistributes** |

Your file's docstring (`ces.py:4`) says *"Dev 4 imports compute_ces()"*. **He does not** — he wrote
his own.

**Measured, both functions, identical inputs, shipped weights:**

| attention (all three) | `assessment/ces.py` (yours) | `tutor/service.py` (live) | ratio |
|---|---|---|---|
| 1.0 | 53.33 | 100.00 | 1.875 |
| **0.9** | **48.00** | **90.00** | 1.875 |
| 0.8 | 42.67 | 80.00 | 1.875 |
| 0.6 | 32.00 | 60.00 | 1.875 |

A fixed **1.875×** ratio whenever `quiz_accuracy is None`. And `ces_threshold = 50`, so:

> **At 0.9 attention — a student paying near-perfect attention who simply has not reached the first
> quiz yet — your function says INTERVENE and Dev 4's says fine.** The threshold splits them across
> the entire range below 1.0.

**The alignment:** one implementation survives, and the §11 `None`-redistribution behaviour is
agreed explicitly with Dev 4, not inferred. CLAUDE.md §11 documents redistribution
(`each new weight = original ÷ 0.75`), which matches Dev 4's, so the likely outcome is **delete
yours and keep his** — but that is a conversation to have, not a unilateral delete, because the
weights are yours by ownership. **This is SYNC-A in the tracker.**

---

## Deviation 2 — the fraction the wire wants is one division away, and nothing does it

The `attention_signal` frame wants `quiz_accuracy` and `teachback_score`. You already return
everything needed:

- `QuizResult` (`assessment/schemas.py:77-83`) → `correct_count`, `total_count`, **and** `score`
  (`service.py:455` sets `score = quiz_accuracy * 100`). The fraction is `score / 100`.
- `TeachbackResult.overall_score` (0–100) → same division.

**So this is an integration task, not a contract redesign.** But there is a real trap sitting right
next to it:

> **`ces_contribution` is already weight-multiplied.** `service.py:410` returns
> `quiz_accuracy * ces_weight_quiz * 100`; `:601` does the same for teachback. It is the most
> plausible-looking field on the object and it will give a **wrong CES** if anyone sends it. Your
> own comment at `:411-414` warns "do NOT multiply by 100 again".

**The alignment:** expose an unambiguous 0–1 fraction, or document loudly which field the client
must use. And settle the scale question with Dev 2 and Dev 4 — **`ws.ts:90-100` declares every
field as bare `number` and specifies no range at all**, which is more dangerous than disagreeing.

---

## L4 — validate against a real package

Dev 1 hands you a real `lesson_id` when L1 passes. Then:

- Submit every quiz from the **real** package, not a fixture. Confirm scoring, and confirm the
  `sessions` row exists (D18 was closed 2026-08-04 — verify the creation path actually runs).
- Submit one teach-back and confirm the score persists against that session.
- Confirm the payload shapes your endpoints receive match what `package_builder` really produces.

**Why it matters:** every assertion you have today runs against fixtures you wrote. The first real
package is the first chance to find a shape mismatch.

---

## What you owe others

| To | What |
|---|---|
| **Dev 4** | A decision on which CES implementation survives, and the agreed `None` behaviour |
| **Dev 2** | The exact field and scale the client should send for `quiz_accuracy` / `teachback_score` |
| **Dev 1** | Confirmation that quiz/teach-back work against the first real package |

## What you're waiting on

- **Dev 1** — a real lesson id (blocked on OpenAI credits)
- **Dev 4** — agreement on CES ownership and on `behavioral_score`, which has no producer anywhere

---

## Scale & Load (contract-mandated)

- **Unit of work:** one quiz submission = N questions per segment; one teach-back per segment.
- **Fixed budgets vs variable input:** state what happens when a lesson has 12 segments rather
  than 4 — is any per-session aggregation bounded?
- **Scope:** per session, per user.
- **Unbounded:** **`analytics/service.py:54`** selects **every** `sessions.session_id` for a user
  with no bound — enumerated as **D59**, owner Dev 3, trigger "first user with >1,000 sessions".
  It grows for the life of the account.
- **Inherited caps:** the CES weights were sized before MediaPipe existed; re-derive them once real
  head-pose/blink data arrives.
- **Concurrency:** two tabs submitting the same quiz — is the write idempotent?
