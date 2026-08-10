# Dev 2 — Lesson Delivery handoff

**Sprint goal:** one student, one complete lesson, generated from one real book.
**Your phases:** **L3** (with Dev 1) · **L6** (attention capture) · support on L4
**Master doc:** `docs/LESSON-DELIVERY-TRACKER.md`

> **Naming, once.** This sprint is often called "video generation". **Your player *is* the video
> lecture** — synchronised audio + slides that happens to also be interactive. A compiled MP4 is
> re-watch-only and out of scope (`docs/decisionupdate.md` §7b). Nothing you build gets replaced by
> video; the tracker §0 explains why it structurally cannot be.

---

## Your one-line status

**The player is in better shape than the trackers suggest** — and it has never once rendered a real
generated lesson. Everything below is verification and one net-new build (MediaPipe).

---

## What is already right — do not rebuild it

Verified in code, so you can trust these:

| Thing | Where | Note |
|---|---|---|
| Player fetches a **real** package | `PlayerLoader.tsx:68` → `useLesson.ts:37-50` → `lesson.service.ts:8-9` → `GET content/lessons/{id}` | Not mocked. Backend signs every URL on read |
| Per-segment MP3 playback | `AudioTimeline.tsx:404-423` — one `<audio>`, keyed by segment, remounted per segment | N files sequenced client-side, **not** one stitched file |
| Quiz fires at every segment boundary | `AudioTimeline.tsx:54-59`, `enterQuiz` at `:58` | Once per segment per session (`player.machine.ts:238-250`) |
| Teach-back after each quiz | `QuizOverlay.tsx:79-81` → `player.machine.ts:252-256` → `Player.tsx:216-221` | Skippable, no timer, never gates progress — all three match CLAUDE.md |
| **The 0:00-quiz bug is fixed** | Virtual clock at `AudioTimeline.tsx:127-191` | The `dev2-narration-playback-handoff.md` ask is done |
| Books/chapters UI | Track W W0–W4 | Built, MSW-tested, **never browser-verified** |

---

## Deviations you own

| # | Intended | Actual | Where |
|---|---|---|---|
| **1** | Slides advance with the narration | Timing comes from a **word-count × WPM estimate**, not the real MP3. Dev 1 is fixing the source (L2); **you must measure the residual drift** | `graph.py:3746-3792`; consumed at `AudioTimeline.tsx:43` |
| **2** | A student can pause and come back | Signed URLs are issued once with **no auto-refresh**. Only a manual Retry re-signs. `/api/media/signed-url` exists and **you have zero callers** | `modules/content/router.py:139`, `:632`/`:639` |
| **3** | Attention captured via MediaPipe Face Landmarker WASM | **Not one line exists.** No `@mediapipe/*` dependency; zero hits for `FaceLandmarker`, `getUserMedia`, `navigator.mediaDevices` | only trace: comment at `PlayerLoader.tsx:8` |
| **4** | W phases verified | All five are `🧪 Implemented`, none Verified — every W exit criterion is browser-driven and no browser run has happened | `docs/book-scale-phase-tracker.md` Track W |

---

## L3 — verify the player against a real lesson

Dev 1 hands you a real `lesson_id` the moment L1 passes. Then:

1. Open it in a browser against the live API. **Audio must be audible speech** — a valid-but-silent
   MP3 passes every automated check we have.
2. **Measure the audio/slide drift** and state it in seconds. This is deviation 1's real number and
   nobody has it.
3. Confirm the text-only degrade path renders when `image_url` is null.
4. Confirm signed URLs resolve, then deliberately wait past the expiry window and record what the
   student sees (deviation 2).

**Exit:** a person watches a full lesson start to finish and the audio matches the slides.

---

## L6 — attention capture, from zero

**Non-negotiable constraints (CLAUDE.md §18):**
- **Raw webcam video NEVER leaves the browser.** Only five derived numbers.
- **Explicit consent before any capture.** The backend is ready — Dev 3 shipped the write endpoint
  on 2026-08-05 (Story 3-32, closing D29), and the `user_consents` table plus RLS is applied. **You
  need the modal and the call.**

**The wire shape you must produce** (`packages/shared/types/ws.ts:90-100`):

```ts
{ session_id, quiz_accuracy: number|null, teachback_score: number|null,
  behavioral_score: number, head_pose_score: number, blink_rate: number }
```

**Three traps, in order of how much time they will cost you:**

1. **`ws.ts` specifies no range at all.** Every field is bare `number`. The 0–1 expectation lives
   only in `tutor/service.py` docstrings and one example in `docs/ws-message-contract.md:52`.
   **Agree the scale with Dev 3 and Dev 4 in writing before you emit a single frame** — this is
   SYNC-B in the tracker.
2. **`behavioral_score` has no definition anywhere.** No producer, no spec, in either app. Dev 4
   owns defining it; you cannot invent it unilaterally.
3. **There is no partial-signal path.** `_parse_signal` (`tutor/service.py:54-100`) hard-requires
   all three of `behavioral_score`, `head_pose_score`, `blink_rate` and raises otherwise. So you
   **cannot ship head-pose first and blink later** — the server rejects the frame. If you want
   incremental delivery, ask Dev 4 to relax that first.

---

## What you owe others

| To | What |
|---|---|
| **Dev 4** | Attention frames at an agreed scale, and confirmation the WS client handles `tutor_intervene` |
| **Dev 1** | The measured drift number from L3, and whether signed-URL expiry strands a real student |
| **Dev 3** | Confirmation the quiz/teach-back UI renders a **real** package's payloads |

## What you're waiting on

- **Dev 1** — a real lesson id (blocked on OpenAI credits)
- **Dev 4** — the `behavioral_score` definition and a decision on partial signals
- **Dev 3** — agreement on the 0–1 scale for quiz/teachback fields

---

## Scale & Load (contract-mandated)

- **Unit of work:** one lesson = N segments; one attention frame per capture tick.
- **Fixed budget vs variable input:** capture frequency × session length is unbounded — state the
  tick rate and what happens on a 90-minute session.
- **Scope:** per session, per browser tab. Say what happens with two tabs open on one lesson.
- **Unbounded:** the attention stream has no server-side rate limit today — agree one with Dev 4.
- **Inherited caps:** `MAX_POLL_ATTEMPTS = 240` × 8s in the upload flow was sized for lesson
  polling; re-derive it for book ingest.
- **Concurrency:** two tabs on one session both send frames — decide whether that is valid.
