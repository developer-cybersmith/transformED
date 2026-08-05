# Story W3: Generate from chapter — `tier` moves to the chapter card

Status: ready-for-dev

**Track:** W · **Branch:** `book-scale/track-w`
**Depends on:** W2 (the chapter card). **Gates:** W4.
**Restores:** Sprint 2 Learner Mode **S2-09**.

## Story

As a **student looking at my book's chapters**,
I want **to pick a chapter, choose how deep I want to go, and start generation**,
so that **I can actually get a lesson** — which today is impossible from the UI at all.

### This is not new work. It is S2-09, relocated.

Sprint 2's Learner Mode shipped as S2-07 (the `ModeSelection` screen), S2-08 (disclaimers),
**S2-09 (wire the selected tier into lesson creation)** and S2-10 (the tier badge), against Dev 1's
S2-LM1–LM5 backend. S2-09's acceptance criterion reads verbatim:

> Selected tier included in the lesson-creation request body (`FormData.append('tier', …)`)

**Book-scale Phase 6 now rejects exactly that with a 422.** So a completed Sprint 2 task was
invalidated by a later architecture change, and this story restores it at its new home. Nothing
else in Learner Mode broke: `ModeSelection` is untouched (which is why W1 removed only its call
sites), S2-10's badge reads `lesson.metadata.tier`, and S2-LM1–LM5 still drive generation from
`lessons.tier`. Phase 6 changed **where the student supplies the tier**, not what it does.

## Acceptance Criteria

**AC1 — `generateLesson` in `books.service.ts`.**
`POST content/books/{bookId}/chapters/{chapterId}/lessons` with a **JSON** body `{tier}` — not
`FormData`, which is what S2-09 used and what the upload endpoint still takes. Returns
`LessonGenerationResponse {lesson_id, chapter_id, tier, status, job_id: string|null,
truncation_expected: boolean}`. Types from contract v1.1.0.

**AC2 — `ModeSelection` is reused, not rebuilt.**
It takes only `onSelect: (tier: LearnerTier) => void` and imports only `learnerMode.ts`. Do not
copy it, do not fork it, do not change its props. `LEARNER_TIER_TO_BACKEND`
(`types/learnerMode.ts:13-17`, `deep→T1 · balanced→T2 · refresher→T3`) is the mapping — no second
copy. If it needs a visual variant for the card context, add a prop with a default that leaves
the upload-era rendering byte-identical, and say so.

**AC3 — 202 and 200 are different, and the UI must not conflate them.**
**202** = a new lesson was accepted. **200** = an equivalent lesson already existed and is being
returned. Same body shape, and `job_id` is `null` on the 200 path. A student who double-taps
Generate must see "already generating" rather than a second spinner claiming new work.

**AC4 — Every documented failure has a distinct, honest message.**
- **409** — the book is still ingesting. Recoverable by waiting; say so.
- **422** `tier` — a client bug; should be unreachable through the UI. Log it.
- **422** `chapter_too_large` — **the detail is an OBJECT**
  (`{code, page_span, max_page_span, boundary_confidence}`), not a string. W0 taught
  `extractErrorMessage` this shape; reuse it rather than adding a second parser. Show the real
  numbers — "this chapter is 412 pages; the limit is 200" — because the generic fallback throws
  away the only information that explains the refusal.
- **429** — two distinct causes with one status: the per-user concurrency cap (carries
  `Retry-After`) and the rate limit. Both mean "wait", and the message should not guess which.
- **404** — book or chapter gone; the identical-body 404 is deliberate, so do not try to
  distinguish them.

**AC5 — `truncation_expected: true` is surfaced before the student waits 15 minutes.**
It means the chapter is longer than the model can see (~90,000 characters ≈ 40 pages, D46), so
the lesson will cover part of it. Say that plainly at generation time. Do not bury it, and do not
present it as an error — the lesson is still generated.

**AC6 — After 202, the chapter card reflects reality without a page reload.**
Revalidate the chapters query so the card moves to "Generating…". The card's state already comes
from `latest_lesson.status`; use it rather than inventing local state that can disagree with the
server.

**AC7 — The Watch gate is unchanged.** `watchableLessonId` (`books.service.ts`) returns a lesson
id only when `latest_lesson.status === 'ready'`, and never consults `has_lesson`. Do not weaken
it. A chapter whose only lesson is `failed` must offer **Generate**, not Watch — in the real
captured fixture that is chapter 0, where `has_lesson` is `true`.

**AC8 — Tests, MSW-backed, using the real fixtures.**
Cover: tier selection reaches the request body mapped correctly (the S2-09 assertion, re-pointed
at the new endpoint and body shape); 202 flips the card; 200 says "already generating" and does
not double-count; each failure in AC4 renders its own message; `truncation_expected` is shown;
and a failed-only chapter still offers Generate. Fixtures derive from `@/test/fixtures` — do not
re-copy the capture.

**AC9 — Annotate S2-09 in `docs/dev2-sprint-tracker.md`; do not delete it.**
It is marked `✅ DONE` with ACs describing a request that now 422s. That is a stale record. Add a
dated note that Phase 6 moved the tier to the chapter card and that W3 restores it — preserving
the original text, matching how the register handles amendments. Also record that S2-09's 5-agent
review was never run ("code review not yet run"), so this code path still owes one.

**AC10 — Gates.** `pnpm lint`, `pnpm type-check`, `pnpm test` — baseline **63 files / 695 tests**.

## Dev Notes

- Everything that fetches must be `"use client"` — the axios auth interceptor is browser-only
  (`lib/api.ts:18-27`).
- Relative paths, no leading slash: `baseURL` already ends in `/api`.
- The generate endpoint is rate-limited `3/minute;20/hour` **per user**, and the concurrency cap
  is 3 concurrent generations. A UI that retries automatically will burn that budget and lock the
  student out; every retry must be user-initiated.
- `latest_lesson.status` is the **client** vocabulary (`queued|running|ready|failed`), mapped
  server-side from the DB's `generating|ready|failed`. Match on the client values.
- Do not touch `upload.service.ts`'s `extractErrorMessage` beyond importing it, and do not
  reintroduce `tier` anywhere near the upload path — that is the defect this whole phase removed.
