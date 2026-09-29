# Story: Default tutor playback speed should be a real 0.8× while the UI keeps showing "1×"

**Requested:** 2026-09-28, direct product feedback: the tutor's narration at the current default
speed (`playbackRate = 1.0`, applied directly as the real `<audio>`/SpeechSynthesis rate) sounds
too fast. Product wants the DEFAULT to actually play at a real rate of 0.8, while the speed control
in `PlayerControls.tsx` keeps showing "1×" for that default — so returning students don't see an
unfamiliar "0.8×" label and wonder if something is broken, and the button still reads like a
normal, unmodified "1×" default.

Clarified with the user before implementation: the other four speed options
(`0.75×`, `1.25×`, `1.5×`, `2×`) are NOT left at their literal real rates. All five buttons are
scaled by the same 0.8 factor, so the relative step between buttons is unchanged from today — only
the whole scale shifts down. See the design table under "Fix" below.

## Root cause / current behavior

`player.machine.ts`'s `playbackRate` field is used directly, everywhere, as the REAL rate:
- `AudioTimeline.tsx`'s "keep audio playback rate in sync" effect: `audio.playbackRate = playbackRate`.
- `handleLoadedMetadata`: re-applies `playbackRate` after a src change resets it.
- The S2-33 virtual clock: `nextMs = audioPositionMs + elapsedMs * playbackRate`.
- The SpeechSynthesis fallback: `utterance.rate = playbackRate` (set once at speak time, S2-34 AC-9).

`PlayerControls.tsx`'s `SPEED_OPTIONS = [0.75, 1.0, 1.25, 1.5, 2.0]` are literal real rates, and the
button's label is the raw value itself (`playbackRate === 1.0 ? '1×' : \`${playbackRate}×\``) — there
is no separate "displayed label" vs. "real rate" distinction anywhere today. `playbackRate`
defaults to `1.0` in the store's initial state and is reset to `1.0` on every `loadLesson()`. It is
NOT persisted (`saveProgress`'s `StoredProgress` payload has no `playbackRate` field), so every
fresh session or lesson load always starts from the store's default — no migration concern for
returning students.

## Fix

Introduce a fixed display-scale factor and store each speed option as an explicit
`{ rate, label }` pair (not a derived division, to avoid floating-point label artifacts like
`1.4999999999999998×`):

| Label (unchanged from today) | Real rate (today) | Real rate (new) |
|---|---|---|
| 0.75× | 0.75 | 0.60 |
| **1×** (default) | 1.00 | **0.80** |
| 1.25× | 1.25 | 1.00 |
| 1.5× | 1.50 | 1.20 |
| 2× | 2.00 | 1.60 |

- `player.machine.ts`: change the default `playbackRate` from `1.0` to `0.8` (both the initial
  state and `loadLesson()`'s reset), exported as a named constant so the two sites can't drift.
- `PlayerControls.tsx`: replace the literal `SPEED_OPTIONS` number array with an array of
  `{ rate, label }` pairs carrying the real rate and its (unchanged) display label. `cycleSpeed()`
  looks up the option by `rate` instead of assuming the raw value doubles as its own label.
  Rendering looks up the current option's `label` rather than formatting `playbackRate` directly.

No other call site needs to change: everything downstream of `playbackRate` (audio element,
virtual clock, SpeechSynthesis) already treats it as a real rate multiplier and works correctly at
any value.

## Acceptance Criteria

1. **AC1**: a freshly loaded lesson has `playbackRate === 0.8` in the store (both on the store's
   initial state and after `loadLesson()`).
2. **AC2**: `PlayerControls` renders `"1×"` as the speed button's label when `playbackRate === 0.8`
   (the new default) — not `"0.8×"`.
3. **AC3**: cycling speed from the default steps through the real rates `0.8 → 1.0 → 1.2 → 1.6 →
   0.6 → 0.8 → …` (wrapping), with displayed labels `1× → 1.25× → 1.5× → 2× → 0.75× → 1× → …` at
   each step — i.e. the SAME label sequence as today, just mapped to different real rates.
4. **AC4**: the real `<audio>` element's `playbackRate` property is actually set to `0.8` (not
   `1.0`) when a lesson loads and no speed change has been made yet.
5. **AC5**: the SpeechSynthesis fallback path's `utterance.rate` is `0.8` under the same default
   conditions (script-only segment, no speed change made).
6. **AC6**: existing tests that explicitly set `playbackRate` to a specific value (e.g. `2.0`,
   `1.5`) to test unrelated behavior (virtual clock speed-up, SpeechSynthesis rate capture) continue
   to pass unmodified — this story changes the DEFAULT only, not the meaning of an explicitly-set
   `playbackRate` value.

## Scale & Load

N/A — a client-side constant/lookup-table change affecting one number's default value and how five
already-fixed options are displayed. No new data, no new I/O, no per-request cost, no query, no
budget or limit of any kind. Nothing here scales with lesson size, user count, or instance count.

## Out of scope

No change to the TTS provider chain, narration WPM budget, or the separate backend narration-pacing
gap (Dev 1's ~163 wpm vs. 150 wpm budget concern, noted in D197's story as explicitly out of scope
there too) — this story only changes the player's own real-time playback multiplier and its display
mapping, a purely client-side lever independent of how the narration audio was generated.

## Completion notes

Implemented exactly as designed:
- `player.machine.ts`: added `export const DEFAULT_PLAYBACK_RATE = 0.8`, replacing the two literal
  `1.0` defaults (initial state and `loadLesson()`'s reset).
- `PlayerControls.tsx`: `SPEED_OPTIONS` is now `{ rate, label }[]`, with each `rate` computed as
  `originalLiteral * DEFAULT_PLAYBACK_RATE` and each `label` kept as the original literal string —
  the label is never derived from the rate at render time, avoiding floating-point display
  artifacts. `cycleSpeed()` looks up by `rate` (`findIndex`) instead of the old `indexOf` on a raw
  number array; the same `(idx + 1) % length` wrap-around and "not found -> first option" fallback
  are unchanged.

**Review finding during verification (not part of the original design, found while running the
full suite):** two pre-existing S2-33 virtual-clock tests
(`'ticks processTimeUpdate every 100ms while PLAYING, eventually firing the quiz at the real
segment boundary'` and `'never calls handleEnded-driven advanceSegment/endLesson from the clock
itself...'`) computed their expected `audioPositionMs` from wall-clock time advanced via
`vi.advanceTimersByTime`, implicitly assuming a 1:1 real-time rate — they never set `playbackRate`
explicitly, relying on the (previous) default of `1.0`. Changing the default to `0.8` broke their
arithmetic (93000ms of wall-clock time now only advances virtual position by 74400ms, short of the
92000ms segment boundary). Fixed by pinning `playbackRate: 1.0` explicitly in both tests' `setState`
calls, since their actual intent (quiz-firing/boundary-detection logic) is independent of playback
speed — matching this story's own AC6 intent, just extended to two tests that turned out to depend
on the default implicitly rather than "explicitly set a specific value," which is how AC6 was
originally worded. Two other tests in the same describe block were checked and found NOT to need
this (one only asserts `> 0` / exact-freeze, not a boundary crossing; one already sets
`audioPositionMs` directly to the boundary itself, so any positive rate still satisfies `>=`).

Verified: `player.machine.test.ts` + full `components/player/` suite 564/564, full web suite
1317/1317 (96 files), `eslint` clean, `tsc --noEmit` clean.
