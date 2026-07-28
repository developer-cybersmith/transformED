# Dev 2 Handoff: playback-clock work needed to close Bug 2

**From:** Dev 1 (content pipeline)
**To:** Dev 2 (player / frontend)
**Date:** 2026-07-28
**Re:** your bug report of 2026-07-27, items 1 and 2

---

## TL;DR

**Bug 1 (quiz duplication) is fixed** — PR #100. Root cause was not what either of us thought; details below, worth two minutes because your proposed fix would have made things worse.

**Bug 2 (TTS fallback) is half mine, half yours.** I'm fixing the backend half now (Story 2-31). **It will not change what you see** — the 0:00 quiz-fires-instantly symptom is in `AudioTimeline.tsx` and needs a virtual playback clock. If you test my fix expecting the symptom gone, it will look like it didn't work.

Everything below was re-verified against `main` today, not carried over from an older audit.

---

## 1. Bug 1 — fixed, but your diagnosis and mine were both wrong

You attributed the 16× to ~16 ARQ retries. It can't be: ARQ is `max_tries=3`.

The real cause: six `PipelineState` channels are `operator.add` **concatenating reducers**. LangGraph *merges* a node's return into state, and for a reducer channel "merge" means **append** — so `return {**state, ...}` re-appends everything already accumulated. Four nodes run after the Phase-1 fan-in and each spread state: **2⁴ = 16×, in a single clean run, no retry involved.**

That's also why you saw the *same* 16× on both a 2-question and a 3-question segment — the multiplier comes from graph shape, not retry count. Your observation was the clue that cracked it.

**Your proposed fix would have caused a worse bug.** "Skip re-dispatching Phase 1 if `lesson_jobs.last_node` shows it completed" — the accumulated channels live only in the process-local `MemorySaver`. After a worker restart, or a different worker picking up the retry, `lesson_planner` and `package_builder` would run with **empty** `segment_summaries`/`quiz_questions` and ship a structurally valid, **content-empty** lesson. Silent corruption instead of visible duplication. Measured: re-dispatching Phase 1 costs **zero** extra LLM calls (93 → 93) because the Supabase checkpoints absorb it — so skipping buys nothing.

Not a criticism — the observation was right and the report was excellent. Flagging only in case it's still on your list.

---

## 2. Bug 2 — what I'm fixing, and why you won't see a difference

**My half (Story 2-31, in progress):** `_fallback_narration()` returns `{"script": "", ...}`, discarding narration text that is sitting right there in `state["narration_scripts"]`. Only the *audio* is missing in that degrade path — the script isn't. Fixing it so the package carries the real text.

**Why the symptom persists** — traced through your code today:

```
audio_url == ""  →  AudioTimeline.tsx:76  hasAudio = false
                 →  AudioTimeline.tsx:91  the !hasAudio branch fires handleEnded() immediately
                 →  'timeupdate' never fires, so narration.timestamps are never read
                 →  quiz fires at 0:00
```

Your `!hasAudio` branch is *correct* as written — its comment says it exactly: *"Nothing will ever load, so 'ended'/'timeupdate' can never fire for this segment — drive the same advance/quiz logic."* Without it a segment would hang forever. It just means a non-empty script alone changes nothing on screen.

### What's needed (your side)

**Story 2a — virtual playback clock (S/M, this is the one that kills the symptom)**

Three-way branch instead of the current two:

| Condition | Behaviour |
|---|---|
| `hasAudio` | today's real `<audio>` path, unchanged |
| `!hasAudio && script.trim()` | **new** — virtual clock |
| `!hasAudio && !script` | today's immediate-advance path |

For the virtual clock:
- `setInterval(100)` accumulator, advancing **only** while `status === 'PLAYING'`, calling `processTimeUpdate`.
- **It must never call `handleEnded()`.** `processTimeUpdate`'s own boundary check already fires the quiz; a second call hits the `quizFiredForSegment` branch and `advanceSegment()`s past an open quiz.
- `setAudioDuration(timestamps.at(-1).end_ms)` so the scrubber shows a real duration.
- Absorb `seekRequestMs`, or explicitly declare seek disabled in this mode.
- **Heads-up:** your S2-26 never-stuck test uses a full 60-word script fixture and asserts a synchronous `'QUIZ'`. It will fail against the new branch — re-point it at an empty-script fixture.

**Story 2b — browser SpeechSynthesis (M, enhancement)**

Confirmed today: **zero** `speechSynthesis` references anywhere in `apps/web/src`. Layer this on the working clock; the clock stays the source of truth for timing so audio and slides can't desync.

---

## 3. Two other things that are yours

**`retryAudio()` remounts an expired URL rather than re-fetching.** `AudioTimeline.tsx:198` keys the `<audio>` on `${segment.segment_id}-${audioRetryCount}`, so a retry re-mounts the element with the *same* `src`. If the failure was an expired signed URL, every retry fails identically.

Relevant because signed URLs currently expire after **1 hour** and nothing refreshes them — a student who leaves a lesson open past that loses audio and images with no recovery. I'm raising the expiry in Story 2-31 (AC-5), which shrinks the window but doesn't remove it. A real fix re-fetches the lesson (or re-signs the segment) on a media error.

**`session_id` is client-generated with no backend round-trip.** `player.machine.ts:142` does `crypto.randomUUID()`; the WS endpoint accepts whatever it's handed, with no server-side registration. No collision/replay protection, and no durable link to Dev 3's session-report data. **Joint decision with Dev 4** — either the backend mints it via a "start session" call before the WS connects, or the client UUID gets registered over REST first. Either works; it just needs one decision rather than two independent assumptions.

Now more pressing than it was: `useLessonSocket` **is** mounted (`Player.tsx:49`), so this ID reaches the backend on every real session.

---

## 4. Credit where due — and one correction to my own audit

My earlier wiring handoff (`docs/dev2-sprint2-wiring-handoff.md`) was written against `main` while your work sat on `sprint2-master`. Your correction was right: 5 of its 6 items were already done. All of it has since merged and I've re-verified it on `main` — player wired to the real endpoint, dashboard/library wired, `useLessonSocket` mounted, quiz feedback fields aligned, `ReassessmentPrompt` shipped. Only the `session_id` item was still open, and you'd already flagged that yourself.

Apologies for the noise — auditing a branch you hadn't PR'd yet was my error, not yours.

---

## Summary

| Item | Owner | Status |
|---|---|---|
| Bug 1 — quiz duplication | Dev 1 | ✅ PR #100 |
| Bug 2 — package carries real script | Dev 1 | 🔵 Story 2-31 |
| Bug 2 — virtual playback clock (**fixes the symptom**) | **Dev 2** | ⬜ needed |
| Browser SpeechSynthesis | **Dev 2** | ⬜ enhancement |
| `retryAudio()` re-fetch on expiry | **Dev 2** | ⬜ needed |
| Signed-URL expiry window | Dev 1 | 🔵 Story 2-31 AC-5 |
| `session_id` identity | **Dev 2 + Dev 4** | ⬜ decision |
| `GET /lessons` + `subject`/`estimated_duration_mins` | Dev 1 | 🔵 Story 2-31 AC-4 |

Happy to pair on the clock — I have the timestamp semantics fresh from the pipeline side.
