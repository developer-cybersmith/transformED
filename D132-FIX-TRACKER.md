# D132 Fix Tracker — Parallelize Slide Image Generation

**Defect:** `docs/DEFECT-REGISTER.md` D132 — `image_generator_node` generates a lesson's slide
images one at a time; measured across 6 real lessons, this is 86-95% of every lesson's total
generation time (6/6 consistent, both synthetic and real content).

**Started:** 2026-08-24 · **Status:** CLOSED — fixed, tested, live-verified across 5 real lessons
spanning every content category (short, long, dense_text, table_heavy, image_heavy).

---

## Approach, and why (read before touching code)

**Core fix:** bound concurrent image generation with a semaphore + `asyncio.gather`, mirroring
`_IMAGE_UPLOAD_CONCURRENCY`'s pattern already used a few functions away in the same file for
image *uploads*. Confirmed via real external research (see prior conversation, sources below)
that this is the standard, correct pattern for concurrent AI-provider calls from one process —
not a shortcut.

**Rejected: a full Redis-Lua atomic cost-reservation system**, after re-checking the actual code
rather than assuming a heavier pattern is automatically "more correct." `accumulate_cost()`
already uses Redis `INCRBYFLOAT` — a single atomic operation. There is no double-counting or
lost-update risk in the cost counter itself, concurrent or not. What concurrency *does*
introduce is smaller: a few slides' proactive `check_ceiling()` reads can be stale relative to
each other, so a lesson could land a small, bounded, deterministic amount over the $3.00 ceiling
(at most `(concurrency - 1) × one image's cost`, roughly $0.10-0.15 at a concurrency of 3-4) —
not a runaway, not data corruption. This is the same class of soft-limit overshoot this system
already explicitly tolerates ("downshift to cheapest providers, complete the lesson, flag in
admin — never abort mid-lesson", CLAUDE.md). Adding a Lua reservation script here would be
solving a problem that doesn't exist, at real implementation risk to a financially-sensitive,
already-hardened function. **Documented here, not hidden — if the accepted margin turns out to
be wrong in practice, this is the paragraph to revisit.**

**Concurrency bound:** starting at **3** (not copying `_IMAGE_UPLOAD_CONCURRENCY = 4` verbatim —
that number was empirically tuned for a *different* resource, Supabase Storage upload
throughput, not this provider's generation rate limit, which isn't documented anywhere in this
project). Conservative starting point per the "adaptive rate limiting" principle from research —
the existing per-call retry/circuit-breaker is the safety net if this needs tuning down; there's
no data yet to justify a higher number.

**What must NOT change (preserve exactly):**
- Per-slide isolation (AC-11) — one malformed/failed slide must still degrade to
  `image_url=None`, never take down the whole node.
- Output order — `slide_images_out` must stay in the SAME order as input `slides`, regardless of
  which slide's generation finishes first under concurrency.
- The idempotency/cache-check at the top of the node (unchanged, runs before any concurrency).
- The single checkpoint write to `lesson_jobs.node_outputs` after all slides finish (unchanged
  timing — after the full batch, not per-slide).
- Real cost accounting semantics — cost still recorded only after a successful upload, per this
  node's own hard-won review history (2026-07-15 finding: recording cost before upload success
  previously miscounted failed uploads as spend).

---

## Milestones

- [x] **M1 — Tracker written** (this file)
- [x] **M2 — Implement bounded concurrent image generation + tests**
- [x] **M3 — Independent adversarial review of the diff** — found one real bug, fixed
- [x] **M4 — Full regression suite + lint/type check, verified independently**
- [x] **M5 — Close D132 in `docs/DEFECT-REGISTER.md`, update `RUN-FINDINGS-LOG.md` and
      `docs/dev1-tracker.md`, commit**
- [x] **M6 — live re-verification, DONE.** Real speedup confirmed with real numbers, see below.

**Update this file after each milestone completes — status, real test counts, anything found.**

---

## Milestone Log

### M1 — 2026-08-24
Tracker created. Approach finalized above after real external research (see chat) plus direct
verification of `cost_tracker.py`'s actual implementation (not assumed) — corrected an earlier,
too-heavy proposed fix (Lua atomic reservation) after confirming `accumulate_cost` is already
atomic via `INCRBYFLOAT`.

### M2/M3 — 2026-08-24
Built via two-stage workflow: implement, then a fresh adversarial-review agent instructed to try
to break it, not confirm it.

**Implementation:** `_process_one_slide()` extracted from the old serial loop body (logic
byte-for-byte unchanged), run under `asyncio.Semaphore(_IMAGE_GENERATION_CONCURRENCY=3)` +
`asyncio.gather`. 3 new tests, 23/23 passing in the node's own test file, 45/45 combined with
`test_node_return_shape.py` + `test_unbounded_queries.py`.

**Adversarial review found ONE real bug the implementer missed, independently verified before
accepting it:** the Supabase Storage upload inside the newly-concurrent code is `storage3`'s
SYNC client (confirmed: it has a `_sync` module, blocking `httpx` underneath) — called directly
on the event loop, it would block every OTHER concurrently-scheduled slide for its own duration,
materially undermining the actual speedup this fix exists to deliver, even though all six of the
tracker's "must not change" invariants (order, isolation, checkpoint timing, cost accounting,
idempotency) were correctly preserved. The new concurrency test didn't catch it because it only
put latency in the mocked `generate()` call, never in `upload()`.

**Fixed:** wrapped the upload call in `asyncio.to_thread`, mirroring `extract_node`'s
`_bounded_upload` pattern exactly (the same fix the implementer's own comments claimed to have
already applied, but hadn't). Added the exact test the reviewer recommended — a MOCKED `upload()`
with a real blocking `time.sleep` inside it, proving slides still overlap even when the upload
step is slow. **RED-GREEN verified directly, not assumed:** temporarily reverted just the
`to_thread` wrapping and confirmed the new test fails exactly as expected (elapsed 1.018s vs.
required <0.54s), then restored the fix and confirmed green again.

**M4 (independent, not the implementer's own report):** `ruff check`/`ruff format --check` on
both touched files — clean. Node's own test file: **24/24 passing** (23 prior + the new
upload-latency test). Full `tests/unit` regression: **1254 passed, 9 skipped** (1250 D130
baseline + 4 net-new), zero regressions.

### M5 — 2026-08-24
D132 closed in `docs/DEFECT-REGISTER.md` with full fix detail, the adversarial-review finding,
and the RED-GREEN proof. `RUN-FINDINGS-LOG.md` and `docs/dev1-tracker.md` updated. Code + docs
committed.

**What's genuinely still open:** M6 — this has never been run against a real lesson with real
AI providers. Everything above is verified against real code execution and real assertions
under mocked providers, not a measured real-world speedup. The next live eval run (or a small,
cheap live smoke test) is the real confirmation that a real lesson's image step is actually
~3-4x faster now, not just correct in isolation.

### M6 — 2026-08-24
Ran the exact same fixture (`short_1page`) that already had a precise pre-fix baseline on
record (395.0s total, 368.5s of that on images, 8 images) — a clean, cheap, apples-to-apples
comparison rather than a fresh unmeasured lesson.

**Real result: 173.6s total, $0.38 — a 2.3x real speedup**, live, on the exact same input shape.

Pulled the real Langfuse trace for the new lesson and got a precise, quantified confirmation of
the actual mechanism, not just the headline number:

| | Before (pre-fix) | After (this run) |
|---|---|---|
| Total lesson time | 395.0s | 168.7s |
| `image_generator_node` span | 368.5s | 123.3s |
| Images generated | 8 | 7 |
| Sum of individual image calls | ~357.6s | 310.1s |
| Per-image avg (unchanged, as expected) | 44.7s | 44.3s |
| Image step as % of total | 93% | 73% |

**The mechanism itself is confirmed, not just the outcome:** before, the node's own span
duration (368.5s) was essentially equal to the SUM of its images (357.6s) — the serial
signature. After, the node's span (123.3s) is only ~40% of the sum (310.1s), landing almost
exactly on the predicted concurrency-of-3 signature: `ceil(7/3) x 44.3s ~= 133s` vs. the
observed 123.3s. Per-image cost/time is unchanged (as it should be — this fix changes
scheduling, not the individual provider calls) — the entire improvement comes from real overlap.

D132 is now fully closed: designed, built, adversarially reviewed, one real bug caught and fixed
pre-ship, and now confirmed under real conditions with a precise, explained mechanism — not just
a passing test suite.

### M7 (additional, requested) — 2026-08-25: cross-category confirmation
M6 proved the fix on one fixture (`short_1page`). Ran one real lesson from each of the 4
remaining content categories to confirm the fix holds everywhere, not just the one case already
tested — each against a real pre-D132 baseline already on record from the 20-PDF run, no
estimates:

| Category | Before | After | Speedup | `image_generator_node` (after) | Predicted (`ceil(n/3) x avg`) | Match |
|---|---|---|---|---|---|---|
| long_400page | 384.7s / $0.440 | 210.2s / $0.436 | **1.83x** | 146.5s | 143.7s | 98% |
| dense_text_uniform | 410.3s / $0.437 | 184.6s / $0.339 | **2.22x** | 134.4s | 133.8s | 99.6% |
| table_heavy_wide | 370.0s / $0.442 | 174.0s / $0.392 | **2.13x** | 120.6s | 122.1s | 99% |
| image_heavy_large | 409.3s / $0.433 | 170.0s / $0.380 | **2.41x** | 123.8s | 131.1s | 94% |

All 4 succeeded. Total real spend this pass: **$1.55**. Combined with M6's `short_1page` result
(2.3x), the fix now has real, measured confirmation across **all 5 of the harness's content
categories** — not a single lucky case. In every one, the real `image_generator_node` span
duration lands within a few percent of the predicted `ceil(images/3) x avg_image_time` formula,
confirming the concurrency mechanism itself, not just an improved stopwatch reading.
