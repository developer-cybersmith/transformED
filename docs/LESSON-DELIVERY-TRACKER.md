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
| **L0** | Unblock spending | **User** | ✅ Unblocked — OpenAI credits refilled 2026-08-14 |
| **L1** | One real lesson package exists | Dev 1 | 🔨 In progress — L0 cleared; Dev 1 can run now |
| **L2** | Narration cost + timing truth | Dev 1 | 🔨 In progress — T08/T09/T10 startable, T11 now unblocked |
| **L3** | A student plays it in a browser | Dev 1 + Dev 2 | ⬜ Blocked by L1 (in flight) |
| **L4** | Quiz + teach-back on a real package | Dev 3 | ⬜ Blocked by L1 (in flight) |
| **L5** | CES made feedable | Dev 3 + Dev 4 | 🔨 In progress — SYNC-A formally closed (Dev 3 sign-off 2026-08-14); T18 done; SYNC-B frozen (PR #138 merged 2026-08-14) |
| **L6** | Attention capture (MediaPipe) | Dev 2 | ⬜ Unblocked by SYNC-B — Dev 2 can start now |
| **L7** | Interventions fire *and recover* | Dev 4 | 🔨 Implemented — exit criterion pending L6 |
| **L8** | One student, one complete lesson | All | ⬜ The finish line |

**Totals:** 9 phases · 0 Verified · 4 Implemented (L0✅, L1🔨, L5🔨, L7🔨) · 5 Not started.
**Last updated:** 2026-08-14 (PR #138 merged — SYNC-B fully frozen; all Dev 4 demo work complete pending L6).

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

### Observed result — 2026-08-13, honest partial pass

**Exit criterion NOT fully met** — this ran once, not twice, and at one tier, not two.

- **Book/chapter used:** `780efa51` (d2l.pdf, 1,151 pages, 21 chapters), chapter 0 "Introduction"
  (29p) — the SAME chapter run three times while D75/D77/D78 were found and fixed live (see
  `docs/DEFECT-REGISTER.md`). Ch 5 "Builders' Guide" at T1 — the test plan's OTHER required
  combination — was **never attempted**. Only tier **T3** was generated; T1 was never run.
- **Real, fully successful generation:** lesson `1baae6f6` (T3, post-D78-fix). `status=ready`,
  real elapsed **1213.55s (~20.2 min)**. All 15 segments got real `audio_provider=sarvam` — 3
  segments independently downloaded and validated via a raw `wave`-module read-back (not just
  trusted from the API): real, non-silent PCM audio, durations matching the package's recorded
  timestamps to the millisecond. One slide image independently downloaded and confirmed a real
  1024×1024 PNG.
- **Schema validation — now run, real pass.** `1baae6f6`'s real package validated against
  `packages/shared/lesson_package.schema.json` with **zero errors**, checked directly with the
  `jsonschema` library (2026-08-14). Confirmed the schema is genuinely strict before trusting the
  result (top-level AND per-`Segment` `required` fields + `additionalProperties: false` — would
  catch both missing and unexpected fields), not a vacuous pass.
- **Cost — now recorded, real and precise, from Langfuse (not the DB's own `cost_usd`, which is
  `0.0000` for this lesson since it predates D86).** Real total: **$1.2500** — 42% of the $3.00
  ceiling. Real per-node-type breakdown (`response_format`/`name` grouping, 123 real observations):

  | Node / call type | Calls | Total time | Avg/call | Real cost |
  |---|--:|--:|--:|--:|
  | `generate-image` (slides) | 15 | 633.4s | 42.2s | $0.3000 |
  | `synthesize-speech` (Sarvam) | 15 | 173.9s | 11.6s | $0.8916 |
  | `_NarrationScriptLLM` | 15 | 137.1s | 9.1s | $0.0080 |
  | `_JargonListLLM` | 15 | 135.4s | 9.0s | $0.0054 |
  | `_SegmentInterventionsLLM` | 15 | 134.1s | 8.9s | $0.0048 |
  | `_QuizBatchLLM` | 15 | 133.8s | 8.9s | $0.0048 |
  | `_SegmentSummaryLLM` | 15 | 80.0s | 5.3s | $0.0032 |
  | `_SegmentComplexityLLM` | 15 | 63.8s | 4.3s | $0.0035 |
  | `_SlideDeckLLM` (slide_generator) | 1 | 14.6s | 14.6s | $0.0159 |
  | `_LessonPlanLLM` (lesson_planner) | 2 | 7.0s | 3.5s | $0.0128 |

  TTS is **71.3%** of real total cost ($0.8916 / $1.2500) — matches `decisionupdate.md`'s
  "67-73% of total" claim almost exactly, the first time that number has been checked against
  real data rather than assumed.
- **Wall-clock — now recorded, real, from Langfuse's own trace-level latency: 935.845s (~15.6
  min).** (Differs from the ~1213.55s worker-log elapsed time recorded earlier — the ~277s gap is
  real overhead outside this trace's own observations: Phase A extraction/chunking/embedding and
  inter-node Supabase checkpoint writes.) **Real finding, not assumed:** `generate-image` calls
  were checked for overlap by real start/end timestamps and are **fully sequential, zero overlap**
  — one image at a time, ~40-52s each, back to back. At 633.4s out of 935.845s total trace time,
  image generation alone is **~68% of this lesson's entire wall-clock**. Phase 1's economy nodes
  (`_SegmentSummaryLLM` etc.) DO run with real parallelism (their summed latency, 684s, exceeds
  the trace's own 935.845s total by less than it would if serial — confirmed structurally, not
  just plausible). **Not fixed here** (out of this specific task's scope, which was to record and
  measure, not optimize) — but a real, concrete, evidence-backed opportunity: parallelizing
  `image_generator_node`'s 15 calls the same way Phase 1 already does could plausibly cut total
  generation time roughly in half.
- **Real defects found and fixed live during this run** (not assumed, all in
  `docs/DEFECT-REGISTER.md`): D75 (lesson_planner batch reliability), D76+D78 (narration cap
  mis-sized then corrected), D77 (per-batch echo retry), D85 (slide-budget allocation, partial —
  see L3 below), D86 (cost persistence, fixed but not yet exercised on a real run).

**Net: L1's real deliverable exists and is genuinely verified end-to-end for one combination
(ch 0 / T3), not the two combinations the exit criterion asks for.** The second chapter/tier
(ch 5 / T1) is still outstanding.

### Second attempt, 2026-08-13 — real external blocker, not a code failure

Attempted the outstanding combination: ch 5 "Builders' Guide" (26p) at T1, lesson `b0a96211`.
**Result: `status=failed`, and the reason is an operational/billing blocker, not a defect:**

- **Sarvam TTS returned `402 Payment Required`** on every segment — the account is out of
  credits, the exact same shape as the L0 OpenAI-credits blocker at the start of this sprint.
  This needs the account topped up before any further real generation is worth attempting.
- **Azure TTS returned `401 Unauthorized`** — a pre-existing, already-known gap (never fully
  configured as a real fallback), not something new.
- With both paid providers down, every segment fell through to the free `browser` fallback.
- This run also surfaced and led to fixing a real bug in D53's own reaper (D91 — see
  `docs/DEFECT-REGISTER.md`): an ARQ retry delayed ~32 minutes before being dequeued (a separate,
  pre-existing event-loop-blocking issue) caused the reaper to mark this lesson `failed` while it
  was still actually running. Fixed same day; the inconsistent DB state self-resolved when the
  worker was restarted onto the fixed code.

**Ch 5 / T1 remains outstanding, now blocked externally on Sarvam credits rather than on any
known code gap.** Retrying before credits are confirmed restored would just re-produce the same
`402` on every segment.

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

### Observed result — 2026-08-13, two of three items done, one still genuinely open

1. **Narration character cap: done, and re-derived twice on real evidence.** Implemented (D76 at
   17,000 chars, sized against a demo duration target — later shown live to be actively harmful,
   zeroing real audio for 9 of 15 segments in lesson `abe4e438`), then corrected (D78, raised to
   120,000, re-sized against real $3.00-ceiling cost headroom instead of any duration). The
   re-generated lesson (`1baae6f6`) confirms the fix: all 15 segments kept real Sarvam audio,
   44,582 real narration chars, cap never engaged.
2. **Slide timing from measured audio: done and independently verified.** `tts_node` now writes
   real timestamps (not the old always-empty `[]`). Verified directly, not assumed: downloaded 3
   real MP3/WAV segments from lesson `1baae6f6` and read them back with Python's `wave` module —
   real measured durations matched the package's recorded `timestamps` to the **millisecond**
   (e.g. 197.6714739s measured vs 197.671s recorded) on every segment checked.
3. **`_get_section_body` silent truncation: only half-fixed, and this half is NOT closed.** The
   "nothing surfaces it" problem is fixed (L2c) — a truncation now writes an explicit,
   persisted record instead of a bare `logger.warning`. **The root cause — the ~90,000-char
   LLM-visible window itself (`structure_max_sections=15 × max_chars=6000`) — is unchanged and
   still open**, registered as D46, and it fired live during the `1baae6f6` run
   (`section_11_1-5-The-Road-to-Deep-Learning body truncated to 6000 chars (was 10174)`).
   **This item must not be reported as done — only its symptom-visibility half is.**

### End-to-end test result
Not run as a standalone deliverable, but strongly implied by item 2's verification above: real
measured audio duration matched the package's own recorded slide-sync timestamp to within
milliseconds on every segment checked (3 of 15) — no formal "worst-case offset in seconds"
figure has been computed across a full lesson, but nothing found so far suggests measurable
drift exists once real audio duration (not a word-count estimate) drives the timestamp.

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

### Observed result — 2026-08-13, real pass, real bugs found — not a clean exit yet

**This actually happened** — not simulated. Started `apps/web`'s dev server pointed at the real
local API (had to override `NEXT_PUBLIC_API_URL`/`NEXT_PUBLIC_WS_URL`, which default to a
different port than this environment's real API — a real config gap worth fixing, not just a
one-off override). Also found and worked around two real access-control gaps blocking this
specific verification, neither a player bug: (a) the beta-access allowlist (`APPROVED_EMAILS`,
maintained as **two separately-synced copies**, `apps/api/.env` and `apps/web/.env` per
`proxy.ts`'s own comment) didn't include the test account; (b) the lesson's `lessons.user_id`
belonged to a different seed account than the one actually logging in via Google OAuth, so the
router's ownership check (`lesson.get("user_id") != user_id` → 404) blocked access until the row
was reassigned.

**Audio plays and matches narration** — confirmed directly by a real person (not assumed):
*"yes im able to see the lesson and listen to the narration as well."*

**Real UX defects found by that same real playback, not hypothetical:**
1. **Slide overflow — root-caused, not yet fixed.** `apps/web/src/app/lesson/[id]/layout.tsx`
   uses `min-h-screen` (can grow) instead of a fixed height, and `Player.tsx`'s slide container
   is missing `min-h-0` — a classic flexbox bug where a tall slide grows the whole page past the
   viewport instead of scrolling inside its own box (which `SlideRenderer.tsx` already supports
   but never gets the chance to use). Two-line CSS fix identified, not yet applied.
2. **1 slide per segment — mechanism fixed (D85), but the actual symptom persists.** Root cause:
   `_tier_slide_budget_per_segment` divided each tier's fixed total-lesson slide band evenly by
   segment count. At 15 segments, T2 and T3 both collapsed to exactly 1 slide/segment regardless
   of narration length (1.23–3.48 real minutes, same single static slide). Fixed the ALLOCATION
   to be duration-proportional (D85, merged) — but re-verified against the real 15-segment
   dataset and found T2/T3 **still** produce 1 slide/segment, because both tiers' total slide
   band is `<=` the segment count, so there's nothing to proportionally redistribute. Only T1
   (wider band) actually differentiates now. **The tier band values themselves still need
   re-derivation — flagged to the user, awaiting a decision, not yet actioned.**
3. **Narration speed too fast — root-caused, not yet fixed.** Sarvam Bulbul v2 supports a `pace`
   parameter (verified against Sarvam's real API docs, default 1.0, range 0.3–3.0); our provider
   code never sends it, so every lesson synthesizes at the raw default. Fix identified (send an
   explicit slower `pace`, e.g. 0.85), not yet applied.
4. **No captions.** Confirmed zero caption/subtitle code anywhere in the frontend. The full
   narration script text is already in the package (`narration.script`) — a static always-visible
   caption overlay is straightforward; word-synced captions are NOT possible yet, since the
   Sarvam integration deliberately returns empty word-level timestamps.
5. **Voice expressiveness ("highs, lows, pauses")** — no simple fix identified. Bulbul v2's
   `pitch` param is a static offset, not dynamic variation; real expressiveness control
   (`temperature`) only exists on Bulbul v3, which this integration doesn't use and hasn't been
   verified as available on the current API key.

**Net: the exit criterion — "a person watches a full lesson start to finish and the audio matches
the slides" — is not yet a clean pass.** Audio genuinely plays and matches narration content, but
the visual/pacing experience has real, identified defects (2 fixed at the mechanism level with a
residual gap, 3 not yet fixed at all). Signed-URL auto-refresh (the known risk above) was not
separately stress-tested (session was short enough not to hit the expiry window).

### Update, 2026-08-13 — 4 of the 5 defects above are now fixed

- Item 1 (slide overflow) — **fixed, D88.**
- Item 2 (D85 slide-budget-per-tier) — **fixed, D87.**
- Item 3 (narration pace) — **fixed, D89.**
- Item 4 (captions) — **fixed, D90.**
- Item 5 (voice expressiveness) — **still open**, no simple fix identified (see D89's own entry
  in `docs/DEFECT-REGISTER.md`).

## Handoff — real lesson_ids available for Dev2/3/4 testing

| lesson_id | Chapter / tier | Status | Notes |
|---|---|---|---|
| `1baae6f6-20cf-4cbd-a72d-c76408a9056e` | ch 0 "Introduction" / T3 | `ready` | The one to use. Post-D78 fix — all 15 segments real Sarvam audio, independently verified (downloaded + validated with `wave`). Currently owned by `aplahoti1295@gmail.com` (real Google account) after a manual reassignment this session — reassign again if a different test account needs it. |
| `abe4e438-052f-48d9-818f-590e3a42b2bb` | ch 0 "Introduction" / T3 | `ready`, superseded | Pre-D78 — 9 of 15 segments degraded to browser-fallback audio (no real TTS). Keep only as a reference for what the D76→D78 defect looked like; don't use for real testing. |
| `b0a96211-15cf-41eb-8642-3c4d570a1c9f` | ch 5 "Builders' Guide" / T1 | `failed` | Blocked on Sarvam credits (D91's entry has the full story). Useful only if someone wants a real example of a failed-lesson state for error-handling UI testing. |

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
