# Recommendation: hold Sprint 3, close an architectural gap first

**From:** Dev 1
**Date:** 2026-08-03
**Decision needed:** approval to defer the Sprint 3 start by approximately six weeks

---

## What we found

While testing whether the pipeline could handle a full-size textbook, we found that the
code treats **one PDF upload as one lesson**. The specification says something different,
and has since day one:

> **Phase A — Book Ingestion** — once per book
> **Phase B — Chapter Generation** — per chapter, student-triggered
> — `CLAUDE.md` §9, `docs/bmad/epics/epic-1-content-pipeline.md:47`

A student is meant to upload a book once and then learn any chapter from it. Today the
system cannot represent a book with more than one chapter — the chapter number is set to
the fixed value `1` in code, and the database requires every chapter to belong to a lesson,
which is backwards.

This was not a decision anyone made. The pipeline was built and validated against a
41-page sample chapter, and every default hardened around that one case. The only record
of the assumption is an inline code comment.

## Why it matters

On a real 1,151-page textbook the system does not fail. **It reports success.** It
produces a lesson marked `ready` built from roughly **4% of the book**, and the remaining
96% is dropped with nothing but a log line. A failure we can see is manageable; a success
that is wrong is not.

The reason this was not caught earlier is worth stating plainly: our evaluation harness
crashed on all five test documents and wrote a success-shaped result file anyway. The
check meant to catch this reported that everything was fine.

## Why now is the cheapest moment

- **Nothing is deployed.** Railway is still marked not-deployed in the master tracker.
- **There are zero real student sessions.** 27 books in the database, all developer tests.
- **The database change is in the safe direction** — a required field becomes optional. It
  cannot invalidate any existing row. No backfill, no downtime.
- **Every week we wait, this gets more expensive**, because Dev 2 continues building UI on
  the assumption that one upload equals one lesson.

## What it is not

This is not a rewrite. All eleven generation nodes, their prompts, the Learner Mode tier
logic, the player, quizzes and teach-back are correct and carry over unchanged. What
changes is how work is scheduled and one ownership direction in the database.

Encouragingly, three of the pieces we need already exist and were never wired up: the
chapters table already has the page-range columns, the extractor already computes
per-page text, and the PDF reading library we already ship can read a book's own chapter
list in four seconds at no cost — we simply never called it.

## The ask

Defer the Sprint 3 start (attention tracking, engagement scoring, tutor state machine) and
spend the time closing this gap instead.

| | |
|---|---|
| **Effort** | 39.5 engineer-days — Dev 1: 30, Dev 2: 9.5 |
| **Calendar** | ~6 weeks with Dev 1 alone on the backend; ~3 weeks with a second backend engineer |
| **Scope** | Sprint 2 and Learner Mode only. Sprint 3 items are registered and deferred, not folded in |
| **Frozen contracts touched** | One — the database migration, requiring the standard 4-developer review |

**First step is half a day.** Before committing to the full plan, we test chapter
detection against three or four real target textbooks. That either confirms the estimate
or tells us to adjust it — cheaply, before any code is written.

## Recommendation

Approve the deferral. Sprint 3 builds the adaptive-tutoring layer on top of the lesson
pipeline. Building it on an assumption we already know to be wrong means paying for it
twice.

One item will not wait for a sprint boundary: we found a security gap where a guessed
session identifier allows access to another student's tutor session. It sits in Sprint 3
territory, but I am raising it with Dev 4 immediately rather than scheduling it.
