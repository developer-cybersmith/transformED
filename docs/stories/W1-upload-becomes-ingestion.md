# Story W1: Upload becomes ingestion — poll the book, not the lesson

Status: ready-for-dev

**Track:** W · **Branch:** `book-scale/track-w`
**Depends on:** W0 (fixtures + MSW). **Gates:** W2.

## Story

As a **student uploading a textbook**,
I want **the upload to succeed and show me the book's chapters appearing**,
so that **I can pick one to study** — instead of the error the app produces today on every
single upload.

### The break, precisely

`UploadFlow.tsx`'s only route into `'processing'` is `handleTierSelect` (`:74-79`), so
`selectedTierAtUploadRef` is **always** non-null by the time the effect runs (`:155-157`). It
therefore always appends `tier` (`upload.service.ts:43`), and the backend 422s on `tier`
unconditionally (`router.py:628-637`). **100 % of uploads fail**, and the user is shown the raw
backend string *"tier is no longer accepted on upload — a book has no tier…"*.

Correction to the tracker's wording, verified in recon: with `tier` merely dropped, it does **not**
"poll forever". `res.lesson_id` is `undefined`, the first poll hits `content/lessons/undefined`,
the backend 4xxs, `isClientError` (`:139`) is true and it **fails fast on poll #1** with *"Lesson
not found — please try uploading again."* Same outcome, different symptom — worth knowing so the
fix is not mis-aimed.

## Acceptance Criteria

**AC1 — The service matches the real endpoint.**
`upload.service.ts`: `uploadLesson` loses its `tier` parameter entirely (`:35`, `:43`), and its
return type becomes `BookUploadResponse {book_id, job_id, status}` — **`lesson_id` is gone**
(`:5`, `:13`). Keep the 50 MB `MAX_UPLOAD_SIZE_BYTES` guard (`:25`).

**AC2 — Polling targets the book.**
New `getBookStatus(bookId)` hitting `content/books/{book_id}`, returning
`BookResponse {book_id, filename, status, page_count, chapter_count, created_at}`. Book status
vocabulary is **`processing | ready | failed`** — *not* the lesson vocabulary
(`queued|running|ready|failed`), so `UploadFlow.tsx:116-119`'s terminal condition and
`upload.service.ts:10`'s `LessonStatus` union do not apply. Reuse `lib/lessonStatusPoll.ts`'s
`nextPollInterval` (`:26-36`) — it takes a boolean and works unchanged — but **not**
`isLessonProcessing` (`:15-17`), which checks the lesson vocabulary.

**AC3 — The state machine drops tier selection.**
`handleFile` (`:63-72`) goes straight to `'processing'`. Remove the `'selecting-mode'` state
(`:22`), `handleTierSelect` (`:74-79`), `handleCancelModeSelection` (`:81-89`),
`selectedTier`/`selectedTierAtUploadRef` (`:26`, `:35`), the tier pill (`:276-283`),
`data-selected-tier` (`:258`) and the `selecting-mode` render block (`:223-247`).
**`ModeSelection.tsx` itself is NOT deleted and NOT modified** — it takes only `onSelect` and is
already fully decoupled. It moves to the chapter card in W3. Deleting it would mean rebuilding it.

**AC4 — Success goes to the book, not a lesson.**
`router.push('/lesson/${lessonId}')` (`:306`) becomes `/books/{book_id}`. W2 creates that route;
until then the push target is correct and the destination 404s — **say so in the story's
completion notes**, do not paper over it with a temporary redirect.

**AC5 — Progress reflects ingestion, honestly.**
Ingest was measured at **90.3 s end-to-end for a 1,151-page book** (58.0 s of it upload). The
existing copy at `UploadFlow.tsx:14` says "chapter generation can take up to ~15 minutes" — that
is now the *generation* number, not ingestion. Show chapters appearing (`chapter_count`) rather
than a fake percentage.

**AC6 — Failure is legible.** `books.status === 'failed'` must produce a real message and a retry
affordance, not a spinner that never resolves. The 20-minute worst case
(`MAX_POLL_ATTEMPTS = 240` × `POLL_INTERVAL_MS = 5000`, `:12`/`:17`) must still terminate.

**AC7 — Tests, against MSW.** Cover: upload succeeds and returns `book_id`; **no `tier` is ever
sent** (assert the FormData has no such key); polling transitions `processing → ready`;
`failed` surfaces; the 20-minute cap terminates. The unmount/cancel path (`:169-172`) must keep
working — it is already correct, do not regress it.

**AC8 — Gates.** `pnpm lint`, `pnpm type-check`, `pnpm test` clean.

## Dev Notes

- Auth is attached by an axios request interceptor that is **browser-only**
  (`lib/api.ts:18-27`, `typeof window !== 'undefined'`). A server component calling `api` gets no
  auth header. Anything fetching must be `"use client"`.
- `UploadFlow` has no external store — inline `useState` plus one `useEffect` with a hand-rolled
  self-rescheduling `setTimeout` (`:99-153`). `lib/lessonStatusPoll.ts` exists but is used only by
  `useLibrary`/`useDashboard`, not here.
- Do not introduce a new state library. Do not rewrite the polling loop into fake timers —
  `UploadFlow.test.tsx:261-278` documents that fake timers break framer-motion's `AnimatePresence`.
