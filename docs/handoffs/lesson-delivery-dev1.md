# Dev 1 — Lesson Delivery handoff

**Sprint goal:** one student, one complete lesson, generated from one real book.
**Your phases:** L0 (support) · **L1** · **L2** · L3 (with Dev 2)
**Master doc:** `docs/LESSON-DELIVERY-TRACKER.md` · **Run recipe:** `docs/book-scale-phase-7-run-recipe.md`

> **Naming, once.** This sprint is often called "video generation". What we build is the
> **narrated interactive lesson** — synchronised audio + slides + quiz + teach-back. That *is* the
> video-lecture experience. A compiled MP4 is re-watch-only and out of scope
> (`docs/decisionupdate.md` §7b). See the tracker §0.

---

## Your one-line status

The chapter-scoped pipeline is built and merged; **it has never run against real providers.** Media
nodes *did* run for real in Sprint 2 (pre-book-scale), so expect failures in the **book-scale
seams**, not in TTS itself.

---

## Deviations you own

| # | Intended | Actual | Where |
|---|---|---|---|
| **1** | Narration capped at **10,000 chars/lesson** across all segments | **No cap exists.** Only a per-section words/sec pacing guard, which cannot bound a per-lesson total | spec `docs/decisionupdate.md` §8:235-244 · absent from `config.py` and `narration_generator_node` (`graph.py:3061-3245`) |
| **2** | Slide changes aligned to **real audio** | `tts_node` ships `"timestamps": []` on **every** path — success `:3474`, exception `:3490`, fallback `:3836`. Timing is a **word-count × WPM estimate** | `graph.py:3746-3792` `_estimate_slide_timestamps` |
| **3** | A budget meeting variable input **errors or surfaces a degradation** | `_get_section_body` truncates at 6,000 chars with only `logger.warning` — nothing persisted, nothing surfaced. Called from **all six** Phase-1 nodes | `graph.py:1941-1960`; call sites 2147, 2424, 2684, 2796, 2969, 3125 |
| **4** | Signed media URLs survive a study session | Signed once at fetch, **no auto-refresh**. `/api/media/signed-url` exists with **zero frontend callers** | defined `modules/content/router.py:139`, used `:632`/`:639` |

**Deviation 3 is the one to feel bad about.** It is the exact pattern CLAUDE.md now bans and the
Scale Contract's Q2 headline example — and it is still live in the code the rule was written about.

---

## L1 — the acceptance run

**Do these before spending anything:**

1. **Check for stale processes.** Two stale `uvicorn`s and two stale ARQ workers cost more
   debugging time in book-scale than any code did. The port precedes `LISTENING` in Windows
   `netstat`, so the obvious regex never matches:
   ```
   netstat -ano | grep -E ":8077[[:space:]]" | grep LISTENING
   ```
2. **The beta-access gate is now in your path.** `infosec.intern3` gated upload/onboarding/teach-back
   behind an allowlist, and it already broke the book-scale upload tests once (**D61**, fixed).
   **Put your gate user on the allowlist before the run**, or L1 fails at the first request for a
   reason that has nothing to do with the pipeline.
3. **Land deviation 1 (the narration cap) first.** TTS is the largest cost line and it is currently
   unbounded against a $3.00/lesson ceiling. Capping after the run means paying twice.

**Then:** generate two chapters at two tiers, both under ~40 pages so `truncation_expected` is
false. Book `780efa51-67cb-4fea-bf4c-b4d6b4c0cfde` is already ingested (1,151 pages, 21 chapters);
ch 0 *Introduction* (29 p) and ch 5 *Builders' Guide* (26 p) are the safe picks.

**Verify like it matters:** download an MP3 and **play it**. A valid-but-silent file passes every
assertion we have. `test_tts_node.py` asserts `mock_sarvam.synthesize.return_value =
(b"AUDIO_BYTES", [])` — `b"AUDIO_BYTES"` is not audio.

**Record:** measured cost per lesson, wall-clock, per-node timings. That is the calibration baseline
this project has wanted since Sprint 1.

---

## Langfuse — check D62 before assuming it's credentials

Phase 7 logged `Failed to export span batch code: 401`. **D62 records a host mismatch:**
`.env.example:41` says `LANGFUSE_HOST=http://localhost:3010` (implying self-hosted) while
`config.py:87-88` defaults to `https://cloud.langfuse.com`. That is a plausible cause of the 401
and is cheaper to check than rotating keys.

Fix it **before** L1 — this run is the calibration baseline, and running it untraced wastes it.

---

## What you owe others

| To | What | When |
|---|---|---|
| **Dev 2** | A real `status='ready'` lesson id with working signed URLs | The moment L1 passes |
| **Dev 3** | The same lesson's real quiz + teach-back payloads | Same |
| **Dev 4** | A real session against that lesson, so `lesson_ready` can be observed | Same |
| **All** | The measured per-lesson cost, so CES/interventions can be budgeted | With the L1 result |

## What you're waiting on

**The user** — OpenAI credits. Nothing in L1 moves without it. **$0.00 has been spent so far.**

---

## Scale & Load (contract-mandated)

- **Unit of work:** one lesson = N segments (4–12 measured). Narration ~800–1,500 chars/segment.
- **Fixed budgets vs variable input:** 10,000 chars/lesson (unimplemented — deviation 1);
  6,000-char section body (deviation 3, silent). Both must error or surface, never truncate quietly.
- **Scope:** per lesson, per user.
- **Unbounded:** two remain, enumerated as **D59** — `admin/router.py:191` and
  `analytics/service.py:54`. Guarded by `tests/unit/test_unbounded_queries.py`; the list may only shrink.
- **Inherited caps:** the 6,000-char body was sized pre-book-scale. Re-derive it.
- **Concurrency:** generation is capped at 3 concurrent per user, and that check is a
  check-then-act with no lock (**D53** bounds it by staleness, does not close it).
