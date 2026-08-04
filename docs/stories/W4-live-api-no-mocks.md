# Story W4: The book-scale UI runs against the live API — and a guard that keeps it that way

Status: review

**Track:** W · **Branch:** `book-scale/track-w`
**Depends on:** W3. **Gates:** Phase 7.

## Story

As **the team**,
I want **the book-scale screens to be provably free of mock data, and a guard that fails if one
creeps back**,
so that **Phase 7's browser run proves the product works rather than proving the fixtures do**.

## The phase's premise was wrong, and that is the finding

The tracker defines W4 as *"MSW off — the whole UI against the live API"*. That assumed MSW would
be intercepting requests in the running app, as it commonly is (`mocks/browser.ts` + a service
worker), and would need switching off for a real run.

**It never was.** W0 installed `msw` as a **devDependency** and wired it only into
`vitest.config.ts`'s `setupFiles`. Verified: every file importing `msw` is under `src/test/` or
`src/__tests__/`. Nothing in the app path imports it, so there is nothing to turn off.

What *does* stand between this UI and a real backend is the older hand-rolled `src/mocks/` layer —
plain async functions imported directly by services. Measured across `src/`:

| Service | State |
|---|---|
| `books.service.ts` | **zero** mock imports — the entire book/chapter/generate path is real |
| `upload.service.ts` | **zero** mock imports |
| `lesson.service.ts` | `getLessonPackage` (the player's content) is **real**; `getLesson` and `updateProgress` are mock-backed **and unreachable** — no caller anywhere outside the file and its tests |
| `dashboard.service.ts` | lesson data is **real** (`content/lessons`); only `learningPulse` is mock, in an explicit try/except that fails to `undefined` — Dev 3's analytics domain |
| `reports.service.ts`, `settings.service.ts` | mock — Dev 3 / settings domain, outside book-scale |

So the book-scale path is **already mock-free**, by construction rather than by decision. This
story's job is not to remove mocks. It is to (a) prove that claim mechanically, (b) stop it
silently becoming false, and (c) hand Phase 7 a UI whose green screens cannot be fixture-shaped.

## Acceptance Criteria

**AC1 — A guard that fails when a mock re-enters the book-scale app path.**
A test asserting that nothing reachable from the book-scale screens imports from `@/mocks` or
`msw`. Scope it to the real surface — `services/books.service.ts`, `services/upload.service.ts`,
`hooks/useBooks.ts`, `hooks/useChapters.ts`, `app/(dashboard)/books/**`,
`components/dashboard/books/**`, `components/dashboard/upload/**` — and **follow imports
transitively**, because a mock two hops away is still a mock in the render path.
Mutation-check it: add `import { lessonApi } from '@/mocks/api'` to `books.service.ts`, confirm
red, revert. A guard that cannot fail is not a guard (binding rule 7).

**AC2 — The dead mock-backed methods are resolved, not left ambiguous.**
`lessonService.getLesson` and `updateProgress` have **no callers**. Either delete them, or keep
them with a `D-nn` register ID and a trigger. Do not leave two mock-backed methods sitting in a
service on the book-scale path with only a comment — that is a documented limitation without an
ID, which binding rule 5 forbids. Note the comment already says they have "no real backend
endpoint yet", so this is a decision about dead code, not about mocking.

**AC3 — `NEXT_PUBLIC_API_URL` is correct, and the known trap is recorded.**
`lib/api.ts:4` defaults to `http://localhost:8000/api` — **including `/api`** — while
`ci.yml:188` sets it to `http://localhost:8000` **without**. Build-only today, so harmless, but
any runtime environment set that way 404s every call. W0 flagged it and did not fix it (it is a
deploy variable). Record it with an owner and a trigger, or fix it deliberately — not both
half-way.

**AC4 — A documented run recipe for Phase 7.**
Exactly how to point the web app at a live API and drive the whole flow: the env vars, the API
and worker commands, and the JWT/user setup. Phase 7 is a browser run by a person; it should not
require rediscovering how to start the stack. Put it where Phase 7 will look for it.

**AC5 — Say plainly what W4 cannot do.**
"The whole UI against the live API" is a **browser** run against a **completed generation**, and
generation costs money. That is Phase 7. This story makes the run trustworthy and cannot itself
perform it. W4 is therefore `🧪 Implemented` on merge and becomes Verified only in Phase 7 —
the same standing as Phases 5, 6 and 6.5.

**AC6 — Gates.** `pnpm lint`, `pnpm type-check`, `pnpm test`. Baseline **65 files / 739 tests**.

## Dev Notes

- Do not delete `src/mocks/`. `reports.service.ts` and `settings.service.ts` still depend on it,
  and those are outside book-scale. Removing it is a different story with a different owner.
- The type-only imports (`import type { … } from "@/mocks/data/…"` in `LearningPulse.tsx`, the
  settings tabs, `InteractivePlayer.tsx`) are compile-time coupling, not runtime mocking. They do
  not put mock *data* in the render path. Worth noting in the guard's comment so the next reader
  does not "fix" them under the banner of this story.
- `dashboard.service.ts`'s `learningPulse` fallback is **correct as written** — it is scoped to
  one field, wrapped, and degrades to `undefined` rather than to fake numbers. Do not widen the
  guard to fail on it.

## Dev Agent Record

### Completion Notes

- **AC1** — `apps/web/src/__tests__/guards/no-mocks-in-book-scale-path.test.ts`, 13 tests, walking
  the import graph **transitively** from 10 entry points. Mutation-checked: one
  `import { lessonApi } from '@/mocks/api'` in `books.service.ts` reddens **7** of them, which is
  what proves the walker follows edges rather than just reading the entry file. It carries a
  positive control (`reports.service.ts`, a legitimate mock importer outside book-scale, MUST be
  flagged) so a walker that resolved nothing could not report everything clean.
- Type-only imports are deliberately allowed and that is asserted, not merely commented —
  `LearningPulse.tsx`'s `import type … from "@/mocks/data/reports"` is erased at build time.
- **AC2** — `getLesson`/`updateProgress` **kept and registered as D56**, not deleted.
  `lesson.service.test.ts:70,76` deliberately pin the delegation with "no real backend yet", so
  deleting them would remove documented, tested state rather than dead weight.
- **AC3** — registered as **D57** rather than half-fixed. The client default includes `/api` and
  `ci.yml:188` omits it; harmless at build time, 404s every call at runtime.
- **AC4** — `docs/book-scale-phase-7-run-recipe.md`, including the three stale-process incidents
  that cost the most time in Phase 6 and the correct Windows `netstat` invocation (the one written
  during Phase 6 could never match).
- **AC5** — W4 is `🧪 Implemented`. "The whole UI against the live API" is a browser run against a
  completed generation, and generation costs money. That is Phase 7.
- **AC6** — `pnpm test` **66 files / 752 tests**, lint and type-check clean.

### File List

- `apps/web/src/__tests__/guards/no-mocks-in-book-scale-path.test.ts` (new)
- `docs/book-scale-phase-7-run-recipe.md` (new) · `docs/DEFECT-REGISTER.md` (D56, D57)
- `docs/book-scale-phase-tracker.md`
