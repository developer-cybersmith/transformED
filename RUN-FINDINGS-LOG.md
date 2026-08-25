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
| 11 | ~~The real, dominant reason lessons take so long: slide images generate ONE AT A TIME, not concurrently~~ | Langfuse trace analysis during the D130 live re-verification (2026-08-24) | High | **Fixed AND live-verified 2026-08-24 — `D132` CLOSED.** Real speedup confirmed against real providers: 395.0s -> 168.7s (2.3x) on the identical `short_1page` fixture. See Closed Gap #3. |
| 12 | **`slide_generator returned unknown segment_id(s)`** — 4 of 20 PDFs failed this way in the completed run (`dense_text_with_headers`, `table_heavy_small`, `image_heavy_small`, `image_heavy_grid`). **Root cause confirmed 2026-08-25 (D133), zero cost:** the LLM copies the real segment_id PERFECTLY every time, then appends `": <a better title it inferred from the summary>"` — because the prompt's own `segment_id={id}: {title} — {summary}` line format teaches it that a segment_id value looks like `"token: description"`. Only fires when the real id+title is generic/bare (`"Document"`, `"1.1 Subsection"`) — every other fixture's real headings are specific enough that the model has nothing to "improve." `lesson_planner_node` has the identical risky prompt shape but is protected by a retry loop already added for D77 (a related problem); `slide_generator_node` has no equivalent retry. | Live 20-PDF eval run, 2026-08-24 (final: 16/20 passed, 4/20 this same failure, $10.64 total, 2h40m) | High (4/20 real failures, mechanism confirmed to be generic LLM behavior, not fixture-specific) | **Root cause confirmed, fix planned — see `D133-FIX-TRACKER.md` / `D133` in `DEFECT-REGISTER.md`.** Fix: apply the same already-proven D77 retry pattern to `slide_generator_node`. Not yet built. |

---

## Closed Gaps

| # | Gap | Fixed in run | Fix summary |
|---|-----|--------------|-------------|
| 1 | Rotated/low-quality real scans OCR into silent, ungated garbage | 2026-08-21 — D128 fix build | `_ocr_page_text` now returns real Tesseract confidence alongside the text; below `_OCR_LOW_CONFIDENCE_THRESHOLD=60` the content is still accepted (never silently dropped) but the page is named in a new `low_confidence_ocr_pages` list, persisted on the `lesson_jobs` checkpoint the same way `tables_detected`/`docling_pages` already are. 10 new/updated tests, 1245/9 skipped full regression, zero regressions. **Still owes a live re-verification** — see Run Log entry. |
| 2 | The 20 eval-harness fixtures all resolved to 1 whole-document "chapter" (100-400 pages for the "long" ones, 2.5x-10x the normal ~40-page workload) — the real cause of the 6+ hour stalled run | 2026-08-21 — D130 fix build (2 parallel agents) | The 4 "long" fixtures now carry real PDF outline entries (`start_section()`) every 40 pages with distinct chapter titles — re-verified independently against the actual regenerated fixtures: 3/4/7/10 real chapters, every span now 40 pages, none of the old 40-400-page whole-document spans remain. Bonus fix in the same pass: a real non-determinism bug in `creation_date` that silently broke the generator's own "byte-identical two runs" promise. Also fixed the secondary opacity gap: both eval runners now write a real-time, truncated-per-run `progress.jsonl`. 5 new/updated tests, full regression **1250 passed, 9 skipped**, zero regressions. **Live-re-verified 2026-08-24**: all 4 long fixtures succeeded at ~$0.44/~6.5min each — matching normal lesson cost/time, not the multi-hour blowup the pre-fix behavior would have produced. |
| 3 | Slide images generated ONE AT A TIME — 86-95% of every lesson's total time, 6/6 real lessons measured | 2026-08-24 — D132 fix build (implement + adversarial review workflow) | `image_generator_node` now runs up to 3 slide images concurrently (`asyncio.Semaphore` + `asyncio.gather`), mirroring the proven `_IMAGE_UPLOAD_CONCURRENCY` pattern. Deliberately did NOT add a Redis-Lua atomic cost-reservation system after directly verifying `accumulate_cost()` already uses atomic `INCRBYFLOAT` — no data-corruption risk, only an already-tolerated small bounded overshoot possibility (documented in `D132-FIX-TRACKER.md`, not hidden). **Adversarial review caught a real bug before shipping:** the Storage upload inside the new concurrent code was still a blocking sync call, silently serializing every slide's upload window and undermining the actual speedup despite every correctness invariant (order, isolation, checkpoint timing, cost accounting) holding. Fixed with `asyncio.to_thread`, RED-GREEN verified directly (reverted the fix, confirmed the new test fails at 1.018s vs. required <0.54s; restored it, confirmed green). 4 new tests, 24/24 passing in the node's own file, full regression **1254 passed, 9 skipped**, zero regressions. **Live-re-verified 2026-08-24 (M6)**: identical `short_1page` fixture, 395.0s -> 168.7s total (2.3x real speedup), $0.38. Mechanism confirmed via real Langfuse trace, not just the headline number — `image_generator_node`'s span went from ~= SUM of its images (serial signature) to ~40% of the sum, landing almost exactly on the predicted concurrency-of-3 prediction. **Cross-category confirmation 2026-08-25 (M7)**: one real lesson from each of the 4 remaining categories, all against real pre-D132 baselines — `long_400page` 1.83x, `dense_text_uniform` 2.22x, `table_heavy_wide` 2.13x, `image_heavy_large` 2.41x, all 4 succeeded, $1.55 total spend. Every single one's real `image_generator_node` span landed within 1-6% of the predicted `ceil(images/3) x avg` formula — the fix is confirmed across all 5 content categories, not one lucky case. |

---

## Run Log

### 2026-08-25 — D132 M7: cross-category live verification (4 lessons, 1 per remaining category)
**Method:** direct `run_eval()` calls for one real fixture from each of the 4 content categories
not yet covered by M6 (`long`, `dense_text`, `table_heavy`, `image_heavy` — `short` already
confirmed) — each one a fixture that already had a precise pre-D132 baseline on record from the
completed 20-PDF run, giving 4 clean, real before/after comparisons in one pass rather than one.

**Result: all 4 succeeded, real speedups 1.83x-2.41x, $1.55 total real spend.**

| Category | Before | After | Speedup |
|---|---|---|---|
| long_400page | 384.7s / $0.440 | 210.2s / $0.436 | 1.83x |
| dense_text_uniform | 410.3s / $0.437 | 184.6s / $0.339 | 2.22x |
| table_heavy_wide | 370.0s / $0.442 | 174.0s / $0.392 | 2.13x |
| image_heavy_large | 409.3s / $0.433 | 170.0s / $0.380 | 2.41x |

**Mechanism re-confirmed per-category, not just the headline numbers:** pulled the real Langfuse
trace for each of the 4 new lessons and compared `image_generator_node`'s real span duration
against the predicted `ceil(n_images/3) x avg_image_time` formula:

| Category | Real span | Predicted | Match |
|---|---|---|---|
| long_400page | 146.5s | 143.7s | 98% |
| dense_text_uniform | 134.4s | 133.8s | 99.6% |
| table_heavy_wide | 120.6s | 122.1s | 99% |
| image_heavy_large | 123.8s | 131.1s | 94% |

**Findings:**
- D132's fix is now confirmed across all 5 of the harness's content categories (short, long,
  dense_text, table_heavy, image_heavy), not a single case — combined with M6's `short_1page`
  result, every category has real, measured, pre/post evidence.
- The concurrency mechanism itself (not just an improved stopwatch reading) holds precisely in
  every category tested — real span durations land within 1-6% of the theoretical
  `ceil(images/3) x avg` prediction across genuinely different content shapes (long documents,
  dense text, tables, image-heavy pages).
- All 4 sequential, matching this project's established (and still-unresolved) posture on
  cross-lesson concurrency (D129) — this run says nothing new about multiple lessons running at
  once, only that this one fix behaves consistently lesson to lesson.

---

### 2026-08-24 — D132 M6: live re-verification against real AI providers
**Command:** direct `run_eval()` call for a single fixture (`short_1page`), reusing the eval
harness's own library code rather than the full 20-PDF suite — cheap, targeted, and re-used a
fixture that already had a precise pre-fix baseline on record for a clean comparison.

**Result: 173.6s / $0.38, real, valid lesson.** Compared directly against the pre-fix baseline
for the identical fixture (395.0s / 8 images / 368.5s image-generation span):

| | Before | After |
|---|---|---|
| Total lesson time | 395.0s | 168.7s (2.3x faster) |
| `image_generator_node` span | 368.5s | 123.3s |
| Images | 8 | 7 |
| Sum of individual image calls | ~357.6s | 310.1s |
| Per-image avg | 44.7s | 44.3s (unchanged, as expected) |
| Image step as % of total | 93% | 73% |

**Findings:**
- The mechanism, not just the outcome, is confirmed: pre-fix the node span ~= sum of its
  images (serial signature); post-fix the span is only ~40% of the sum, landing almost exactly
  on the predicted `ceil(images/3) x avg` concurrency signature.
- Per-image cost/time is unchanged, exactly as the design intended — this fix changes
  scheduling only, not the individual provider calls.
- **D132 is now fully closed end to end**: designed with real external research, built,
  adversarially reviewed (catching one real bug pre-ship), RED-GREEN verified, and now
  live-confirmed with a precise, explained mechanism — not just a passing test suite.

---

### 2026-08-24 — D132 fix: bounded concurrent image generation, build + fix + verify
**Method:** two-stage workflow (implement, then a fresh adversarial-review agent instructed to
try to break the diff, not confirm it), followed by my own independent fix of what the review
found and my own independent full regression run — not trusted from either agent's own report.

**Implementation:** `image_generator_node`'s per-slide loop extracted into
`_process_one_slide()` (logic byte-for-byte unchanged) run under
`asyncio.Semaphore(_IMAGE_GENERATION_CONCURRENCY=3)` + `asyncio.gather`. 3 new tests, 23/23
passing in the node's own file.

**Adversarial review result: NEEDS FIXES — found one real bug, all six "must not change"
invariants otherwise held.** The Storage upload inside the new concurrent code is `storage3`'s
SYNC client (confirmed: has a `_sync` module, blocking `httpx` underneath) — called directly on
the event loop, it would block every OTHER concurrently-scheduled slide for its own duration,
silently undermining the actual speedup this fix exists to deliver. The new concurrency test
didn't catch it because it only put latency in the mocked `generate()` call, never `upload()`.

**Fixed directly (not delegated) after independently confirming the review's claim myself:**
wrapped the upload in `asyncio.to_thread`, mirroring `extract_node`'s own `_bounded_upload`
pattern. Added the exact test the reviewer recommended — mocked `upload()` with a real blocking
`time.sleep` inside it. **RED-GREEN verified directly:** temporarily reverted just the
`to_thread` wrapping, confirmed the new test fails exactly as predicted (elapsed 1.018s vs.
required <0.54s, real observed numbers not estimated), restored the fix, confirmed green again.

**Final verification (independent):** `ruff check`/`ruff format --check` clean. Node's own test
file: 24/24 passing. Full `tests/unit` regression: **1254 passed, 9 skipped** (1250 D130
baseline + 4 net-new), zero regressions.

**Findings:**
- D132 closed. The mechanism (bounded semaphore fan-out) is validated by real external research
  as the standard pattern for this exact scenario, not a shortcut — but a heavier Redis-Lua
  atomic reservation was deliberately NOT built after directly confirming `accumulate_cost()`
  already uses atomic `INCRBYFLOAT` — no data-corruption risk exists, only a small,
  already-tolerated bounded overshoot possibility, documented rather than hidden or over-engineered around.
- Real, concrete proof that a second independent pass (adversarial review) earns its cost: the
  first implementation was fully correct on every safety invariant and still would have shipped
  with the actual performance problem barely improved, invisibly, had the review not caught it.
- **Genuinely still open:** M6 — never run against a real lesson with real AI providers. The
  next live eval run is the real confirmation of an actual measured speedup, not just
  correctness under mocked providers.

---

### 2026-08-24 — 20-PDF S3-1 live eval: COMPLETED — 16/20, first time ever this far
**Command:** `pytest tests/evals/test_live_run.py -v --run-live-eval` (restarted after the
Redis-down abort earlier the same day)
**Result:** Ran to completion — **2h40m (9600s), real spend $10.64 total.** First time in this
project's history the S3-1 eval harness has completed anywhere near this far; every prior
attempt (this session and before) crashed instantly or was aborted before finishing.

| PDF | Valid? | Cost | Time |
|---|---|---|---|
| short_1page | ✅ | $0.43 | 6.6 min |
| short_3page | ✅ | $1.13 | 16.8 min |
| short_10page | ✅ | $1.75 | 24.7 min |
| short_sparse | ✅ | $1.73 | 24.8 min |
| long_100page | ✅ | $0.44 | 6.6 min |
| long_150page | ✅ | $0.44 | 6.3 min |
| long_250page | ✅ | $0.44 | 6.4 min |
| long_400page | ✅ | $0.44 | 6.4 min |
| dense_text_uniform | ✅ | $0.44 | 6.8 min |
| dense_text_long_paragraphs | ✅ | $0.44 | 6.4 min |
| dense_text_short_paragraphs | ✅ | $0.65 | 9.7 min |
| dense_text_with_headers | ❌ | $0.09 | 2.1 min |
| table_heavy_small | ❌ | $0.01 | 0.8 min |
| table_heavy_wide | ✅ | $0.44 | 6.2 min |
| table_heavy_tall | ✅ | $0.43 | 7.6 min |
| table_heavy_mixed | ✅ | $0.44 | 6.6 min |
| image_heavy_small | ❌ | $0.01 | 0.5 min |
| image_heavy_large | ✅ | $0.43 | 6.8 min |
| image_heavy_captioned | ✅ | $0.44 | 6.9 min |
| image_heavy_grid | ❌ | $0.01 | 0.6 min |

**16/20 valid, 4/20 failed — all 4 failures are the SAME error** (`slide_generator returned
unknown segment_id(s)`), unrelated to D130 or D132. See Open Gap #12 for the failure detail and
root-cause lead.

**Findings:**
- **D130 live-confirmed, definitively.** Every "long" fixture (100-400 pages) now costs and
  takes essentially the SAME as a tiny document (~$0.44, ~6.5 min) — not the multi-hour, would-be
  multi-dollar blowup the pre-fix whole-document fallback would have produced. This is the real
  confirmation the earlier "6+ hours, stopped before finishing" run could never provide.
- The literal S3-1 AC ("all 20 PDFs produce a valid LessonPackage") is NOT yet fully satisfied —
  16/20, not 20/20 — but this is by a wide margin the closest this project has ever come, and the
  gap has a real, identified, separately-tracked cause (Gap #12), not a mystery.
- D130's fix did not introduce any of the 4 new failures — none of the 4 failing fixtures were
  touched by that fix, and this is the first time any of them has ever run live at all.

---

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
