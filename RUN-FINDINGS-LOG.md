# Run Findings Log

**Purpose:** every time we actually run something — a test suite, a live eval, a manual
verification against real providers — the result and whatever it found gets logged here, not
left in chat history. The point is to build up one place that shows what's actually been
verified vs. assumed, so gaps can be triaged into targeted fixes instead of staying scattered.

**How to use this:**
- After every meaningful run, add an entry to the **Run Log** below (newest at the top).
- If a run finds something actionable, add/update a row in **Open Gaps** above it.
- When a gap gets fixed, move it to **Closed Gaps** with the run that confirmed the fix — don't
  delete it, this file's value is the history, not just the current state.
- A gap that gets a formal defect ID lives authoritatively in `docs/DEFECT-REGISTER.md` — this
  file links to that ID rather than duplicating its full text. Not everything logged here needs
  a `D-nn` ID; use one when it's a real, fixable defect, skip it for a plain observation.

**Started:** 2026-08-21 (backfilled with every run from this session so far).

---

## Open Gaps — Targeted Fix Candidates

| # | Gap | Found in run | Severity | Status |
|---|-----|---------------|----------|--------|
| 1 | ~~Rotated/low-quality real scans OCR into silent, ungated garbage~~ | Real-world PDF investigation (2026-08-20) + confirmed live (2026-08-21) | High | **Fixed 2026-08-21 — `D128` CLOSED.** Unit/mock-level verified (10 tests, 1245/9 skipped full regression, zero regressions). **Not yet re-verified live** — the 2026-08-21 live confirmation was pre-fix; see Closed Gaps below. |
| 2 | Multiple concurrent real users has never been tested. Three concrete, already-known risks: the circuit breaker trips per-provider globally (one user's failure can lock out others); `D45`'s duplicate-request check has no real DB constraint; `D49`'s rate limiter silently multiplies across server replicas. | Discussion following the real-world live run (2026-08-21) | **High** | Open — `D129`, scoped to Sprint 4 |
| 3 | The official Sprint 3 eval harness — 20 synthetic PDFs — has **never actually completed a run**, despite the tracker previously claiming it was "done, blocked only on Sarvam credits." Three silent blockers found and fixed in sequence (`D124`, `D126`, `D130`) — all now cleared. | Sprint 3 completion audit (2026-08-20) + attempted live (2026-08-21) | Med (blocks S3-2 entirely, see #4) | **All known blockers fixed 2026-08-21 (see Closed Gap #2). Not yet re-attempted live** — next `--run-live-eval` is the real confirmation. |
| 4 | Prompt tuning (S3-2) cannot be honestly completed — its own rule requires real before/after scores from the 20-PDF harness, which has never produced any (see #3). One prompt change (`D125`) already shipped, but tuned against a static scoring rule, not real data — doesn't satisfy the AC. | Sprint 3 completion audit (2026-08-20) | Med | Open — blocked on #3 |
| 5 | Encrypted PDFs fail with a raw Python traceback as the error message (`PDFium: Incorrect password error` inside a full stack trace), not a clean, identifiable "this file is password-protected" message. Confirmed: it does NOT crash the worker or silently pass — it fails loud via the subprocess exit-code path — but the message quality is poor. | Real-world PDF investigation (2026-08-20) | Low | Open — not registered as a `D-nn` yet |
| 6 | Non-English OCR, multi-column layouts, and fillable forms remain completely untested — the 4 real-world fixtures (`D127`) close scan/rotation/corruption/encryption, not these three. | Real-world PDF investigation (2026-08-20) | Low/Med (unknown — never measured) | Open — not registered, no fixtures exist yet |
| 7 | Admin panel (S3-4) is API-only — zero UI exists anywhere in `apps/web`. Satisfies S3-4's own written AC, but not the Sprint 3 goal line's "admin panel live." | Sprint 3 completion audit (2026-08-20) | Low (scope question, not a bug) | Open — needs a product decision, not a fix |
| 8 | ~~Circuit breaker (S3-3) untested against real Redis; Langfuse cost attribution (S3-5) never confirmed against a real dashboard~~ | Sprint 3 completion audit (2026-08-20) | Low | **Langfuse half corrected 2026-08-24 — the "401 Unauthorized, no credentials configured" claim was WRONG.** Connected directly with the real credentials this session: `auth_check()` returned `True`, and real trace data was successfully pulled (see D132, and the traces `traced_node()` has been writing all along). The earlier 401 was almost certainly the D126 credential-shadowing bug, active at the time — not a broken/missing Langfuse account. Circuit-breaker-vs-real-Redis half still genuinely untested. |
| 9 | ~~The 20 eval-harness fixtures all lack any real chapter structure~~ | Investigation after stopping the 2026-08-21 live run | High | **Fixed 2026-08-21 — `D130` CLOSED.** See Closed Gap #2. |
| 10 | Same root mechanism as #9, wider blast radius: a real book with no detectable structure has no upper bound on the "chapter" size a real student could select — not just an eval-harness inconvenience. Not an overspend risk (the $3 ceiling still holds via downshift), but a real time/UX/quality-degradation risk, mechanism confirmed, real-world likelihood unmeasured. | Surfaced planning the D130 fix | Med-High | Open — `D131`, deliberately not fixed (product/UX decision). Recommended to decide alongside `D129` at Sprint 4. |
| 11 | **The real, dominant reason lessons take so long: slide images generate ONE AT A TIME, not concurrently.** Measured via real Langfuse traces across 6 real lessons (both today's post-D130 run and the 2026-08-21 real-world run) — image generation alone is 86-95% of every lesson's total time, 6/6 consistent, every image taking a strikingly uniform ~41-45s. Phase 1's economy nodes already run concurrently per segment; `image_generator_node` has no equivalent for its own per-slide calls. This is a bigger time driver than D130 ever was. | Langfuse trace analysis during the D130 live re-verification (2026-08-24) | **High** | Open — `D132`, not fixed. Real fix candidate: bound-concurrency fan-out for `generate-image` calls, same pattern `_IMAGE_UPLOAD_CONCURRENCY` already uses for image *uploads* in the same file. |

---

## Closed Gaps

| # | Gap | Fixed in run | Fix summary |
|---|-----|--------------|-------------|
| 1 | Rotated/low-quality real scans OCR into silent, ungated garbage | 2026-08-21 — D128 fix build | `_ocr_page_text` now returns real Tesseract confidence alongside the text; below `_OCR_LOW_CONFIDENCE_THRESHOLD=60` the content is still accepted (never silently dropped) but the page is named in a new `low_confidence_ocr_pages` list, persisted on the `lesson_jobs` checkpoint the same way `tables_detected`/`docling_pages` already are. 10 new/updated tests, 1245/9 skipped full regression, zero regressions. **Still owes a live re-verification** — see Run Log entry. |
| 2 | The 20 eval-harness fixtures all resolved to 1 whole-document "chapter" (100-400 pages for the "long" ones, 2.5x-10x the normal ~40-page workload) — the real cause of the 6+ hour stalled run | 2026-08-21 — D130 fix build (2 parallel agents) | The 4 "long" fixtures now carry real PDF outline entries (`start_section()`) every 40 pages with distinct chapter titles — re-verified independently against the actual regenerated fixtures: 3/4/7/10 real chapters, every span now 40 pages, none of the old 40-400-page whole-document spans remain. Bonus fix in the same pass: a real non-determinism bug in `creation_date` that silently broke the generator's own "byte-identical two runs" promise. Also fixed the secondary opacity gap: both eval runners now write a real-time, truncated-per-run `progress.jsonl`. 5 new/updated tests, full regression **1250 passed, 9 skipped**, zero regressions. **Not yet re-verified against a real live run** — the next `--run-live-eval` attempt is that confirmation. |

---

## Run Log

### 2026-08-24 — Langfuse trace analysis: found the real dominant time cost (D132)
**Method:** while the restarted 20-PDF live eval was in progress (safe, read-only — did not
touch the running process), queried Langfuse's own API directly for the real per-node trace
data of every completed lesson so far, plus the 2 real-world lessons from the earlier D127 run,
to answer "where does the time actually go inside one lesson."

**First finding: Langfuse access itself works.** `get_langfuse().auth_check()` returned `True`
and pulled real trace data successfully — corrects Open Gap #8's earlier "401 Unauthorized, no
credentials configured" claim, which was almost certainly the now-fixed D126 credential-
shadowing bug active at the time, not a broken Langfuse account.

**Second finding — corrects a wrong claim made earlier in this same conversation:** an initial
read of `lf.api.trace.list()`'s top-level trace names misidentified `package_builder_node` as
the bottleneck (its listed "trace" showed ~1481s latency for `short_10page`). Pulling the FULL
trace detail (`lf.api.trace.get()`, all observations) showed this was wrong — the trace's
displayed name is inherited from whichever node last touched it, not what dominates the time.
`package_builder_node`'s own real span is ~1-2 seconds, exactly as it should be.

**The real finding, quantified across 6 real lessons (4 from today, 2 from 2026-08-21's D127
run):**

| Lesson | Total | Image gen | % | # images | Avg/image |
|---|---|---|---|---|---|
| short_1page | 395s | 368.5s | 93% | 8 | 44.7s |
| short_3page | 1003s | 955.7s | 95% | 21 | 44.3s |
| short_10page | 1481s | 1339.6s | 90% | 30 | 43.4s |
| short_sparse | 1486s | 1412.5s | 95% | 32 | 42.9s |
| real_scan_like | 415s | 358.1s | 86% | 8 | 43.1s |
| real_scan_like_rotated | 290s | 255.6s | 88% | 6 | 41.2s |

`image_generator_node`'s own span duration is essentially the SUM of its child `generate-image`
calls, not the MAX — the signature of serial execution. Phase 1's economy nodes are confirmed
(same trace data) to genuinely run concurrently per segment; image generation has no equivalent
fan-out for its own per-slide calls. 6 of 6 measured lessons show the identical pattern
regardless of content type, size, or day. → **D132 registered (open, not fixed).**

**Answers the standing question directly: no more PDFs are needed to identify this** — the
signal is already unambiguous across 6 independent, real data points spanning both today's and
last week's runs.

---

### 2026-08-24 — 20-PDF S3-1 live eval, 1st post-fix attempt: aborted in <2 min, Redis down
*(Note: logged in-session as "2026-08-21" at the time — corrected here against real Langfuse
server timestamps, which are authoritative. Any nearby entries still reading 2026-08-21 for
this same work carry the same correction; not individually re-dated.)*
**Command:** `pytest tests/evals/test_live_run.py -v --run-live-eval`
**Result:** Stopped intentionally after 7 of 20 PDFs, all failed with `Connection refused` to
`localhost:6379` — Redis had stopped running since it was last confirmed up earlier this
session (unrelated to D130; the machine likely went idle). Confirmed via `redis-cli ping`.

**Finding — the progress-visibility fix (D130 Part B) proved its value on its very first real
use:** `progress.jsonl` showed 7 failed PDFs within under 2 minutes of run start, live, from
outside the process. Before this fix, this same failure would only have been discovered after
the run either finished or was killed blind — as happened with the original 6+ hour D130
incident. Caught, diagnosed, and Redis restarted in well under 5 minutes.

**Action:** Redis restarted (`redis-server --daemonize yes`, confirmed `PONG`), run restarted
fresh immediately after — see next entry.

---

### 2026-08-21 — D130 fix: real chapter structure + progress visibility, build + verify
**Method:** two parallel, independently-scoped agents on disjoint files — Part A (fixture
chapter structure, `generate_eval_pdfs.py` + new test file) and Part B (progress visibility,
both eval runners + existing test file) — followed by independent re-verification of both,
not just trusting their own reports.

**Commands:** `python -m tests.fixtures.generate_eval_pdfs` (regenerate all 20 real fixtures) ·
manual `detect_chapters()` re-check against the actual regenerated files (not the agent's claim)
· `pytest tests/unit -q` (full regression) · `ruff check`/`ruff format --check` on every touched
file.

**Results:**
- Regenerated all 20 real fixtures cleanly.
- Independently re-ran chapter detection against the real files: `long_100page` → 3 chapters
  (heading rung), `long_150/250/400page` → 4/7/10 chapters (toc rung), every chapter now 40
  pages — exactly matching the implementing agent's own report, confirmed independently rather
  than trusted.
- Full `tests/unit` regression: **1250 passed, 9 skipped** (1245 prior baseline + 5 net-new),
  zero regressions.
- `ruff check`/`ruff format --check` clean on all 5 touched files.

**Findings:**
- D130 fixed: the 4 "long" fixtures now carry real PDF outline entries every 40 pages with
  distinct, deterministic chapter titles (identical repeated titles get merged/deduped by the
  real detector — confirmed in testing — so a rotating title list was required, not one string).
- Bonus, found in the same pass: `creation_date` defaulting to `datetime.now()` silently broke
  the generator's own "byte-identical two runs" promise for every fixture (only visible on the
  slow "long" builders, which routinely take over a second to build) — now pinned to a fixed
  constant, verified byte-identical via SHA-256 across two separate process invocations.
- Second gap fixed: both eval runners (`runner.py`'s `run_all_evals`, `real_world_runner.py`'s
  `run_all_real_world_evals`) now write a real-time, per-run-truncated `progress.jsonl` — the
  exact fix for the "6+ hour run, zero visibility" problem experienced firsthand this week.
- **Not yet done:** the fix has not been re-verified against a real live `--run-live-eval`
  attempt — that's the next real confirmation this fix actually resolves the multi-hour stall,
  not just the chapter-count math in isolation.
- Part C (the same root mechanism as a real-student risk, not just an eval-harness one) was
  deliberately registered separately (`D131`) rather than folded into this fix — a product/UX
  decision, not a test-fixture change.

---

### 2026-08-21 — 20-PDF S3-1 live eval: attempted, stopped after 6+ hours, root cause found
**Command:** `pytest tests/evals/test_live_run.py -v --run-live-eval`
**Result:** Stopped intentionally after **6 hours 8 minutes**, no result written (this test only
writes output after all 20 PDFs finish). Real spend on whatever completed before stopping is
unmeasured — the same blind spot named when this test was first flagged.

**Health check before stopping (so "stopped" isn't confused with "crashed"):** process CPU time
and memory were confirmed still climbing across every check throughout the 6+ hours (37s → 50s →
1m04s → 1m10s → 2m11s → 2m31s → 2m46s → 2m49s → 2m51s CPU; memory 73MB → 331MB), which rules out
a hang or deadlock — a genuinely stuck process would show flat, unchanging CPU forever. No
orphaned child processes. System uptime confirmed no power/reboot interruption (6+ days
continuous). It was doing real work, just far slower than estimated.

**Root-cause investigation (zero cost — pure local function, no PDF/DB/network):** ran the
chapter-detection function directly against all 20 local fixture PDFs. Result: **every single
one resolves to exactly 1 chapter spanning the entire document.** None of the 20 carry a real
PDF table of contents or detectable heading structure, so all 20 fall through to the detector's
last-resort "whole document is one chapter" rule. For the 4 "long" fixtures (100/150/250/400
pages), that means the system generates one chapter of up to 400 pages — instead of the
~40-page chapter the whole pipeline's ~5-15 min/lesson timing assumption was built around.

**Findings:**
- This is the real, now-proven explanation for the multi-hour runtime — not a bug introduced
  this session, a pre-existing gap in how the original 20 test fixtures were built (they were
  never given realistic chapter markers). → **Gap #9 / D130 opened.**
- A second, smaller gap surfaced in the same investigation: this test prints zero progress while
  running — no way to tell from the outside how many of the 20 are done without instrumenting it
  externally. Named in D130's registration, not separately numbered.
- **Recommendation before the next attempt:** either fix the fixture generator to give the 4
  "long" PDFs detectable chapter structure (so they resolve to several realistic ~40-page
  chapters instead of one giant one), or accept the longer runtime and run it unattended
  overnight with progress logging added first.

---

### 2026-08-21 — D128 fix: OCR confidence check, build + unit-test
**Commands:** edited `extract_subprocess.py` (`_ocr_page_text`, `extract_pdf`) + `graph.py`
(`extract_node`'s checkpoint) · `pytest tests/unit/test_extract_subprocess.py
tests/unit/test_extract_node.py tests/unit/test_real_world_extraction.py -v` · `ruff check` /
`ruff format --check` / `mypy` on every touched file · full `pytest tests/unit -q`

**Results:**
- Targeted files: 58 + 16 passed (extraction/node checkpoint tests), 6 of them net-new.
- Full `tests/unit` regression: **1245 passed, 9 skipped** (1239 prior baseline + these 6),
  zero regressions.
- `ruff check`/`ruff format` clean on every touched file. `mypy`: only the same 3 pre-existing,
  unrelated `openai.py` provider errors — nothing new.

**Findings:**
- The fix works as designed: the exact fixture that proved D128 (`real_scan_like_rotated`) now
  flags all 3 of its pages; the companion upright fixture (`real_scan_like`) flags zero — the
  check discriminates real content from garbage rather than flagging indiscriminately.
- **This run does NOT re-verify the fix live.** The 2026-08-21 live confirmation logged above
  (in the real-world eval run entry) was captured BEFORE this fix existed — it proves the bug,
  not the fix. Whether the flag actually lands correctly in `lesson_jobs.node_outputs` on a real
  live run remains unit/mock-level verified only, deliberately not re-spent to confirm today
  (see Gap #1's Open Gaps entry). → **Candidate for the next live run, when one is next run
  anyway rather than as a dedicated re-spend.**
- `docs/DEFECT-REGISTER.md`'s D128 entry closed with full fix + test detail.

---

### 2026-08-21 — Real-world PDF eval tier, LIVE run against real providers
**Command:** `pytest tests/evals/test_live_run_real_world.py -v --run-live-eval`
**Result:** `1 passed in 731.73s (12m11s)`

First time this pipeline has ever completed a real end-to-end run against real
OpenAI/Sarvam/Supabase. Real spend: **$0.8296 total**, under the ~$1-1.30/lesson estimate.

| Fixture | Valid? | slide_quality | quiz_relevance | Cost | Time | Note |
|---|---|---|---|---|---|---|
| `real_scan_like` | ✅ | 1.0 | 1.0 | $0.4791 | 419.6s | Genuine OCR recovery, real content |
| `real_scan_like_rotated` | ✅ | **1.0** | **1.0** | $0.3505 | 294.0s | **Content is OCR gibberish — see Gap #1** |
| `real_corrupted_truncated` | ❌ (expected) | — | — | $0 | 13.0s | Real `PdfiumError: Data format error` |
| `real_encrypted_locked` | ❌ (expected) | — | — | $0 | 1.0s | Real `PdfiumError: Incorrect password error` |

**Findings:**
- Confirms the pipeline's happy path genuinely works end to end against real providers — the
  first time this has ever been observed, not just claimed.
- Confirms Gap #1 (D128) is not theoretical: a garbage-content lesson got a perfect quality
  score and shipped. Severity raised Med → High in `docs/DEFECT-REGISTER.md`.
- Confirms the broken fixtures fail exactly as designed — for free, before any provider spend.
- Does **not** verify the 20-PDF S3-1 tier (Gap #3) — separate, still unrun.

---

### 2026-08-20 — Real-world PDF fixture build + cheap-tier tests
**Commands:**
`python -m tests.fixtures.generate_real_world_pdfs` · `pytest tests/unit/test_real_world_extraction.py -v` · `pytest tests/unit -q` (full regression)

**Results:**
- Fixture generation: 4/4 fixtures built from `d2l.pdf`, each manually verified to behave as
  intended (0 extractable text on the scan-like pair; real `PdfiumError`s on the broken pair).
- `test_real_world_extraction.py`: **6/6 passed** — real Tesseract/pdfium calls, no mocks.
- Full `tests/unit` regression: **1239 passed, 9 skipped** (1233 baseline + 6 new), zero
  regressions.

**Findings:**
- OCR fallback genuinely recovers real text from an upright scan (confirmed against real
  content from `d2l.pdf`, not a synthetic stand-in).
- Rotated scan OCR is silent garbage — 96% mean confidence upright vs. 38% rotated on the
  identical source page. → **Gap #1 / D128 opened.**
- Corrupted and encrypted files both fail loud with an identifiable real error, not silently.

---

### 2026-08-20 — Real-world PDF coverage gap investigation (5 parallel agents)
**Method:** code investigation, no live spend — reading `generate_eval_pdfs.py`,
`extract_subprocess.py`, the repo root's existing PDFs, `docs/LESSON-DELIVERY-TRACKER.md` /
`docs/book-scale-phase-tracker.md`, and cost/timing data across the tracker + defect register.

**Findings:**
- The 20-PDF synthetic generator (`fpdf`-based) structurally cannot produce: a scanned page, a
  rotated scan, an encrypted file, a corrupted file, non-English text, a multi-column layout,
  blank/cover-heavy pages, tables spanning a page break, or fillable forms. → **Gap #6.**
- The OCR fallback path exists and works, but every existing test mocks the real Tesseract call
  out — nothing in the repo had ever run it against real scanned pixels before this session.
- No OCR confidence check exists anywhere — later confirmed as Gap #1 / D128.
- Encrypted PDFs: initially assessed as "zero handling anywhere" — corrected on direct testing
  (see below): it fails loud via the subprocess exit-code path, just with a raw traceback
  instead of a clean message. → **Gap #5.**
- Two real books already exist in the repo: `d2l.pdf` (tracked, CC BY-SA 4.0 — usable) and
  `EvadingEDR.pdf` (untracked, commercial No Starch Press book — deliberately never used as
  fixture source content, copyright).
- "L1" (referenced in the S3-1 story as covering "exhaustive scale testing") is **not** a
  diversity/scale-testing initiative — it's a single acceptance run of one real book. Real-world
  PDF diversity has no owner anywhere in the project.
- Cost basis for planning: ~$1-1.30/lesson, 5-15 min/lesson measured from real prior runs — a
  real-world tier must be manual/pre-release only, not per-PR/nightly.

**Direct verification (same session, before building anything):**
- Built a real encrypted PDF (`fpdf2.set_encryption()`), ran it through the real extraction
  subprocess: confirmed exit code 1, real traceback ending in
  `PDFium: Incorrect password error` — fails loud, not silently, not an unhandled worker crash.

---

### 2026-08-20 — Sprint 3 completion audit (5 tasks, multi-agent investigate + adversarial verify)
**Method:** 5 independent investigations (S3-1 through S3-5) reading real code and running real
`pytest` suites, each followed by an adversarial second pass trying to break the first verdict.
One second-pass agent (S3-3's) failed to return a valid result after 5 retries — its first-pass
finding stands unconfirmed by a second pass.

**Results per task:**

| Task | Verdict | Real tests run |
|---|---|---|
| S3-1 Eval harness (20 PDFs) | **OVERCLAIMED** | `test_eval_runner.py` + friends: 66 passed, 5 skipped. Full repo: 2253 passed, 26 failed (unrelated), 170 errors (unrelated) |
| S3-2 Prompt iteration | **PARTIAL** | `test_slide_generator_node.py`: 30 passed. Regression set: 147 passed |
| S3-3 Circuit breaker | DONE, untested live *(unconfirmed second pass)* | 114 passed (`test_retry`, `test_breaker_accounting`, `test_provider_tracing_resilience`, `test_image_providers`, `test_tts_providers`) |
| S3-4 Admin panel | DONE, untested live | `test_admin_router.py`: 41 passed. Full unit: 1233 passed, 9 skipped |
| S3-5 Langfuse cost attribution | DONE, untested live | 51 passed (3 dedicated files). Full unit: 1233 passed. Full integration: 21 passed, 78 skipped |

**Findings:**
- S3-1's tracker claim ("done, blocked only on Sarvam credits") was materially wrong — a real
  defect (`D124`, chapter_id incompatibility) crashed all 20 PDFs for a reason unrelated to
  Sarvam, closed 5 days after the tracker's "done" date but never disclosed in the tracker text.
  A second live blocker was found and fixed this session (`D126`, credential shadowing). →
  **Gap #3.**
- S3-2 genuinely blocked on S3-1 (Gap #4) — no before/after real scores can exist until the
  harness actually runs once.
- S3-3, S3-4, S3-5 are all real, substantively tested code — the gap in each is specifically
  "never exercised against a real external dependency," not "doesn't work." → **Gaps #7, #8.**
- S3-4's admin panel has zero frontend UI despite the sprint goal line naming "admin panel
  live." → **Gap #7.**
- A stale defect-ID reference found in S3-4: both the tracker and `router.py`'s code comments
  cite "D109" for a real concurrent-retry race; the register shows this was renumbered to D113
  on a merge collision. The underlying race is real and still open — just mislabeled everywhere
  it's cited.
