# Story: `handleEnded` advances/ends the lesson without checking `status`, skipping a segment when `timeupdate` beats `ended` at a boundary

**Discovered:** 2026-09-26, direct report from a teammate (Dev 4 / AkshayDev2905) diagnosing a real
production T1 lesson (`fa9dae5b-33c3-4ff9-ba4b-7314b21c024f`): the player went `1 → 3 → 4 → 5 → 6 → 8`,
skipping segments 2 and 7 entirely (4.97 + 5.57 = 10.5 min of audio never played, with the
post-segment quiz/teach-back shown for the WRONG segment). Registered as **D197** in
`docs/DEFECT-REGISTER.md`.

## Root cause

`processTimeUpdate` (`AudioTimeline.tsx`) fires on the native `<audio>` element's `timeupdate`
event. At the very end of a segment's audio, the browser fires a final `timeupdate` with
`currentTime` equal to (or past) the segment's own `end_ms`, then fires `ended` shortly after.
`processTimeUpdate`'s boundary check (`if (ms >= segmentEnd && !quizFiredForSegment.has(...))`)
runs on that final `timeupdate` and calls `enterQuiz()` — setting `status` to `'QUIZ'` and adding
the segment to `quizFiredForSegment` — **before** `ended` ever fires.

`handleEnded` then runs (the native `ended` event) and reads `quizFiredForSegment` to decide what
to do:

```ts
if (segment && quizFiredForSegment.has(segment.segment_id)) {
  advanceSegment();          // "student sought back and replayed" branch
}
```

This branch was written for a genuine replay (student seeks back to an already-quizzed segment,
`status` is `'PLAYING'`, `ended` fires again, and advancing is correct). It has no `status` check,
so it fires identically for the race case: `status` is `'QUIZ'` (the quiz overlay just opened for
segment N), and `advanceSegment()` moves `currentSegmentIndex` to N+1 **while the quiz for N is
still open**. `QuizOverlay`/`TeachBackModal` read `currentSegmentIndex`, so they now show N+1's
quiz/teach-back content for a segment the student hasn't heard yet. `exitTeachBack()` then calls
`advanceSegment()` again on exit, landing on N+2 — segment N+1's audio never plays at all.

**The identical race exists on the last segment's `isLast` branch too** (not explicitly walked
through in the original report, but the same missing check): if `status` is already `'QUIZ'` when
`ended` fires on the last segment, the `else` branch calls `wsSendControl({type:
'lesson_complete'}); endLesson();` immediately — ending the lesson while the last segment's own
quiz/teach-back is still supposed to run.

It only happens when the browser's decoded audio duration is at least the package's own recorded
`end_ms` for that segment's final timestamp, so the final `timeupdate` can reach the boundary
before `ended` fires — package generation now sets a segment's last `end_ms` to the measured real
audio duration, so on many segments the two land exactly on the same tick, making the outcome a
race decided by browser/timing jitter, not a deterministic order.

**Confirmed by reading the code**, not yet by an executed test at diagnosis time — this story's
own RED phase (below) is the first executed reproduction.

## Fix

**Corrected in review** (Story Quality finding): an earlier draft of this section proposed a
single guard inside `handleEnded()` itself, on the reasoning that every OTHER call site already
only invokes it when `status` is `'PLAYING'`. That reasoning was wrong for the virtual-clock call
site specifically — see Completion notes below for what was actually tried, why it broke a real
test, and what shipped instead. The as-shipped design is a separate `handleAudioEnded()` wrapper
applied ONLY to the `<audio onEnded={...}>` prop, not a guard inside `handleEnded()`:

```ts
function handleAudioEnded() {
  if (usePlayerStore.getState().status !== 'PLAYING') return;
  handleEnded();
}
```

- The real `<audio>` element's native `ended` event (`<audio onEnded={handleAudioEnded}>`) is the
  ONLY call site where a genuine race against `processTimeUpdate` is possible, so it is the only
  one wrapped.
- The play/pause effect's `if (audio.ended) { handleEnded(); }` (`AudioTimeline.tsx`) still calls
  `handleEnded()` directly, unwrapped — it runs inside the SAME effect's
  `if (status === 'PLAYING')` branch, so `status` is already `'PLAYING'` by the time this line
  runs, and the wrapper would be a no-op there anyway.
- The "no audio and no script" degrade path still calls `handleEnded()` directly, already
  explicitly gated: `if (status === 'PLAYING') handleEnded();`.
- The virtual-clock (S2-33) interval still calls `handleEnded()` directly, unwrapped — it
  deliberately needs to run even when `processTimeUpdate`'s own slide-transition-pause side effect
  just moved `status` off `'PLAYING'` in the same tick (see Completion notes).

The legitimate cases (audio ends before the boundary tick, or a genuine replay with `status` still
`'PLAYING'`) are unaffected — `handleEnded` still opens the quiz / advances exactly as before.

## Acceptance Criteria

1. **AC1** (RED, reproduces the reported bug on unmodified code): a 3-segment lesson, `status`
   `'PLAYING'` on index 0. Fire `timeupdate` at `end_ms` (enters `QUIZ`, index stays 0). Fire
   `ended` on the same element. Assert index is **still 0** (not 1) and `status` is still
   `'QUIZ'` — on today's code this assertion fails (index becomes 1).
2. **AC2**: from the AC1 state, call `exitQuiz()` then `exitTeachBack()` in sequence. Assert the
   index becomes exactly 1 (segment 1 plays), never 2.
3. **AC3** (control case, must keep passing): fire `ended` BEFORE any `timeupdate` reaches
   `end_ms`. `status` is still `'PLAYING'` at that point. Assert `handleEnded` still opens the
   quiz (status becomes `'QUIZ'`, index stays put) — the non-race path must be unaffected.
4. **AC4**: the identical race on the **last** segment — `timeupdate` at `end_ms` enters `QUIZ`,
   then `ended` fires. Assert `endLesson`/`wsSendControl({type: 'lesson_complete'})` is NOT called
   while `status` is `'QUIZ'` (previously it fired immediately, ending the lesson before the last
   segment's own quiz/teach-back ran).
4b. **AC4b** (added in review — Story Quality finding: AC4 had no positive counterpart): from the
   AC4 state, exit the quiz/teach-back (`exitQuiz()` then `exitTeachBack()`). Assert
   `wsSendControl({type: 'lesson_complete'})` DOES fire and `status` becomes `'ENDED'` — an
   implementation that simply never fires `lesson_complete` on this path at all would satisfy AC4
   as originally worded while leaving the lesson unable to ever end; AC4b closes that gap.
5. **AC5**: the existing legitimate-replay test
   (`'does NOT send segment_complete again when replaying an already-quizzed segment'`) and every
   other existing `AudioTimeline.component.test.tsx` test continues to pass unmodified — the fix
   must not change behavior for any already-covered path.
6. **AC6**: the play/pause effect's own `audio.ended -> handleEnded()` path
   (`AudioTimeline.tsx`, exercised by the existing
   `'calls handleEnded() (ending the lesson) instead of audio.play()...'` test) is unaffected by
   the fix. **Corrected in review** (Acceptance Auditor finding: this rationale was stale relative
   to the shipped mechanism): this call site is unaffected not because a guard-inside-`handleEnded`
   happens to be a no-op there, but because, as shipped, this call site never goes through the new
   `handleAudioEnded()` wrapper at all — it still calls `handleEnded()` directly, and only the
   `<audio onEnded={...}>` JSX prop was changed.

## Scale & Load

N/A for questions 1-5 — pure client-side state-machine ordering fix inside an already-running
player session. No new data, no new I/O, no new budget, limit, page count, or per-request cost of
any kind; nothing here is inherited from an earlier design.

**Q6 (concurrent check-then-act) is the one topically closest to this story and is addressed
directly, not waved away** (Story Quality finding: a blanket "N/A" doesn't engage the question
that's actually adjacent): this story IS itself a check-then-act race, just at the browser-event
level rather than the server-request level Q6 usually means — `processTimeUpdate`'s boundary
check (the "check": has this segment been quizzed yet) racing the native `ended` event (the
"act": advance/end). The fix (`handleAudioEnded`'s `status` guard) closes that race for the one
call site where it's real. It does not need a lock or a database constraint because there is only
ever one `<audio>` element and one JS event loop per player session — no second "requester" can
interleave the way concurrent server requests can. N/A remains the answer for genuine
multi-request concurrency (there is none, client-side, single session); Q6 does not extend to
"is every call site's status assumption durable forever" — that is tracked separately (see Review
Findings).

## Out of scope

The narration pacing gap the same report separately named (60db synthesises at ~163 wpm against a
150 wpm budget, costing ~3.4 min of a lesson's target duration) is explicitly Dev 1's / backend's
own issue, independent of this player-side race, and is not touched here.

## Completion notes

Implemented as designed, with one deviation from the fix section above: the guard is **not**
inside `handleEnded()` itself. A first attempt added `if (status !== 'PLAYING') return;` directly
to `handleEnded()`'s own body and it broke a pre-existing, legitimate test — the S2-33 virtual
clock (no real `<audio>` element) calls `processTimeUpdate(nextMs)` and then `handleEnded()`
directly in the same tick, on purpose, to finalize an already-quizzed segment even when
`processTimeUpdate`'s own slide-transition-pause side effect just changed `status` away from
`'PLAYING'` in that same tick. A guard inside `handleEnded()` silently swallowed that legitimate
call too.

Fixed instead with a new wrapper, `handleAudioEnded()`, applied only to the one call site that is
actually racy — the `<audio onEnded={...}>` DOM prop:

```ts
function handleAudioEnded() {
  if (usePlayerStore.getState().status !== 'PLAYING') return;
  handleEnded();
}
```

`handleEnded()` itself is unchanged. The other three call sites (play/pause effect's
`audio.ended` check, the "no audio no script" degrade path, and the virtual clock) keep calling
`handleEnded()` directly and are unaffected, since each already only calls it when `status` is (or
was just synchronously confirmed) `'PLAYING'`, or deliberately needs to run regardless (the
virtual clock).

Both functions were relocated from their original position (just above the component's JSX
return) to immediately after `const hasScript = ...`, ahead of the play/pause `useEffect` — an
ESLint rule flagged `handleEnded` as "used before declaration" once a second reference
(`handleAudioEnded`) was added, even though JS function-declaration hoisting makes the original
ordering work correctly at runtime. Pure relocation, no behavior change: both functions only
reference `usePlayerStore.getState()`.

AC1–AC4 implemented as new tests in a `D197` describe block in
`AudioTimeline.component.test.tsx`, using a new `loadThreeSegmentLesson()` fixture helper. AC5/AC6
verified by running the full existing suite rather than adding new tests — no existing test
needed changes.

Verified: `AudioTimeline.component.test.tsx` 60/60, full player suite 458/458 (20 files), full web
suite 1307/1307 (96 files), `eslint` clean, `tsc --noEmit` clean.

**Post-review addendum:** the 8-layer review below (Review Findings) resulted in 5 more tests
added to the same describe block: AC4b (positive counterpart to AC4 — the lesson does eventually
end once the guarded quiz/teach-back is exited), two "guard holds for non-PLAYING statuses beyond
QUIZ" tests (PAUSED and TEACH_BACK, not just the QUIZ status the original 4 tests exercised), and
a zero-quiz-question segment test (`enterQuiz()`'s `TEACH_BACK`-direct branch, not previously
exercised against the guard at all). AC3 gained an additional `tutorState` store-read assertion
and AC4 gained a direct `endLesson` spy, both alongside their existing assertions rather than
replacing them. D198 was registered (and the story's own "Fix"/AC6 text corrected in place) rather
than shipping a further code change — see Review Findings for the reasoning.

Re-verified after the review round: `AudioTimeline.component.test.tsx` 64/64, full player suite
462/462 (20 files), full web suite 1311/1311 (96 files), `eslint` clean, `tsc --noEmit` clean.

## Review Findings

8-layer BMAD adversarial review (Blind Hunter, Edge Case Hunter, Acceptance Auditor, Scale & Load
Hunter, Story Quality, Test Coverage, AC Completeness, Process Integrity) run against PR #258.

- [x] [Review][Patch] (resolved from Decision) No mechanism enforces the invariant that only
  `handleAudioEnded` may be attached to `<audio onEnded>` — the entire fix's safety rests on a
  19-line code comment (`AudioTimeline.tsx:214-232`). Raised independently by Blind Hunter (thin
  wrapper, trivially reintroducible, no test asserts the DOM wiring itself; near-identical names
  with no lint/JSDoc signal) and by the mandatory Scale & Load Hunter (contract Q5: a future 5th
  call site added to `handleEnded()` without a `status === 'PLAYING'` check silently reintroduces
  D197's exact symptom with green CI). **Decision: add a regression test** that directly proves the
  guard fires by asserting `handleEnded`'s side effects (`advanceSegment`/`endLesson`/`enterQuiz`)
  never run when `status !== 'PLAYING'` at the `onEnded` call site — turning the comment's
  invariant into something CI actually checks. — applied: two new tests added ("guard holds for
  non-PLAYING statuses beyond QUIZ", covering `PAUSED` and `TEACH_BACK`), exercised through the
  real rendered component so a future revert of `onEnded={handleEnded}` (dropping the wrapper)
  would fail them, since `handleEnded`'s `advanceSegment`/`endLesson` branches have no internal
  status gate of their own (unlike `enterQuiz`, which does).
- [x] [Review][Defer] `handleAudioEnded`'s guard drops the native `ended` fact for ANY
  `status !== 'PLAYING'`, not just the `QUIZ`/`TEACH_BACK` race this story targets. Edge Case
  Hunter raised two concrete paths; both were investigated against the real store code
  (`player.machine.ts` `pauseForIntervention`/`cancelIntervention`, lines 275-300) before deciding:
  **(a) Intervention scenario — investigated, NOT reachable.** `preInterventionPauseReason` is
  only non-null when the student was already paused *before* the intervention, which means the
  `<audio>` element was already paused and cannot be mid-playback firing a genuine native `ended`
  event at that moment. In the realistic case (audio ends while genuinely `PLAYING`, intervention
  fires the same tick), `preInterventionPauseReason` is `null`, so `cancelIntervention()` calls
  `play()` — a real `PAUSED`→`PLAYING` transition that correctly re-triggers the play/pause
  effect's existing `audio.ended` recovery check. No fix needed; the claimed indefinite-stuck case
  does not occur. **(b) Replay scenario — real, but self-heals.** Replaying an already-quizzed
  segment can race `pauseForSlideTransition()`, dropping the `ended` fact while `status` is
  briefly `'PAUSED'`; recovery happens automatically via the existing 5s auto-resume timer
  (Story 2-57). User confirmed no further work needed since it self-heals. **Decision: defer,
  registered as D198** (see `docs/DEFECT-REGISTER.md`) rather than fixed — a code fix would mean
  touching `processTimeUpdate`'s slide-transition-pause logic, an area with its own dense history
  of past regressions, for a bounded, rare, self-recovering stall.
- [x] [Review][Patch] Missing test: a zero-quiz-question segment (`enterQuiz()`'s `TEACH_BACK`-
  direct branch, which the codebase's own comment calls "the normal case for several segments per
  lesson," not a corner case) is never exercised against the new guard.
  [`AudioTimeline.component.test.tsx`] — applied: new test added, verified green.
- [x] [Review][Patch] Story's "Fix" section and AC6's stated rationale are self-contradictory with
  the Completion notes: "Fix" claims the virtual-clock call site was already safe under an
  in-function-guard design; Completion notes admit that design was tried and broke a real test,
  and the shipped mechanism is different. The prose itself was never corrected.
  [`docs/stories/audio-timeline-segment-skip-race.md`] — applied: Fix/AC6 sections corrected in
  place to describe the actual shipped `handleAudioEnded` wrapper mechanism.
- [x] [Review][Patch] AC4 has no positive-path counterpart (unlike AC1/AC2): nothing asserts that
  after exiting the last segment's quiz/teach-back, `lesson_complete`/`endLesson()` actually DOES
  fire. An implementation that never fires it on this path at all would pass AC4 as worded.
  [`docs/stories/audio-timeline-segment-skip-race.md`, `AudioTimeline.component.test.tsx`] —
  applied: AC4b added to both the story and the test file, verified green.
- [x] [Review][Patch] Minor test-rigor nits: AC4's `sendControl` assertion is logically redundant
  with its adjacent `status` assertion (`endLesson` itself is never spied); AC3 could substitute/
  join its mock assertion with a real `tutorState` store read.
  [`AudioTimeline.component.test.tsx`] — applied: AC3 gained a `tutorState` assertion, AC4 gained
  a direct `endLesson` spy assertion, both additive.
- [x] [Review][Patch] Scale & Load "N/A" justification dismisses all six questions as a block
  without specifically engaging Q6 (concurrent check-then-act), which is topically the closest
  given this story is itself an event-ordering race.
  [`docs/stories/audio-timeline-segment-skip-race.md`] — applied: Scale & Load section rewritten
  to address Q6 directly.
- [x] [Review][Defer] `handleEnded`'s non-last branch has no unconditional fallback — if
  `l.segments[idx]` is falsy at a valid non-final index, neither branch executes and playback
  silently stalls. [`AudioTimeline.tsx` handleEnded, non-last branch] — deferred, pre-existing,
  unchanged by this diff (body only relocated).
- [x] [Review][Defer] `wsSendControl?.()` optional chaining silently drops
  `segment_complete`/`lesson_complete` if the WS handler is momentarily unset, diverging client/
  server state with no telemetry. [`AudioTimeline.tsx` handleEnded] — deferred, pre-existing.
- [x] [Review][Defer] No defense against the native `ended` event firing twice in immediate
  succession while `status` is still `'PLAYING'` — both fires pass the guard and double-execute.
  [`AudioTimeline.tsx` handleAudioEnded] — deferred, pre-existing, orthogonal to D197's ordering
  race.
- [x] [Review][Defer] Guard's soundness assumes `enterQuiz()`/`setTutorState()` remain
  synchronous; if either becomes async, the race reopens nondeterministically.
  [`apps/web/src/stores/player.machine.ts`] — deferred, speculative/forward-looking, pre-existing
  synchronous contract unchanged by this diff.
- [x] [Review][Defer] Stale/out-of-range `idx` after a mid-playback segment-count change could
  cause `isLast` to wrongly evaluate true and fire `endLesson()` prematurely.
  [`AudioTimeline.tsx` handleEnded] — deferred, pre-existing, unchanged by this diff.

Dismissed as noise / already addressed (5): no regression test for the seek-back replay flow
(AC5's pre-existing test already exercises this exact path through the real component, confirmed
passing); inline function identity churn on `onEnded` (reviewer's own verdict: not a bug); Defect
Register D197 wording flagged as unverifiable by a reviewer whose diff excluded it — independently
confirmed correct, already describes the shipped wrapper mechanism, not an in-function guard;
numeric test-run claims flagged as unverifiable from diff alone — inherent review-scope
limitation, confirmed green via the gating CI bucket separately; AC5/AC6 coverage confirmed by
reading existing tests rather than an execution log — informational, not a defect.

Also noted, not part of the review-gate tally: Process Integrity flagged the Sprint Task Branch
Rule's naming convention (`sprint{N}/...`) as ambiguous for ad-hoc, non-tracker bug reports like
this one — a process/governance question for the team, not a violation of this PR.
