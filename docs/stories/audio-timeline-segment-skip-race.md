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

`handleEnded` gains a single guard at its very top: if `status !== 'PLAYING'`, return immediately
— a no-op. Every OTHER call site of `handleEnded` already only calls it when `status` is (or has
just been set to, synchronously, in the same effect) `'PLAYING'`:

- The play/pause effect's `if (audio.ended) { handleEnded(); }` (`AudioTimeline.tsx:204`) runs
  inside the SAME effect's `if (status === 'PLAYING')` branch — `status` is already `'PLAYING'`
  by the time this line runs.
- The "no audio and no script" degrade path is already explicitly gated:
  `if (status === 'PLAYING') handleEnded();`.
- The virtual-clock (S2-33) interval's own `handleEnded()` call is already nested inside
  `if (state.status !== 'PLAYING') return;` at the top of the same tick handler.

So the guard changes nothing for any of those three call sites, and correctly turns the real
`<audio onEnded>` event into a no-op exactly when — and only when — `processTimeUpdate` has
already moved `status` off `'PLAYING'` for this same boundary. The legitimate cases (audio ends
before the boundary tick, or a genuine replay with `status` still `'PLAYING'`) are unaffected —
`handleEnded` still opens the quiz / advances exactly as before.

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
5. **AC5**: the existing legitimate-replay test
   (`'does NOT send segment_complete again when replaying an already-quizzed segment'`) and every
   other existing `AudioTimeline.component.test.tsx` test continues to pass unmodified — the fix
   must not change behavior for any already-covered path.
6. **AC6**: the play/pause effect's own `audio.ended -> handleEnded()` path
   (`AudioTimeline.tsx:204`, exercised by the existing
   `'calls handleEnded() (ending the lesson) instead of audio.play()...'` test) is unaffected by
   the new guard, since `status` is already `'PLAYING'` by the time that branch runs.

## Scale & Load

N/A — pure client-side state-machine ordering fix inside an already-running player session. No
new data, no new I/O, no new budget, limit, or per-request cost of any kind. The six questions do
not apply to a client-side event-ordering race in already-loaded lesson playback.

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
