# Dev 2 handoff — 2026-07-29

**From:** Dev 1 (infra / content pipeline / providers)
**To:** Dev 2 (Next.js, custom player, MediaPipe, quiz/teach-back UI, dashboard, WS client)

Supersedes nothing — `docs/dev2-narration-playback-handoff.md` (2026-07-28) is still live and
its open items are restated here so you have one list.

---

## TL;DR

1. **A one-line change in `player.machine.ts` unblocks the demo.** Quiz and teach-back 404 for
   every student right now, and the client-generated `sessionId` is why.
2. **The whole web CI job has never run — on any commit, ever. My bug.** I fixed it and ran
   your suite: **506 passing, 0 failing.** No action needed; this is the good news item.
3. **`next build` fails — the app has never produced a production build.** Found the moment CI
   could reach that step. One Suspense boundary on `/signin`. Needs one decision from you.
4. Three player items from last week's handoff are still open; the signed-URL one got *less*
   urgent but not fixed.

---

## 1. THE BLOCKER — the invented `sessionId` (register ID: D18)

### What happens

A student answers a quiz question and gets **404**. Every time. The demo cannot complete.

### Why it's yours (partly)

`apps/web/src/stores/player.machine.ts:142`:

```ts
sessionId: crypto.randomUUID(),
```

That UUID has never existed in the database. `app/modules/assessment/service.py:175` looks the
session up, doesn't find it, and correctly 404s.

**To be clear: the backend half is the bigger failure.** Nothing anywhere creates a `sessions`
row — all 7 references in `apps/api` are reads, and I confirmed `apps/web` never inserts one
either. So even a "correct" client id would have 404'd. Both halves need fixing; I'm doing the
backend.

### Why no test caught it

Worth reading, because it isn't carelessness on anyone's part:

> **Your tests mock the POST. Dev 3's tests seed the session row in fixtures. Both suites are
> green. The product is broken.**

Each side tested its half against its own assumption, and nothing ever reconciled them. The
same pattern sits behind 12 of 17 defects we analysed this week (RC-1 in
`docs/DEFECT-REGISTER.md`). It traces to CLAUDE.md's Week-1 rule "each dev mocks the other's
interface" — right at the time, never given an expiry.

### What you'll need to change

Once the backend endpoint lands (Story 2-35), roughly:

```ts
// before
sessionId: crypto.randomUUID(),

// after — the server mints it; the id is DB-generated
const { session_id } = await api.post('/api/assessment/sessions', { lesson_id: lessonId })
```

The endpoint takes `{lesson_id}`, derives `user_id` from your JWT, and returns the
database-generated `session_id`. **Call it once when the lesson starts**, not per segment —
each call creates a new attempt row, which is intentional (re-learning the same lesson must
produce a new session for CES history).

I'll ping you the moment the endpoint is merged so you're not building against a moving target.

### This also closes the identity gap I raised last week

Item 3 of the previous handoff: *"`session_id` is client-generated with no backend round-trip
… no collision/replay protection, and no durable link to Dev 3's session-report data."*

Server-minting closes all three. **The joint Dev 2 + Dev 4 decision I asked for is now
resolved by the schema itself** — `session_id uuid PRIMARY KEY DEFAULT gen_random_uuid()` means
server-minting was always the intended design. No meeting needed.

---

## 2. The web CI job has never executed. Not once. That one's mine.

**Correction to what I told you earlier today.** I said CI was "about to run `pnpm test` for
the first time" and gave you a heads-up to brace for red. Both halves were wrong, and the
truth is worse and then better.

### It's not that the test step was missing. The job never started.

```yaml
- uses: actions/setup-node@v4
  with:
    cache-dependency-path: apps/web/pnpm-lock.yaml   # ← this file does not exist
```

This is a pnpm **workspace** — `pnpm-workspace.yaml` lists `apps/web`, so there is exactly one
lockfile and it lives at the **repo root**. The path never resolved, `setup-node` failed with
*"Some specified paths were not resolved"*, and the job died right there.

**So `pnpm lint`, `pnpm type-check` and `pnpm build` have never run on any commit either.** Not
just the missing test step — the entire job, since it was written.

Second, independent breakage underneath it: **`pnpm type-check` did not exist as a script** in
`apps/web/package.json` at all. The step would have failed even after the path was fixed. Both
are infra, both are mine, both are fixed in PR #110.

### Then I ran your suite, and it's green

Since I'd created the problem, I wasn't going to hand you a deadline sight-unseen:

| | Result |
|---|---|
| `pnpm test` | **53 files, 506 passed, 0 failed** (68s) |
| `pnpm lint` | 0 errors, 32 warnings (exit 0) |
| `tsc --noEmit` | clean |

So **all three web steps gate from day one** — no `continue-on-error`, no grace period, nothing
for you to triage. Your suite has been green this whole time; the pipeline just had no way to
say so.

One small thing in your file: I added `"type-check": "tsc --noEmit"` to
`apps/web/package.json`. One line, and CI already assumed it existed. Shout if you'd rather it
were configured differently.

Also worth knowing: the story files claim "488 tests" in 41 places. It's 506. Nobody was
lying — no machine had ever counted.

---

## 3. 🚨 …and then it reached `next build`, which fails. **The app has never built.**

I'd have preferred to hand you only good news. But once the job could actually run, it got one
step further and hit this — and it's the most serious thing in this document.

```
⨯ useSearchParams() should be wrapped in a suspense boundary at page "/signin".
Error occurred prerendering page "/signin".
Export encountered an error on /(auth)/signin/page: /signin, exiting the build.
⨯ Next.js build worker exited with code: 1
```

**`pnpm build` fails. It has never succeeded on any commit.** I reproduced it locally with CI's
exact env vars, so this isn't a CI-environment artefact:

```bash
NEXT_PUBLIC_SUPABASE_URL=http://localhost:54321 \
NEXT_PUBLIC_SUPABASE_ANON_KEY=test \
NEXT_PUBLIC_API_URL=http://localhost:8000/api \
pnpm build
```

> **CORRECTION 2026-07-30 (register D31).** This block originally read
> `NEXT_PUBLIC_API_URL=http://localhost:8000`, copied from `ci.yml:126`. **That value is wrong
> and it 404s every API call** — every router is mounted under `/api` (`main.py:166-172`) with
> no unprefixed alias, and axios joins a prefix-less base with a relative path to give
> `/content/lessons`. `apps/web/src/lib/api.ts:4` falls back to the correct
> `http://localhost:8000/api`, so a dev who set nothing worked and a dev who followed **this
> document** did not. `.env.example:10` and `ci.yml:126` carry the same bug. Entirely Dev 1's.
> See `docs/reports/frontend-wiring-audit-2026-07-30.md` §3.

### Why nobody caught it

Everything upstream is genuinely fine — `✓ Compiled successfully`, TypeScript clean, 506 tests
pass. This only fails at **static prerender**, which `next dev` never performs and `vitest`
never performs. It is invisible to every workflow any of us actually uses day to day, and the
one job that would have caught it had been dead since it was written. My fault, and it means
this has been sitting there unseen.

**Consequence: `apps/web` has never produced a production build, so it has never been
deployable.** That's very likely why the Deploy workflow fails alongside CI.

### The cause

`useSearchParams()` opts a component out of static rendering. Next needs a Suspense boundary to
know what to prerender in its place.

- `src/components/auth/SignInForm.tsx:15` calls `useSearchParams()`
- `src/app/(auth)/signin/page.tsx:104` renders `<SignInForm />` with no boundary
- It's the only `useSearchParams()` in the codebase, so `/signin` is the only affected route

### The fix — yours, and I've deliberately not made it

```tsx
import { Suspense } from "react";
...
<Suspense fallback={/* your call */}>
    <SignInForm />
</Suspense>
```

Mechanically trivial. I stopped because the `fallback` is a **visible UX decision** on your
sign-in page — a skeleton matching the form, a spinner, or `null`. Guessing at that and pushing
it to your file is exactly the kind of thing I'd rather ask about, especially having told you
above that I'm not touching your source.

**Say the word and I'll do it with whatever fallback you name — it's a 5-minute change and it
unblocks deployment.** Registered as **D27**.

### 4a. Virtual playback clock — **this is the one that kills the 0:00 symptom**

Unchanged and still the highest-value player item. The backend half shipped (the package now
carries the real narration script even when audio is missing), but **you will see no
difference until this lands** — which is exactly what I warned about last week, restated so
it isn't read as "the fix didn't work".

Three-way branch instead of today's two:

| Condition | Behaviour |
|---|---|
| `hasAudio` | today's real `<audio>` path, unchanged |
| `!hasAudio && script.trim()` | **new** — virtual clock |
| `!hasAudio && !script` | today's immediate-advance path |

- `setInterval(100)` accumulator, advancing **only** while `status === 'PLAYING'`, calling
  `processTimeUpdate`.
- **It must never call `handleEnded()`.** `processTimeUpdate`'s own boundary check already
  fires the quiz; a second call hits `quizFiredForSegment` and `advanceSegment()`s past an
  open quiz.
- `setAudioDuration(timestamps.at(-1).end_ms)` so the scrubber shows a real duration.
- Your S2-26 never-stuck test uses a full 60-word script fixture and asserts a synchronous
  `'QUIZ'` — it will fail against the new branch. Re-point it at an empty-script fixture.

### 4b. `retryAudio()` can't recover from an expired URL

`AudioTimeline.tsx:199` keys the `<audio>` on `${segment.segment_id}-${audioRetryCount}`, so a
retry re-mounts with **the same `src`**. Fine for a transient network blip; useless for a 403.

**Status change:** I raised the embedded-media signed-URL expiry from 1h to **8h**, so the
window shrank a lot — but there is still **no re-sign path anywhere**, so the cliff moved
rather than disappeared. A student who leaves a tab open past 8 hours loses all audio and
images with only a page reload to recover.

Compounding it, `useLesson.ts:29` stops polling once status is `ready` (`refreshInterval → 0`,
`revalidateOnFocus: false`), so the client never re-fetches. That `false` is **correct** for
its own reason — your comment explains a refocus would reset the player state machine — so
please don't just flip it. The fix is either re-fetching the lesson on a media error, or
calling the (currently dormant, zero-caller) `GET /api/media/signed-url` to re-sign one asset.

### 4c. Browser `SpeechSynthesis` — still zero references in `apps/web/src`

Enhancement, not a blocker. Layer it on the working clock so the clock stays the source of
truth for timing and audio can't desync from slides.

---

## 5. Context you may want

`docs/DEFECT-REGISTER.md` is new — the authoritative record of known defects and decisions.
Two entries touch the player:

- **Learner Mode was broken until this morning.** Every T1 and T3 lesson silently shipped T2
  content because the tier never reached the generation nodes. Fixed. If you were seeing
  suspiciously uniform quiz counts across tiers, that's why.
- **Cost baselines are ~4× inflated** by a duplication bug now fixed. Any lesson-cost figure
  you've been shown is unreliable until re-measured.

---

## What I need from you

**One decision, and it's small:** the Suspense `fallback` for `/signin` (§3). Name it and I'll
push the fix, or take it yourself — either way it unblocks deployment.

The `sessionId` change (§1) depends on my endpoint landing first; I'll ping you.

Two things worth knowing my plan on, so we don't collide:
- The **only** thing I've touched in `apps/web` is one added line in `package.json`
  (`"type-check": "tsc --noEmit"`, §2). No source files, and I don't intend to.
- CI now runs your lint, type-check, build **and** tests — all gating, all currently green.

Happy to pair on the playback clock — I have the timestamp semantics fresh from the pipeline
side, and it's the item standing between us and a lesson that visibly works end to end.
