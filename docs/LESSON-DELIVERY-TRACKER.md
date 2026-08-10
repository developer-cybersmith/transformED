# Lesson Delivery Tracker — from an uploaded book to a student finishing a lesson

**Owner:** Dev 1 (coordinating) · **Created:** 2026-08-05 · **Last updated:** 2026-08-05 (audited and corrected same day)
**Sole purpose:** get one real student through one complete lesson generated from one real book.
Nothing in this document is about anything else.

**Companion docs:** `docs/book-scale-phase-tracker.md` (how a book becomes chapters — done) ·
`docs/SCALE-CONTRACT.md` (binding on every task here) · `docs/DEFECT-REGISTER.md` ·
`docs/book-scale-phase-7-run-recipe.md` (how to run the stack)

---

## 0. The flow we are building — and the one correction to it

The flow as described in planning was:

> generate lesson package → slides + audio narration built → **all patched together into a final
> video, uploaded to Bunny.net** → **fetched every time** the student plays it → mid-lecture quiz
> → and we read the CES score

**The generation half is exactly right. The delivery half inverts the architecture, and it is
self-defeating** — the moment a lesson is flattened into an MP4, the mid-lecture quiz, the
teach-back and the CES interventions have nowhere to live. They are client-side React state driven
by audio position (`AudioTimeline.tsx:16-60`); a video file has no `onTimeUpdate` store, no
per-slide DOM, and no place to pause for an answer. CLAUDE.md pins this:

> *"This is the FIRST-WATCH experience — never replace it with video; it is the only mode that
> carries quizzes, teach-back, CES interventions and jargon tooltips."*

**The reconciliation — the intent is honoured, the mechanism changes:**

```
 ┌──────────────────────────── WHAT WE BUILD ────────────────────────────┐
 │                                                                       │
 │  upload book (once)                                                   │
 │      └─► detect chapters ──► student picks chapter + tier             │
 │              └─► pipeline builds a LESSON PACKAGE (JSONB)             │
 │                    segments[] → slides + AI image                     │
 │                                 narration MP3 (one per segment)       │
 │                                 quiz · teach-back · interventions     │
 │                      └─► API signs every media URL on read            │
 │                            └─► React player = "the video lecture"     │
 │                                  synchronised audio + slides          │
 │                                  + quiz at each segment boundary      │
 │                                  + teach-back                         │
 │                                  + webcam → CES → interventions       │
 │                                                                       │
 └───────────────────────────────────────────────────────────────────────┘
              │
              ▼  LATER, OPTIONAL, RE-WATCH ONLY (not in this tracker)
      compiled MP4 on Bunny Stream — after assessment is already done
      `docs/decisionupdate.md` §7b · DECIDED, NOT DESIGNED, NOT IMPLEMENTED
```

**The player *is* the video lecture.** Synchronised narration and visuals — which happens to also
be interactive. That is the product. Bunny enters only for re-watch, and only after §7b's five
preconditions are met. It is deliberately out of scope here.

---

## 🔒 GATE RULE — inherited, no exceptions

Same rule as the book-scale tracker, and for the same reason.

1. A phase is complete when it has been **observed working end to end**, not when the code is
   written. `Implemented` is not `Verified`.
2. Phase N+1 does not begin until Phase N is `✅ Verified`.
3. **The observed result must be written into this file** — the actual numbers seen, never "works".
4. If verification fails, the phase returns to `🔨 In Progress`. It is never partially passed
   forward.

**Why:** the eval harness crashed on all five test PDFs and wrote a success-shaped result file
anyway (D58). Every defect in this project survived because something reported success without
being checked.

---

## Status

| # | Phase | Owner | Status |
|:--:|---|---|---|
| **L0** | Unblock spending | **User** | ⬜ Not started — **BLOCKING EVERYTHING** |
| **L1** | One real lesson package exists | Dev 1 | ⬜ Blocked by L0 |
| **L2** | Narration cost + timing truth | Dev 1 | ⬜ Not started (partly startable now) |
| **L3** | A student plays it in a browser | Dev 1 + Dev 2 | ⬜ Blocked by L1 |
| **L4** | Quiz + teach-back on a real package | Dev 3 | ⬜ Blocked by L1 |
| **L5** | CES made feedable | Dev 3 + Dev 4 | ⬜ Not started |
| **L6** | Attention capture (MediaPipe) | Dev 2 | ⬜ Not started |
| **L7** | Interventions fire *and recover* | Dev 4 | ⬜ Not started |
| **L8** | One student, one complete lesson | All | ⬜ The finish line |

**Totals:** 9 phases · 0 Verified · 0 Implemented · 9 Not started.

---

## L0 — Unblock spending

**Owner: the user.** Minutes of work; blocks all nine phases.

1. **Add OpenAI credits.** The key in `gate.env` is valid; the balance is zero. Phase 7's run died
   at `429 insufficient_quota / credit_balance_exhausted` with **$0.00 spent**.
2. **Fix the Langfuse `401`.** The same run logged `Failed to export span batch code: 401`. This
   run is the intended cost/latency calibration baseline — running it untraced means paying for it
   and getting no data, then paying again.

**Exit criterion:** a trivial paid call succeeds and a Langfuse span appears.

### Observed result
_Not yet run._

---

## L1 — One real lesson package exists

**Owner: Dev 1.** This is book-scale Phase 7's acceptance run. It is the single most valuable
action in this document.

**Why it matters — corrected 2026-08-05 after audit.** An earlier draft of this tracker claimed
"no lesson has ever been generated end to end in this repo's history". **That is false**, and it is
the sentence the whole plan rested on. Counter-evidence in three independent places:
`docs/dev2-sprint-tracker.md:27` — *"live end-to-end testing (real backend + real Supabase, first
time past `package_builder` landing for real)"*, 2026-07-27; `docs/dev1-tracker.md:9` — *"48 quiz
questions ... from a live Refresher-tier run"*, which cannot come from a mock; and D1's *"~4× real
TTS spend"*, which is real money.

**The accurate claim is narrower and still worth acting on:** the media nodes ran for real during
Sprint 2, but the **chapter-scoped pipeline has never run** — every book-scale change (page-bounded
extraction, `chapter_id` threading, chunk reuse) is unexercised against real providers. And the
unit tests remain mock-shaped: `tests/unit/test_tts_node.py` asserts
`mock_sarvam.synthesize.return_value = (b"AUDIO_BYTES", [])`, and **`b"AUDIO_BYTES"` is not audio** —
it passes if Sarvam's API changed or if every MP3 were corrupt.

**Revised risk:** expect failures in the book-scale seams, not in TTS itself. Budget hours, not days.

### Work
- Run per `docs/book-scale-phase-7-run-recipe.md` — check for stale processes first
- Generate **two chapters at two tiers**, both under ~40 pages so `truncation_expected` is false
- Validate each package against `packages/shared/lesson_package.schema.json`
- Record the **measured** cost per lesson against the $3.00 ceiling

### Exit criterion
Two schema-valid packages in `lessons.content`, each with real MP3s in `lesson-audio` and real
images in `lesson-images`, no truncation warning.

### End-to-end test
1. Upload `E:\test-books\d2l.pdf` → 21 chapters
2. Generate ch 0 (29 p) at T1 and ch 5 (26 p) at T3
3. Download one MP3 and **play it** — confirm it is audible speech, not a valid-but-empty file
4. Open one image — confirm it is a real render
5. Record cost, wall-clock, and per-node timings from Langfuse

**Expect failure in the book-scale seams** — page-bounded extraction, `chapter_id` threading,
chunk reuse. TTS and image generation have worked for real before (Sprint 2); the wrapper around
them has not.

### Discharges
Story 1-13 AC10 · book-scale Phases 5, 6, 6.5 · Track W W0–W4 (all currently `🧪 Implemented`).

### Observed result
_Not yet run._

---

## L2 — Narration cost and timing truth

**Owner: Dev 1.** Items 1 and 3 are startable **today, without credits**, and item 1 should land
**before** L1 because TTS dominates lesson cost.

### Work
1. **Implement the narration character cap.** `docs/decisionupdate.md` §8 (`:235-244`) requires a
   maximum of 10,000 characters per lesson across all segments. (There is no PRD file in this repo —
   an earlier draft cited one.) Grep finds **no such cap** in `config.py` or the narration node. TTS is the largest cost line and it is
   currently unbounded against a $3.00 ceiling. → **Scale Contract Q2.**
2. **Replace estimated slide timing with measured audio duration.** `tts_node` ships
   `"timestamps": []` **always** (`graph.py:3474`, and on the exception path `:3490` and in `_fallback_narration` `:3836` — no path emits a non-empty track); `_estimate_slide_timestamps`
   (`graph.py:3746-3792`) distributes slides across a *word-count × WPM estimate*. So slide changes
   are guessed against a real MP3 — **drift is unmeasured and will be visible in any demo.**
3. **Fix `_get_section_body`'s silent truncation** (`graph.py:1941-1960`) — still 6,000 chars with
   only a `logger.warning`. This is the canonical instance of the pattern CLAUDE.md now bans and
   the Scale Contract's Q2 headline example. Must become an explicit surfaced degradation.

### Exit criterion
Narration cost is bounded and the bound is tested; slide timing comes from real audio duration;
truncation is surfaced on the record, not logged.

### End-to-end test
Measure audio/slide drift across a full real lesson — state the worst-case offset in seconds.

### Scale & Load
- **Unit of work:** one lesson = N segments (measured 4–12). Narration ~800–1,500 chars/segment.
- **Fixed budget vs variable input:** 10,000 chars/lesson meets an unbounded chapter → must raise
  an explicit error or a surfaced degradation, never truncate silently.
- **Scope:** per lesson, per user.
- **Unbounded:** none introduced.
- **Inherited caps:** the 6,000-char section body was sized pre-book-scale — re-derive it.
- **Concurrency:** none — single-job path.

### Observed result
_Not yet run._

---

## L3 — A student plays it in a browser

**Owner: Dev 1 + Dev 2.** Track W (W0–W4) is all `🧪 Implemented`. A browser has rendered a real
lesson before (Sprint 2, 2026-07-27) — but **never a chapter-scoped one, and never through the new
books/chapters UI**, all of which is unverified.

### Work
- Point the web app at the live API and open the real lesson from L1
- Verify: audio plays · slides advance in sync · images render · text-only degrade when
  `image_url` is null · signed URLs resolve
- Measure the drift from L2 item 2

### Exit criterion
A person watches a full lesson start to finish and the audio matches the slides.

### Known risk
`_EMBEDDED_MEDIA_EXPIRY_S` (defined `modules/content/router.py:139`, used `:632`/`:639`) signs URLs once at fetch with **no auto-refresh**; `/api/media/signed-url` exists but has zero frontend callers. A
student who pauses past the window loses audio with only a manual Retry to recover.

### Observed result
_Not yet run._

---

## L4 — Quiz and teach-back against a real package

**Owner: Dev 3** (scorer/API) with Dev 2 (UI).

**Both are built and wired to real endpoints.** The quiz fires at **every segment boundary**
(`AudioTimeline.tsx:54-59`) — one per segment, not one mid-lecture. Teach-back follows each quiz,
is always skippable, has no timer, and never gates progress (all three match CLAUDE.md).

### Work
Validate quiz and teach-back payloads against the **first real package**, not fixtures. D18
("nothing ever creates a `sessions` row") was closed 2026-08-04 — confirm a real session is created
and that both endpoints find it.

### Exit criterion
A student answers every quiz and submits one teach-back; scores persist against a real session.

### Observed result
_Not yet run._

---

## L5 — CES made feedable

**Owner: Dev 3 + Dev 4.** This is the largest genuine gap, and it is worse than "unfinished".

### The three defects
1. **The formula exists twice and disagrees.** `assessment/ces.py:19-87` (Dev 3) has **zero
   importers** — dead code whose own docstring says "Dev 4 imports compute_ces()". He does not;
   `tutor/service.py:106-136` is a second implementation, and it is the one that runs.

   **Measured, both functions, identical inputs, shipped weights** (an earlier draft printed
   "≈32 vs ≈92", which was spliced from two *different* inputs — exactly the unmeasured number this
   tracker's gate rule forbids):

   | attention (all three) | `assessment/ces.py` | `tutor/service.py` (LIVE) | ratio |
   |---|---|---|---|
   | 1.0 | 53.33 | 100.00 | 1.875 |
   | **0.9** | **48.00** | **90.00** | 1.875 |
   | 0.8 | 42.67 | 80.00 | 1.875 |
   | 0.6 | 32.00 | 60.00 | 1.875 |

   A fixed 1.875× ratio whenever `quiz_accuracy is None`: Dev 3 keeps the 0.35 weight and feeds it
   `0.0`; Dev 4 drops it and redistributes. **`ces_threshold = 50`, so at 0.9 attention — a student
   paying near-perfect attention who simply has not reached a quiz yet — Dev 3's function says
   INTERVENE and Dev 4's says fine.** The threshold splits them across the entire range below 1.0.
   → register as a defect.
2. **`behavioral_score` has no producer anywhere** — a required wire field with no definition, no
   computation, in either app.
3. **`quiz_accuracy` is derivable but nothing derives it.** `QuizResult` (`assessment/schemas.py:77-83`)
   already returns `correct_count`, `total_count` and `score` (= accuracy × 100), so the 0–1 fraction
   is one division away — **nothing performs the join**, which is an integration task, not a contract
   redesign. The real hazard is the neighbouring field: `ces_contribution`
   (`assessment/service.py:410`, `:601`) is **already weight-multiplied**, so anyone who reasonably
   reaches for it sends a wrong number. Worse, `packages/shared/types/ws.ts:90-100` declares every
   field as bare `number` and **specifies no range at all** — the wire contract is *silent* on scale,
   which is more dangerous than disagreeing.

Also: `_parse_signal` (`tutor/service.py:54-100`) **hard-requires** all three MediaPipe fields and
raises otherwise — there is no partial-signal path, so nothing can send CES until L6 lands.

### Work
Delete one CES implementation and keep one · define and produce `behavioral_score` · expose the
quiz/teach-back fractions the wire expects · decide whether a partial signal is valid.

### Exit criterion
A CES value is computed from real signals during a real lesson, and the same inputs produce the
same number from one implementation.

### Observed result
_Not yet run._

---

## L6 — Attention capture

**Owner: Dev 2.** CLAUDE.md's locked choice is MediaPipe Face Landmarker WASM.

**Not one line exists.** No `@mediapipe/*` dependency, zero hits for `FaceLandmarker`,
`getUserMedia` or `navigator.mediaDevices` in `apps/web/src`. The only trace is a comment at
`PlayerLoader.tsx:8` — *"will load MediaPipe WASM in Sprint 3."*

### Non-negotiable constraints (CLAUDE.md §18)
- **Raw webcam video NEVER leaves the browser** — only 5 derived numbers
- Explicit consent required before any capture: modal + `user_consents` row. The DB side is real
  and applied (`20260702000000_dpdp_user_consents.sql`) and Dev 3 shipped the write endpoint on
  2026-08-05 (Story 3-32, closing D29) — so the backend is ready and the UI is not.

### Exit criterion
Consent recorded, capture running, five derived numbers arriving over the WebSocket, no raw frames.

### Observed result
_Not yet run._

---

## L7 — Interventions fire, and recover

**Owner: Dev 4.** The FSM is genuinely well built — all 7 states real, all 5 guard rules
implemented — with two defects that matter.

1. **`INTERVENING` is a one-way trap.** It exits only on `intervention_complete`, an event
   **dispatched by nothing** — absent from `_CLIENT_DRIVABLE_EVENTS`, `_TUTOR_CLIENT_EVENTS`,
   `wireTypes.ts`, and every server path. No timeout. **The first intervention that ever fires
   permanently kills CES monitoring for that session, silently.** Unreachable today only because
   L6 does not exist. → register before L6 lands.
2. **Every FSM node returns `{**state, ...}`** — the pattern CLAUDE.md bans repo-wide. Not
   currently harmful (no `operator.add` channels), but `test_node_return_shape.py:33` scans only
   `app/modules/content/pipeline`, so **the tutor graph is outside the guard**. `FIXED-UNGUARDED`.

Also: both `modules/tutor/router.py` endpoints return **501**.

### Exit criterion
An intervention fires from a real low CES, is delivered to the client, and the session **returns to
TEACHING** afterwards.

### Observed result
_Not yet run._

---

## L8 — One student, one complete lesson

**The finish line.** Upload a book → pick a chapter → generate → watch the whole thing with
synchronised narration and slides → answer every quiz → submit a teach-back → have attention
measured → receive at least one intervention → reach a session report.

### Exit criterion
A real person does all of the above once, unassisted, and the numbers are recorded here.

### Observed result
_Not yet run._

---

## Per-developer handoffs

Each dev has one doc with their deviations, their alignment work, what they owe and what they wait
on. Written to be opened cold and started from.

| Dev | Doc | Owns |
|---|---|---|
| Dev 1 | `docs/handoffs/lesson-delivery-dev1.md` | L1 acceptance run · L2 narration cap, timing, truncation |
| Dev 2 | `docs/handoffs/lesson-delivery-dev2.md` | L3 player verification · L6 MediaPipe + consent UI |
| Dev 3 | `docs/handoffs/lesson-delivery-dev3.md` | L4 quiz/teach-back on a real package · L5 CES reconciliation |
| Dev 4 | `docs/handoffs/lesson-delivery-dev4.md` | L5 CES contract · L7 INTERVENING fix + `behavioral_score` |

---

## Interdependency map

```
        ┌─────────────────────────────────────────────┐
  USER  │ L0  credits + Langfuse 401 (check D62 first) │
        └───────────────────┬─────────────────────────┘
                            │ blocks everything
                            ▼
  DEV 1   L2 narration cap ──► L1 acceptance run ──► a REAL lesson_id
          (start NOW,           (needs L0)               │
           no credits)                                   │
                            ┌────────────────────────────┼────────────────┐
                            ▼                            ▼                ▼
  DEV 2                   L3 play it            DEV 3  L4 quiz +    DEV 4  observe
                          measure drift                teach-back          lesson_ready
                            │                            │                │
                            │        ┌───────────────────┴────────────────┤
                            │        ▼                                    ▼
                            │   SYNC-A: which CES implementation survives (D3 + D4)
                            │        │
                            │        ▼
                            │   SYNC-B: attention wire scale + behavioral_score (D2+D3+D4)
                            │        │
                            ▼        ▼
  DEV 2                   L6 MediaPipe + consent  ◄── BLOCKED until SYNC-B
                            │
                            ▼
  DEV 4                   L7 interventions fire AND recover
                            │        ▲
                            │        └── the INTERVENING fix must land BEFORE L6 ships
                            ▼
  ALL                     L8  one student, one complete lesson
```

**The one ordering rule that is not obvious:** Dev 4's `INTERVENING` fix must land **before** Dev 2's
MediaPipe work. Today the trap is unreachable because no attention signal exists. The moment L6
ships, the first distraction puts a session in INTERVENING permanently and silently disables the
tutor for the rest of that lesson.

---

## Integration strategy

**Branching.** One story, one branch off `main`, PR into `main`. **No integration branch this
time.** Book-scale used one and it hid a real problem — CI triggered only on PRs to `main`, so six
phases merged with zero checks. The trigger now includes `book-scale/**` and `dev`, but the simplest
fix is to stop needing it.

**Story-first gate applies** (CLAUDE.md): story file committed alone, pushed, chronologically first
on the branch, and it carries a `## Scale & Load` section answering the six questions
(`docs/SCALE-CONTRACT.md`). A story without it goes back.

**Contract freeze points.** These are the only places two devs can break each other silently:

| Sync | What is frozen | Who signs | Blocks |
|---|---|---|---|
| **SYNC-A** | Which CES implementation survives, and the `quiz_accuracy is None` behaviour | Dev 3 + Dev 4 | L5, and any CES number anyone quotes |
| **SYNC-B** | The `attention_signal` wire: field scale (0–1 vs 0–100), `behavioral_score`'s definition, whether partial signals are valid | Dev 2 + Dev 3 + Dev 4 | L6 — Dev 2 cannot emit a frame without it |
| **SYNC-C** | A real `lesson_id` with working signed URLs exists | Dev 1 announces | L3, L4, and Dev 4's `lesson_ready` observation |

**SYNC-B is the dangerous one.** `packages/shared/types/ws.ts:90-100` declares every field as bare
`number` and **specifies no range at all**. A contract that is silent is worse than one that
disagrees — three devs can each be internally consistent and still not interoperate. Freeze it in
`ws.ts` with explicit ranges, not in a conversation.

**Review gate.** Every PR takes the 6-layer `/bmad-code-review` (CLAUDE.md), including the **Scale &
Load** layer. Cross-boundary changes — anything touching `ws.ts`, the CES formula, or
`package_builder` output — additionally need the other affected dev on the PR.

**Verification standard.** Inherited from the gate rule: a phase is done when it is **observed
working**, with the numbers written into this file. Specific to this sprint, because the failure
mode is well documented here: **a mock-only assertion does not close a phase.** `test_tts_node.py`
asserts `mock_sarvam.synthesize.return_value = (b"AUDIO_BYTES", [])` — `b"AUDIO_BYTES"` is not
audio, and that test passes if every MP3 is corrupt.

---

## Success criteria for this sprint

**The sprint succeeds when one person does this once, unassisted, and the numbers are recorded
here:**

1. Upload a real textbook → chapters appear
2. Pick a chapter and a tier → generation starts
3. Watch the whole lesson: **narration audible, slides in sync**
4. Answer the quiz at **every** segment boundary
5. Submit one teach-back
6. Have attention measured with consent recorded
7. Receive at least one intervention — **and the session returns to TEACHING afterwards**
8. Reach a session report

**Measurable exit numbers — none of these exist yet, and all must be recorded:**

| Metric | Target | Status |
|---|---|---|
| Cost per lesson | ≤ $3.00 (PRD §12 ceiling) | **never measured** |
| Generation wall-clock | 5–15 min | never measured end to end |
| Audio/slide drift | state it in seconds; agree a ceiling once known | **never measured** |
| Narration length | ≤ 10,000 chars/lesson (`decisionupdate.md` §8) | **cap not implemented** |
| Truncation warnings | zero, for chapters under ~40 pages | never verified live |
| CES agreement | one implementation, one number | **two implementations, 1.875× apart** |

**What "done" is not:** green unit tests, a passing MSW suite, or a phase marked Implemented. Every
defect this project has found was something that reported success without being checked.

---

## Cross-team asks

| Teammate | What Dev 1 cannot unblock | The ask |
|---|---|---|
| **Dev 2** | Track W unverified; player never saw a real lesson; MediaPipe absent (L3, L6) | Verify the player against real signed URLs the day L1 lands. Then build attention capture + consent UI. |
| **Dev 3** | Two CES implementations, one dead; quiz fraction not exposed (L4, L5) | Delete one CES implementation. Expose the 0–1 fractions the wire contract wants. Validate scoring against the first real package. |
| **Dev 4** | `INTERVENING` trap; `behavioral_score` undefined; tutor endpoints 501 (L5, L7) | Make `intervention_complete` reachable, or add a timeout. Define `behavioral_score`. |
| **Dev 2 + Dev 4** | Revision video (§7b item 4) | **Nothing yet.** Do not open until L8 is green. |

---

## Out of scope, deliberately

- **The compiled MP4 / Bunny Stream.** §7b, decided but undesigned. Revisit after L8 — and weigh it
  against the cheaper alternative §7b already records: **Bunny CDN as a pull-zone in front of
  Supabase Storage**, which gives cheap egress for the existing MP3s and images with zero
  transcoding, zero video pipeline and zero player change.
- Everything not on the path from "book uploaded" to "student finished a lesson".

## Update protocol

When a phase changes state, in the **same** response: update its Status line → fill in **Observed
result** with the actual numbers seen, never "works" → update the Status table → update
**Last updated**. Never mark a phase Verified without recorded evidence.
