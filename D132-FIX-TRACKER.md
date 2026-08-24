# D132 Fix Tracker — Parallelize Slide Image Generation

**Defect:** `docs/DEFECT-REGISTER.md` D132 — `image_generator_node` generates a lesson's slide
images one at a time; measured across 6 real lessons, this is 86-95% of every lesson's total
generation time (6/6 consistent, both synthetic and real content).

**Started:** 2026-08-24 · **Status:** In progress

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
- [ ] **M2 — Implement bounded concurrent image generation + tests**
- [ ] **M3 — Independent adversarial review of the diff** (fresh eyes, try to break it — order,
      isolation, checkpoint timing, no double-counting)
- [ ] **M4 — Full regression suite + lint/type check, verified independently**
- [ ] **M5 — Close D132 in `docs/DEFECT-REGISTER.md`, update `RUN-FINDINGS-LOG.md` and
      `docs/dev1-tracker.md`, commit**
- [ ] **M6 (optional, cost/time permitting)** — live re-verification: does a real lesson's image
      step actually run ~3-4x faster now?

**Update this file after each milestone completes — status, real test counts, anything found.**

---

## Milestone Log

### M1 — 2026-08-24
Tracker created. Approach finalized above after real external research (see chat) plus direct
verification of `cost_tracker.py`'s actual implementation (not assumed) — corrected an earlier,
too-heavy proposed fix (Lua atomic reservation) after confirming `accumulate_cost` is already
atomic via `INCRBYFLOAT`.
