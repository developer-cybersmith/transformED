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
| 3 | The official Sprint 3 eval harness — 20 synthetic PDFs — has **never actually been run live**, despite the tracker previously claiming it was "done, blocked only on Sarvam credits." Two other real blockers were hiding behind that claim (now fixed: `D124`, `D126`), but the run itself still hasn't happened. | Sprint 3 completion audit (2026-08-20) | Med (blocks S3-2 entirely, see #4) | **Open — next scheduled run, not yet executed** |
| 4 | Prompt tuning (S3-2) cannot be honestly completed — its own rule requires real before/after scores from the 20-PDF harness, which has never produced any (see #3). One prompt change (`D125`) already shipped, but tuned against a static scoring rule, not real data — doesn't satisfy the AC. | Sprint 3 completion audit (2026-08-20) | Med | Open — blocked on #3 |
| 5 | Encrypted PDFs fail with a raw Python traceback as the error message (`PDFium: Incorrect password error` inside a full stack trace), not a clean, identifiable "this file is password-protected" message. Confirmed: it does NOT crash the worker or silently pass — it fails loud via the subprocess exit-code path — but the message quality is poor. | Real-world PDF investigation (2026-08-20) | Low | Open — not registered as a `D-nn` yet |
| 6 | Non-English OCR, multi-column layouts, and fillable forms remain completely untested — the 4 real-world fixtures (`D127`) close scan/rotation/corruption/encryption, not these three. | Real-world PDF investigation (2026-08-20) | Low/Med (unknown — never measured) | Open — not registered, no fixtures exist yet |
| 7 | Admin panel (S3-4) is API-only — zero UI exists anywhere in `apps/web`. Satisfies S3-4's own written AC, but not the Sprint 3 goal line's "admin panel live." | Sprint 3 completion audit (2026-08-20) | Low (scope question, not a bug) | Open — needs a product decision, not a fix |
| 8 | Circuit breaker (S3-3) and Langfuse cost attribution (S3-5) are both code-complete and unit-tested, but neither has ever been exercised against a real dependency (real/fake Redis for the breaker; a real Langfuse dashboard for cost attribution — confirmed live 401 Unauthorized, no credentials configured for Langfuse specifically, despite other providers' credentials being present). | Sprint 3 completion audit (2026-08-20) | Low | Open |

---

## Closed Gaps

| # | Gap | Fixed in run | Fix summary |
|---|-----|--------------|-------------|
| 1 | Rotated/low-quality real scans OCR into silent, ungated garbage | 2026-08-21 — D128 fix build | `_ocr_page_text` now returns real Tesseract confidence alongside the text; below `_OCR_LOW_CONFIDENCE_THRESHOLD=60` the content is still accepted (never silently dropped) but the page is named in a new `low_confidence_ocr_pages` list, persisted on the `lesson_jobs` checkpoint the same way `tables_detected`/`docling_pages` already are. 10 new/updated tests, 1245/9 skipped full regression, zero regressions. **Still owes a live re-verification** — see Run Log entry. |

---

## Run Log

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
