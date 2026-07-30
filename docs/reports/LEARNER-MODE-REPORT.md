# Learner Mode — Feature Report (cross-team)

**Project:** TransformED AI (HIE) · **Feature:** Learner Mode — tier-aware lesson generation
**Contributors:** Dev 1 (generation) · Dev 3 (assessment, reporting, Learner DNA) · Dev 2 (runtime/UI)
**Feature window:** Jul 13 – Jul 30, 2026
**Report date:** 2026-07-30
**Verdict:** ✅ **WORKING AND PROVEN — after a correction that matters**

---

## 1. The One-Paragraph Version (for anyone in a hurry)

Learner Mode lets one chapter produce three genuinely different lessons: **Deep** for first-time
mastery, **Standard** for normal study, **Refresher** for revision. A student picks depth, and
the system changes how many slides it writes, how many quiz questions it asks, and how the
content is framed. **The feature works today and is proven by tests that fail if it breaks.**
But it must be reported with a correction: Learner Mode was declared complete on **2026-07-22**,
and on **2026-07-28** we discovered it had **never actually worked** — the chosen tier never
reached the generation code, so *every* Deep and Refresher lesson silently produced Standard
content while reporting success. That defect is fixed, and it is now the most heavily guarded
part of the pipeline. **The feature is real as of 2026-07-28, not 2026-07-22.**

---

## 2. What Learner Mode Is (in plain terms)

One chapter. Three depths. The student chooses.

| Tier | Name | For | Slides per lesson | Quiz questions per segment |
|------|------|-----|------------------:|---------------------------:|
| **T1** | **Deep** | First-time mastery of hard material | **20–25** | **3–5** |
| **T2** | **Standard** | Normal study (the default) | **12–15** | **2–3** |
| **T3** | **Refresher** | Revision before an exam | **6–8** | **1–2** |

*(All six numbers verified directly from `pipeline/graph.py` on 2026-07-30, not from a document.)*

The tier does three things, not one:

1. **Budgets the slides** — a Refresher lesson is genuinely shorter, not a truncated Deep lesson.
2. **Bands the quiz** — depth of checking scales with depth of study.
3. **Reframes the prompt** — T1 and T3 carry explicit content-depth framing so the AI writes
   *differently*, rather than writing the same thing at a different length.

Downstream, the tier also travels into the student's **session report** ("this was a Refresher
lesson — 2 of 2 correct") so their score is read in the right context, and into the **Learner
DNA** profile that adapts over time.

---

## 3. ⚠️ Correcting the Record

**This section exists because the honest history matters more than a clean one.**

On **2026-07-22**, a Learner Mode audit (`docs/learner-mode-sprint-audit-report.md`, Dev 3)
concluded:

> **Verdict:** ✅ SPRINT COMPLETE — All goals achieved, all tests GREEN
> *Tier-aware quiz depth · T1: 3–5 Qs/segment · T2: 2–3 · T3: 1–2 · **Achieved? ✅ Yes***

Every test behind that verdict was green. The verdict was still wrong.

On **2026-07-28**, while fixing an unrelated duplication bug, we found that **the tier never
reached the six generation nodes that consume it.** The pipeline fans out to those nodes with an
explicit list of values to carry across; `tier` had been omitted from that list. Because the
fan-out *replaces* state rather than merging into it, all six nodes read the built-in default —
**Standard** — regardless of what the student actually chose.

**The production consequence:** every Deep lesson and every Refresher lesson generated before
2026-07-28 shipped Standard content, was marked complete, and reported success. Nothing in the
logs, the database, or the test suite said otherwise.

**Why the tests could not see it.** The tier logic itself was correct and unit-tested — the
functions that compute slide budgets and quiz bands worked perfectly when handed a tier. The
tests handed them one directly. **Nothing tested whether the pipeline ever actually did.** The
seam between "the tier is chosen" and "the tier is used" was the one thing not covered, and it
was the only thing that was broken.

This is the project's dominant defect pattern, which a root-cause analysis on 2026-07-29 found
explains **12 of 17** defects: *each side tested its own half against its own assumption, and
nothing reconciled them.*

**Neither the 2026-07-22 report nor its author was careless.** The claim was true of every
component and false of the whole. That distinction is the single most useful thing in this
document.

---

## 4. What Was Delivered

### Dev 1 — Generation side (the part that makes lessons actually differ)

| Task | Deliverable |
|------|-------------|
| **S2-LM1** | `tier` accepted on the upload API (`T1`/`T2`/`T3`), validated, defaulting to `T2`; invalid values rejected with a clear error |
| **S2-LM2** | `tier` persisted on the lesson record and threaded into the pipeline's working state |
| **S2-LM3** | **Slide budgets per tier** — 20–25 / 12–15 / 6–8, distributed across segments with a structural per-segment cap so a single-segment Deep chapter cannot overflow |
| **S2-LM4** | **Quiz bands per tier** — 3–5 / 2–3 / 1–2 per segment, enforced at generation and re-checked on cached reads |
| **S2-LM5** | **Tier-aware prompt framing** — the lesson outline is generated with explicit depth instructions for T1 and T3, so content differs in kind and not only in quantity |
| *(fix)* | **The D2 defect** — `tier` added to the fan-out payload; guarded (see §5) |
| *(fix)* | **Stale-cache tier stamping** — a checkpoint written before the fix cannot replay Standard content into a Deep lesson. The first attempt at this guard was itself found inadequate on review (see §6) |

### Dev 3 — Assessment & reporting side

| Deliverable | Effect |
|---|---|
| Tier context in the session report | `tier`, a human-readable tier label, question counts, accuracy label |
| Learner DNA snapshot in the report | Descriptive dimension labels + growth direction — **no raw numeric scores shown to students**, per the compliance rule |
| Re-assessment prompt | `reassessment_due` after every 10th session |
| Zero regressions in existing endpoints | Prior tests remained green |

### Dev 2 — Runtime & UI

| Story | Deliverable | Status |
|---|---|---|
| 4-19 | Learner tier at runtime; `tier` made optional in the shared contract | done |
| 4-20 | Tier-driven Q&A phase length | done |
| 4-21 | Tier over the WebSocket | done |
| — | Tier picker in the upload flow (Deep / Balanced / Refresher → T1/T2/T3) | done, verified wired |

---

## 5. How We Know It Works Now

The D2 fix is guarded three ways, and the guards were themselves attacked to prove they hold.

| Guard | What it proves |
|---|---|
| `test_fan_out_state_keys.py` (**11 tests**) | Every value the Phase-1 nodes read is present in the fan-out payload. **Deleting `"tier"` from the source makes this fail.** |
| `test_tier_differentiation_and_cost.py` (**2 tests**) | End-to-end: a Deep run and a Refresher run through the **real fan-out** produce genuinely different quiz counts. This is the test that would have caught D2 originally. |
| `test_pipeline_tier1.py` (**15 tests**) | Tier-1 budget and band arithmetic across edge cases |
| Cached-read tier stamp | A checkpoint from before the fix carries its tier explicitly, so stale Standard content cannot be replayed into a Deep lesson |

**All 28 tests pass on `main` as of 2026-07-30.**

**Mutation-verified, re-run on 2026-07-30 for this report.** The fix was deliberately re-broken
— `"tier"` deleted from `_FAN_OUT_STATE_KEYS` at `graph.py:4160`, restoring the exact D2 defect —
and **8 of the 28 tests failed**, by name:

```
test_tier_is_declared_in_fan_out_state_keys
test_fan_out_payload_carries_tier[T1] [T2] [T3]
test_tier_reaches_quiz_generator_through_the_fan_out[T1-3-5] [T3-1-2]
test_in_band_cache_is_still_reused_no_respend
test_tier_changes_the_delivered_package        <- the one that proves the product claim
```

This matters because the *original* Learner Mode tests were green while the feature was broken.
A guard that has not been attacked is only a claim.

*A note on method, because it nearly produced a false result.* The first attempt at this mutation
deleted the first `"tier",` occurrence anywhere in the file — which was **not** the fan-out entry
— and all tests passed, appearing to show the guards were worthless. Targeting the actual
declaration gave the result above. **An imprecise mutation produces a false "survived", which is
more dangerous than no mutation testing at all**, because it discredits a guard that works.

**Independently cross-audited.** Two separate multi-agent audits — **Dev 2's 14-agent Sprint 2
completion audit (2026-07-29)** and Dev 1's 13-agent frontend wiring audit (2026-07-30) — read
the tier path on both ends and confirmed the vocabulary matches end to end: the UI's
Deep/Balanced/Refresher maps to T1/T2/T3, the upload API accepts exactly those three and rejects
anything else, and the same closed set is used in generation.

---

## 6. What the Hardening Campaign Also Found in Learner Mode

Three further Learner Mode defects surfaced while fixing D2. Each is worth reading because each
was invisible to a green suite.

**1. The stale-cache guard could not catch its own stated hazard.** The first fix rejected a
cached quiz batch when its question count exceeded the tier's band. But every pre-fix checkpoint
was Standard-sized (2–3 questions) and Deep's upper limit is 5 — so **every stale cache passed
for exactly the Deep lessons the safeguard was written to protect.** It fired only for
Refresher. Redesigned to stamp the tier into the checkpoint itself: exact rather than inferred.

**2. A rejected cache plus one transient AI failure shipped a segment with zero questions** and
left the bad checkpoint in place, so each retry re-rejected and re-billed. A salvage path now
handles it.

*An earlier draft of this claim said the retry loop was unbounded. That was wrong — the cost
ceiling always terminated it. The claim was corrected on 2026-07-29 rather than left standing;
the fix stands on the zero-questions defect, which was always the stronger argument.*

**3. Cost figures for Learner Mode tiers are unreliable.** The 16× duplication bug inflated real
spend roughly 4×, so any "a Refresher lesson costs X" figure predating 2026-07-28 is wrong. A
cost meter was built on 2026-07-30; the real per-tier numbers land on the first live eval run.

---

## 7. Level of Completion — an honest scorecard

| Dimension | Status | Basis |
|---|---|---|
| **Tier accepted, validated, persisted** | ✅ **100%** | Source-verified; invalid tiers rejected |
| **Slide budgets differ by tier** | ✅ **100%** | Verified in code: 20–25 / 12–15 / 6–8 |
| **Quiz bands differ by tier** | ✅ **100%** | Verified in code: 3–5 / 2–3 / 1–2 |
| **Prompt framing differs by tier** | ✅ **100%** | T1 and T3 carry explicit depth framing |
| **Tier reaches the generation nodes** | ✅ **100% — fixed 2026-07-28** | Guarded by 28 tests, mutation-verified |
| **Tier in session report + Learner DNA** | ✅ **100%** | Dev 3; field-by-field cross-audited |
| **Tier picker in the UI, wired to the API** | ✅ **100%** | Both ends read in the wiring audit |
| **Stale-cache protection** | ✅ **100%** | Tier stamped in the checkpoint |
| **Proven against live AI providers** | ❌ **0%** | No tiered lesson has ever been generated live |
| **Per-tier cost measured** | ❌ **0%** | Meter built 2026-07-30; never run |
| **Perceived quality difference validated with a human** | ❌ **0%** | Nobody has read a Deep and a Refresher lesson side by side |

**Overall: Learner Mode is functionally complete and correctly wired end to end.** What remains
is not construction — it is confirmation that the three tiers *feel* different to a reader, which
is ultimately a judgement only a person can make.

---

## 8. The One Thing Left That Matters

**Generate the same chapter three times — once per tier — and read all three.**

The tests prove the *counts* differ (20–25 vs 12–15 vs 6–8 slides; 3–5 vs 2–3 vs 1–2 questions).
No test can prove a Deep lesson *teaches more deeply* than a Refresher one. That is the product
claim, and it needs a human to look.

The 5-PDF live eval harness is the vehicle:

```
pytest tests/evals/test_live_run.py -v --run-live-eval
```

It now also reports per-lesson cost, which would answer a second open question: **does a Deep
lesson fit inside the $3.00 ceiling?** The ceiling is enforced, but the headroom at T1 —
the most expensive tier — has never been measured.

---

## 9. Known Limitations (full disclosure)

- **Not live-proven.** Every claim in §5 rests on automated tests and source audit. No tiered
  lesson has been generated against live AI providers.
- **No per-tier cost data.** The $3.00 ceiling is enforced at every AI call, but T1 headroom is
  unmeasured. This is the tier most likely to approach the limit.
- **Non-English tiers are unsafe.** Content truncation assumes roughly 4 characters per token.
  Measured reality: English ≈ 6.0, **Hindi ≈ 1.06, Tamil ≈ 0.71**. A Hindi lesson would be
  truncated far more aggressively than intended. Deliberately deferred under an explicit
  English-only decision, registered, with the fix already specified — trigger: the first
  Indic-language lesson.
- **Tier is write-only in the lesson list.** It is stored and used but not returned by the
  list endpoint, so the dashboard cannot show which tier a past lesson used. Registered, low
  severity.
- **Structure detection ranks a chapter below its own subsections.** A pre-existing hierarchy
  inversion, pinned by a test so it cannot be fixed silently, deferred to the Sprint 3
  document-AI migration. It affects segmentation for all tiers equally.

---

## 10. The Lesson Worth Carrying Forward

Learner Mode is the clearest case study this project has produced.

**Every component was correct. Every test was green. The feature did not work.**

It failed at the one seam nobody tested — between choosing a tier and using it. It was found not
by a test but by **Dev 2 running a real lesson and noticing the numbers were wrong** — 48 quiz
questions where 3 were expected.

The response was to make that class of failure detectable rather than to fix the instance: the
end-to-end tier test now runs through the real fan-out, so the seam itself is covered; the guards
were mutation-tested so a green test is evidence and not decoration; and a binding rule was added
to the project guide — *no test may assert only on a mock it constructed.*

**Learner Mode now works, and — more importantly — we would know if it stopped.**

---

# Appendix A — Attribution

Learner Mode is a three-developer feature and this report covers all of it.

- **Dev 3** built the assessment and reporting half — tier context in session reports, the
  Learner DNA snapshot with descriptive-labels-only compliance, and the re-assessment prompt —
  and published the first Learner Mode audit (`docs/learner-mode-sprint-audit-report.md`,
  2026-07-22). §3 corrects that report's central verdict. **The correction is about a test-design
  blind spot shared by the whole team, not about the quality of that work**; every component it
  verified was in fact correct.
- **Dev 2** built the runtime and UI half (stories 4-19, 4-20, 4-21 and the tier picker) — and
  **reported the live symptom that led to discovering D2.** Dev 2 also performed the
  **14-agent cross-team Sprint 2 completion audit** (`docs/sprint2-completion-audit-2026-07-29.md`)
  that independently verified the Learner Mode tracker claims against actual code rather than
  against tracker files. **That audit is a primary evidence source for this report.**
- **Dev 1** built the generation half (S2-LM1–LM5), found and fixed D2, and built the guards in §5.

---

# Appendix B — Evidence Ledger

| Claim | Where to verify it |
|---|---|
| Tier bands (slides and quiz, all three tiers) | `apps/api/app/modules/content/pipeline/graph.py` — `_TIER_TOTAL_SLIDE_BAND`, `_TIER_QUIZ_COUNT_BAND` |
| Valid tiers and the default | `apps/api/app/schemas/lesson.py` — `VALID_TIERS`, `DEFAULT_TIER` |
| The D2 defect and its fix | `docs/DEFECT-REGISTER.md` → D2 |
| The three guards (28 tests) | `tests/unit/test_fan_out_state_keys.py`, `tests/integration/test_tier_differentiation_and_cost.py`, `tests/unit/test_pipeline_tier1.py` |
| Tier-aware generation story | `docs/stories/2-lm3-lm4-lm5-tier-aware-generation.md` |
| Learner Mode infrastructure story | `docs/stories/2-2-learner-mode-infra.md` |
| Dev 2's runtime/UI stories | `docs/stories/4-19-learner-tier-runtime.md`, `4-20-learner-qa-phase-length.md`, `4-21-learner-ws-tier.md` |
| Dev 3's original Learner Mode audit | `docs/learner-mode-sprint-audit-report.md` |
| Dev 2's cross-team completion audit | `docs/sprint2-completion-audit-2026-07-29.md` |
| Dev 1's route-by-route wiring audit | `docs/reports/frontend-wiring-audit-2026-07-30.md` |
| The stale-cache guard redesign | `docs/stories/2-31-narration-recovery-and-tier-cleanup.md` |
| Non-English tokenisation measurements | `docs/DEFECT-REGISTER.md` → D21 |
