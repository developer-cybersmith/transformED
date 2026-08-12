# Story W0: Contract harness — MSW, real fixtures, and a CI job that can go red

Status: ready-for-dev

**Track:** W (Dev 1 executing on Dev 2's behalf) · **Branch:** `book-scale/track-w`
**Depends on:** nothing. **Gates:** W1.

## Story

As **the team**,
I want **the frontend's tests to fail when the frontend disagrees with the real API**,
so that **`apps/web` CI cannot stay green while the product is dead**.

### Why this is first

`apps/web/src/__tests__/services/upload.service.test.ts:53` asserts
`expect(body.get('tier')).toBe('T3')` against a mocked `@/lib/api`. The backend now returns
**422** for exactly that field. **That test passes today and will keep passing.** So will
`UploadFlow.test.tsx:137,152`, which assert `uploadLessonMock` was called with `'T1'`/`'T3'`
one layer up, and `READY_STATUS` at `:58`, which fabricates a lesson-shaped poll response that
the endpoint can no longer produce.

Green CI over a product that 422s on 100 % of uploads is the 2026-07-29 failure moved one layer
up. Fix the harness before fixing the code, or the fix has nothing to confirm it.

## Acceptance Criteria

**AC1 — MSW is installed and wired.** `msw` is a devDependency. `apps/web/vitest.config.ts`
currently has **`setupFiles: []`** — create the setup file and register it. `server.listen({
onUnhandledRequest: 'error' })` — an unhandled request must fail the test, not pass silently.

**AC2 — Handlers are generated from the frozen contract, not hand-written.**
`docs/contracts/book-api.v1.json` is at **1.1.0** and its `real_example` block was captured on
2026-08-04 from the real 1,151-page run (1,151 pages, 21 chapters, and a chapter carrying **two**
lessons at different tiers). Build the fixtures from that block. Do not invent values; do not
copy the old `apps/web/src/mocks/` hand-rolled fixture layer, which is a different thing (plain
async functions imported directly by services, not network interception).

**AC3 — Handlers cover every book-scale endpoint and every documented failure.**
`GET /content/books`, `GET /content/books/:id`, `GET /content/books/:id/chapters`,
`POST /content/lessons` (202 **and** the 422-on-tier), and
`POST /content/books/:id/chapters/:cid/lessons` (202, 200-idempotent, 404, 409, 422 tier,
422 `chapter_too_large`, 429). The `chapter_too_large` detail is an **object**
(`{code, page_span, max_page_span, boundary_confidence}`), not a string — see AC6.

**AC4 — The mutation check, which is the actual exit criterion.**
Rename a field in a fixture (e.g. `chapter_count` → `chapterCount`) and a test **must** go red.
Prove it: run the mutation, capture the failure, revert. A harness that cannot go red is not a
harness. Record the command and the observed failure in the story's Debug Log.

**AC5 — The three false-confidence tests are corrected, not deleted.**
`upload.service.test.ts:46-54` (`tier` sent), `:20-36` (`lesson_id` in the response fixture), and
`UploadFlow.test.tsx:137,152` assert a contract that now 422s. Invert them: the service must
**not** send `tier`, and the response has **no** `lesson_id`. Keep `:66-68`'s `expectTypeOf`
tripwire — it fails loudly when the parameter is removed, which is correct and wanted.

**AC6 — `extractErrorMessage` learns the object-shaped detail.**
`upload.service.ts:59-67` handles a string `detail` and FastAPI's array form. The new 422 uses an
**object**, so both branches miss and it silently returns the fallback — throwing away
`page_span`/`max_page_span`, the only information that tells the user why their chapter was
refused. Add the branch, with a test.

**AC7 — A contract CI job that cannot pass by skipping.**
`.github/workflows/ci.yml` has an `api` job and a `web` job. Add a job that boots the API,
fetches `/openapi.json`, and diffs the book-scale paths and response schemas against
`docs/contracts/book-api.v1.json`. **Copy the anti-vacuum pattern from the `Migration tests` step
(`ci.yml:89-126`)** — and note *why* it looks like that: D51, where the original guard matched
only an all-skipped run, so a partial skip passed green for weeks. Assert a non-zero comparison
count.

**AC8 — CI triggers.** `ci.yml:3-7` triggers on push to `main`/`dev` and PRs to `main` only, so
**PRs into `book-scale/integration` run no CI at all**. Either add the branch or record the
decision with an owner and a trigger. Do not leave it implicit.

**AC9 — Gates.** `pnpm lint`, `pnpm type-check`, `pnpm test` all clean. Baseline is 53 files /
506 passing; report the new numbers.

## Dev Notes

- **Stack reality:** Next **16.2.9**, React **19.2.4**, Vitest 3.2.6, jsdom, Tailwind v4 — *not*
  the Next 14 CLAUDE.md claims (D36). Middleware is `src/proxy.ts`, not `middleware.ts`.
- `@testing-library/jest-dom` is a devDependency but **never imported** (no setup file exists), so
  assertions use `expect(x).not.toBeNull()` rather than `toBeInTheDocument()`. If you add it to the
  new setup file, say so — it changes the idiom repo-wide.
- `apps/web/src/lib/api.ts` is axios with `baseURL = NEXT_PUBLIC_API_URL || "http://localhost:8000/api"`.
  Services use relative paths without a leading slash (`'content/lessons'`). MSW handlers must
  match the resolved absolute URL.
- ~~⚠️ `ci.yml:188` sets `NEXT_PUBLIC_API_URL: http://localhost:8000` — **without** `/api`.~~
  **FIXED 2026-08-11** (D31, Story 3-35) — `ci.yml` and `.env.example` both now carry
  the `/api` suffix. This note is kept for context on why the trap existed, not because
  it still does.
- Tests live in `apps/web/src/__tests__/`, mirroring `src/`. Idiom is `vi.hoisted()` + `vi.mock()`.
  MSW replaces the *module* mock for network-level tests — do not do both for the same test.
- `UploadFlow.test.tsx:261-278` genuinely sleeps ~10 s because fake timers break framer-motion's
  `AnimatePresence`. Do not "optimise" it into fake timers.
