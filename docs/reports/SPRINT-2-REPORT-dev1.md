# Sprint 2 Report — Chapter Generation Pipeline (Phase B)

**Project:** TransformED AI (HIE) · **Owner:** Dev 1 — Infra & Content Pipeline
**Sprint window:** Weeks 4–5 (Jul 3–16, 2026) · **Hardening & audit campaign:** Jul 17–30, 2026
**Report date:** 2026-07-30
**Verdict:** 🟡 **DELIVERED AND HARDENED — but not yet live-proven end to end**

---

## 1. The One-Paragraph Version (for anyone in a hurry)

Sprint 1 taught the system to *read* a book. Sprint 2 taught it to *teach* one. All 21 tasks
shipped: fifteen generation nodes that turn one chapter into a complete, schema-valid lesson —
slides, quizzes, narration, audio, images, glossary, intervention messages — assembled into a
single package the frontend can play. **All 21 tasks are merged to `main` and the whole
upload → generate → play path was independently confirmed real (not mocked) by two separate
multi-agent audits run by two different developers.** What Sprint 2 does **not** yet have is
Sprint 1's kind of evidence: **no lesson has ever been generated end to end against live AI
providers.** Everything is verified by 793 automated tests and line-by-line source audit. The
gap between those two things is the honest headline of this report — and it is exactly the gap
that, in Sprint 1, hid seven production-blocking bugs behind 87 green tests.

---

## 2. Executive Summary

1. **All 21 Sprint 2 tasks delivered and merged.** 15 generation nodes + fan-out orchestration,
   cost-ceiling enforcement, the `lesson_ready` push, and the 5-PDF eval harness.
2. **Two independent audits cross-confirmed the pipeline is real.** Dev 2's 14-agent Sprint 2
   completion audit (2026-07-29) and Dev 1's 13-agent frontend wiring audit (2026-07-30) both
   read the code on both ends. Dev 2's verdict on this pipeline: *"genuinely solid — every node,
   every endpoint, every page in that path was independently read and confirmed real, not mocked,
   not stubbed."*
3. **A 12-day hardening campaign found and fixed 22 defects, each now guarded by a test that
   fails if it returns.** Nine of them had *never worked for a single minute* — they were not
   regressions.
4. **The most expensive defect was a 16× content-duplication bug** that inflated real spend
   roughly 4×. It was reported from a live run by Dev 2, root-caused to a LangGraph state
   pattern repeated at 18 sites, fixed at all 18, and locked behind a source-level scan.
5. **CI could not pass at the start of this campaign and now can.** It had failed 60 consecutive
   runs and had never once reached a test step. The `apps/web` job had never executed at all —
   meaning the frontend had never produced a production build.
6. **What is still open is precisely scoped:** 14 registered defects, each with a named owner and
   a trigger. One blocks the student journey (`sessions` has no writer — fix written, in review).

---

## 3. Was Sprint 2 a Success? (the honest answer)

Three chapters, and the third is not finished.

**Chapter 1 — Build (Jul 3–17).** All 21 tasks coded, all 15 nodes real, tests green. On paper:
done. The tracker said `21/21 COMPLETE ✅`.

**Chapter 2 — Reality (Jul 27–29).** Dev 2 ran a real Refresher-tier lesson and reported **48
quiz questions for a segment that should have had 3**. That single observation unravelled a
16× duplication bug across 18 code sites, and *while fixing it* we found that Learner Mode's
tier had never reached the generation nodes at all — every Deep and Refresher lesson had been
silently producing Standard content. A structured root-cause analysis then established the
uncomfortable pattern: **9 of 11 pre-existing defects had never worked once.** The codebase was
not unstable; its verification had never confirmed anything worked.

**Chapter 3 — Proof (incomplete).** 22 defects are fixed and guarded. Two independent audits
confirm the seams line up. But **nobody has yet run a lesson through live AI providers.** The
5-PDF eval harness exists and has been attempted four times; all four attempts died before
reaching an AI call because no database or Redis was running. Until that run happens, "Sprint 2
works" is an inference from tests, not an observation.

**So: a genuine success on delivery and on hardening, with one honest asterisk on proof.**
Sprint 1 earned its ✅ by producing a real lesson ID and a real timing. Sprint 2 has not yet
earned that, and this report will not claim it.

---

## 4. Scope Delivered (tracker: 21/21)

### Phase 1 — Economy nodes (six, run in parallel per segment, on the cheap model)

| Task | Node | What it produces |
|------|------|------------------|
| S2-1 | `summarise_segment` | A compact summary per segment — the input Phase 2 consumes instead of raw chapter text (**5× token saving**) |
| S2-2 | `segment_complexity` | Difficulty scoring per segment |
| S2-3 | `quiz_generator` | Tier-banded multiple-choice questions per segment |
| S2-4 | `jargon_extractor` | Glossary terms for in-lesson tooltips |
| S2-5 | `intervention_messages` | Pre-generated nudges, so the live tutor never needs an AI call mid-lesson |
| S2-6 | `narration_generator` | The spoken script per segment |

### Phase 2 — Premium nodes (sequential, start only after all Phase 1 segments finish)

| Task | Node | What it produces |
|------|------|------------------|
| S2-7 | `lesson_planner` | The lesson outline — **built from Phase 1 summaries, never raw chapter text** |
| S2-8 | `slide_generator` | Slide content, budgeted by learner tier |

### Phase 3 — Media & assembly

| Task | Node | What it produces |
|------|------|------------------|
| S2-9 | `tts_node` | Narration audio (Sarvam → Azure → browser fallback chain; never hard-fails) |
| S2-10 | `image_generator` | Slide imagery |
| S2-11 | `package_builder` | The final schema-validated `LessonPackage` JSONB |

### Platform & delivery

| Task | Deliverable |
|------|-------------|
| S2-12 | `lesson_ready` push — ARQ worker → Redis pub/sub → WebSocket, plus the worker job itself |
| S2-13 | **$3.00/lesson cost ceiling** enforced at every AI call; breach aborts before overspend |
| S2-14 | 5-PDF eval harness — slide-quality and quiz-relevance scoring, results written to JSON |
| S2-15 | LLM provider factory — model-agnostic dispatch, so swapping models is an env-var change |
| S2-LM1–5 | **Learner Mode tier-aware generation** — see the separate Learner Mode report |

**Verified on `main` 2026-07-30:** 16 pipeline functions present (15 nodes + the Phase-1 fan-out).

---

## 5. Headline Results (and exactly how each is known)

| Result | Evidence | Class of proof |
|---|---|---|
| 21/21 tasks delivered, all merged to `main` | 16 node functions verified present in `pipeline/graph.py` | ✅ Direct source verification |
| Upload → generate → play path is real, not mocked | Dev 2's 14-agent audit + Dev 1's 13-agent audit, independently | ✅ Two independent audits |
| 793 gating tests pass | `pytest tests/unit tests/integration` | ✅ Executed |
| Full suite: 1,485 pass / 22 fail | The 22 are pre-existing, in Dev 3's (19) and Dev 4's (3) files | ✅ Executed |
| 22 defects fixed **and guarded** | `docs/DEFECT-REGISTER.md` — every entry names its guard | ✅ Executed |
| Lesson package is schema-valid three ways | Pydantic ↔ `lesson.ts` ↔ JSON Schema, cross-validated in test | ✅ Executed |
| Media arrives as 8-hour pre-signed URLs | Server-side signing verified; frontend signs nothing | ✅ Both ends read |
| Cost ceiling fires on unpriced models | Real arithmetic against a fake Redis, seeded at $2.999 | ✅ Executed |
| **A lesson generated against live AI providers** | — | ❌ **Never done** |
| **Actual cost per lesson** | — | ❌ **Never measured** |
| **Generation wall-clock time** | — | ❌ **Never measured** |

**The last three rows are the whole reason this report says 🟡 and not ✅.**

---

## 6. The Hardening Campaign — 22 defects, and why they matter

On 2026-07-28 Dev 2 reported a real symptom from a real run. The investigation that followed
changed how we understand this codebase.

### The finding that reframed everything

**9 of 11 pre-existing defects had never worked for a single minute.** Only 1 of 17 was a true
regression. Median time-to-discovery was 13 days — which measures *when a human read the code*,
not when anything detected anything.

The dominant cause, explaining **12 of 17** defects: **mocks are written by the consumer and
never reconciled with the producer.** The project's Week-1 rule *"each dev mocks the other's
interface"* was correct at the time and was never given an expiry date. **567 of 2,328 test
assertions (24%) describe a conversation with a mock rather than a real outcome.**

### The defects worth naming

| # | Defect | Consequence if shipped |
|---|---|---|
| 1 | **16× content duplication.** 18 nodes returned the whole accumulated state; six channels append rather than replace, so four nodes after the fan-in each doubled all six: 2⁴ = 16×, in one clean run with no retry | 48 quiz questions instead of 3; **real spend inflated ~4×** |
| 2 | **Learner Mode tier never reached the generation nodes** | Every Deep and Refresher lesson silently shipped Standard content while reporting success |
| 3 | **Zero OpenAI exceptions inherit from the HTTP library we were catching** | Every rate-limit (the most common transient failure) was permanently fatal — retry was decorative |
| 4 | The AI SDK's own retry ran *underneath* ours | 9 HTTP requests per logical call, two competing backoff schedules, 600-second timeouts |
| 5 | **An unpriced model switched the $3.00 ceiling off entirely** | Running the model-evaluation the roadmap mandates would have disabled cost control |
| 6 | An "AI validation" step in structure detection was **arithmetically dead** — 6,000-char prompt window vs a 90%-coverage acceptance test | We paid for a call on every upload and always discarded the result |
| 7 | Narration text was discarded on the audio-fallback path | Lessons shipped with silent, empty narration |
| 8 | **A Redis blip was a permanent pipeline failure** | A two-second infrastructure hiccup killed a 5–15 minute job that had already been paid for |
| 9 | An API key was recoverable from a "sanitized" error | Credential exposure in logs |
| 10 | A column name that does not exist was added to a query | `GET /lessons` would have failed for **every user on every request** |
| 11 | `lesson_ready` was routed by a key that could never match | The completion push reached no client (mitigated: the frontend polls) |
| 12 | The frontend had **never produced a production build** | Not deployable — invisible because the CI job that checks it had never run |

Each of the 22 is now closed with a guard: a test that fails if the defect returns. The
duplication bug's guard is a source-level scan that rejects the code pattern itself, not just
its symptom.

### Verification was itself verified

Because the campaign was about untrustworthy tests, **every fix was mutation-tested** — the fix
was deliberately broken to confirm the new test actually fails. This caught **four guards that
were green but proved nothing**, including one that watched a single method while the real
regression path sailed past it, and one that passed via an error path without ever exercising
the success path. All four were fixed. One review finding was **rejected with evidence** after
mutation testing showed the test it condemned was genuinely load-bearing.

---

## 7. Infrastructure Truths Uncovered (all now fixed)

These were not Sprint 2 features. They were discovered because someone finally looked.

- **CI had failed 60 consecutive runs and merges proceeded anyway.** It died at the lint step —
  step 5 of 9 — so it had **never reached a test step at all.** Lint, format and the entire web
  job are now green; type-checking is the last remaining gate (24 errors, Dev 3's 19 and
  Dev 4's 5).
- **The `apps/web` CI job had never executed on any commit** — a lockfile path assumed a
  per-app file in a shared-workspace repo. Consequence: `apps/web` had never produced a
  production build and was **never deployable**. Fixed; the job now passes end to end,
  including its 506 tests.
- **The `$3.00/lesson` ceiling was enforced but never measured.** The eval harness contained
  zero references to cost. A meter was built and tested; the number lands on the first live run.
- **Following the setup documentation broke every API call.** The frontend's config template
  omits a URL path segment the backend requires. A developer who configures nothing works; one
  who reads the docs gets a 404 on every request. Found 2026-07-30, registered, **not yet
  fixed** — Dev 1's.

---

## 8. Quality Process Executed

- **Story-first gate** on every hardening story: story committed alone, chronologically first,
  pushed before any implementation code. Verified per branch.
- **Adversarial multi-agent review** on each story. One round found that a shipped guard *could
  not catch its own stated hazard* — the check fired only for the tier the acceptance criterion
  was **not** written about.
- **Mutation testing on every fix** (see §6). 40+ mutants across the campaign; every survivor
  was investigated and each turned out to be a weakness in the test, not the code.
- **A binding defect register** (`docs/DEFECT-REGISTER.md`) where every entry must name its
  enforcement — a test, a CI gate, or the word `DISCIPLINE`. That last label is deliberate: it
  means *nothing stops us breaking this*, and its count is the honest fragility measure.
- **Seven binding engineering rules** added to the project guide, each derived from a specific
  defect. The load-bearing one: *no test may assert only on a mock it constructed.*
- **Verification scope = CI scope.** Established after Dev 1 measured "no regression" against a
  narrow scope, merged, and put a broken test on `main` for an hour. Recorded as a defect
  against ourselves rather than quietly fixed.

---

## 9. Level of Completion — an honest scorecard

| Dimension | Status | Basis |
|---|---|---|
| **Tasks delivered** | **21/21 — 100%** | All merged to `main`, source-verified |
| **Code complete** | **100%** | 16 pipeline functions present and real |
| **Test-verified** | **100% of gating scope** | 793 pass, 0 fail |
| **Cross-audited** | **100% of the generate path** | Two independent multi-agent audits |
| **Defects closed with guards** | **22** | Register; each names its guard |
| **Live-proven end to end** | **0%** | ❌ No lesson ever generated against live providers |
| **Cost-verified against the $3.00 ceiling** | **0%** | ❌ Meter built 2026-07-30; never run |
| **Performance measured** | **0%** | ❌ No generation timing exists |
| **Student journey complete** | **Blocked** | `sessions` has no writer; fix in review |

**Overall: Sprint 2 is functionally complete and structurally hardened. It is not yet
operationally proven.** Those are different claims and the difference is one live run.

---

## 10. Known Limitations & Open Items (full disclosure)

**14 registered open defects**, each with a named owner and a trigger. Four are live in
production:

| ID | What | Owner |
|---|---|---|
| **D18** | Nothing creates a session row → quiz and teach-back return 404 for every student. **Fix written and in review** (PR #119); the frontend half is one line | Dev 3 review + Dev 2 |
| **D29** | DPDP consent audit row has no writer — required before any attention data is collected | Dev 3 |
| **D31** | Following the setup docs 404s every API call (§7) | **Dev 1** |
| **D35** | The player invents its own session id and nothing ever replaces it | Dev 2 |

**Dev 1's remaining items:** D31 (above), D32 (a defensive-skip that a docstring claims but the
code does not have — it can kill the final node after 100% of a lesson's spend), D33 (a poor
diagnostic on the same path), D37 (a database query pattern never executed against real
Postgres, only against mocks — and the same select list already caused one outage-class failure).

**Accepted with explicit triggers, not forgotten:** non-English tokenisation (trigger: the first
Indic-language lesson — measured Hindi at 1.06 chars/token against an assumed 4.0); the
chapter/subsection hierarchy inversion in structure detection (trigger: the Sprint 3 document-AI
migration); the advisory-not-gating CI test steps (trigger: the 22 pre-existing failures reach
zero).

**Unowned:** the frontend is on Next.js 16 while the project guide locks Next.js 14 — two major
versions of divergence in the file declared the source of truth. Nobody has been assigned this.

**Carried program risks (pre-existing, unchanged):** the API host has no India region and must
migrate before Sprint 3 real students; the DPDP consent audit table must be writable before any
attention data is captured.

---

## 11. The One Recommendation

**Run the 5-PDF live eval.** One command, roughly 75 minutes, real API spend:

```
pytest tests/evals/test_live_run.py -v --run-live-eval
```

It requires Redis, Supabase and live API keys reachable. It now reports per-lesson cost and
names any lesson that breaches the $3.00 ceiling.

This single action converts three ❌ rows in §9 into measured facts, and produces the first
honest answer to *"what does a lesson actually cost?"* — a number the business plan depends on
and that has never existed.

Sprint 1's report was credible because it had a lesson ID and a stopwatch. **Sprint 2 deserves
the same, and one run buys it.**

---

## 12. Sprint 3 Readiness

The pipeline Sprint 3 builds on is checkpointed, idempotent, cost-capped, observability-wired,
retry-correct, and guarded by 793 tests plus a defect register with real enforcement. Sprint 3's
attention monitoring and full tutor state machine consume a lesson package this sprint now
reliably produces.

Two hard prerequisites before real students:

1. **Region migration.** The current API host has no India region — a data-residency
   constraint, not a latency preference.
2. **DPDP consent audit table must be writable.** A boolean flag on the user record is
   insufficient; the audit row is required *before* any attention data is collected.

---

# Appendix A — Attribution

This report describes work by Dev 1 (infra and content pipeline). Two contributions by other
developers are load-bearing to its conclusions and are credited explicitly:

- **The Sprint 2 completion audit was performed by Dev 2**
  (`docs/sprint2-completion-audit-2026-07-29.md`). It was a cross-team, 14-agent, two-angle
  audit — every frontend page and every backend endpoint read in full, cross-referenced, then
  independently verified per developer, then adversarially re-challenged. **Its verdict on this
  pipeline is the strongest external evidence in this report:** *"The core content pipeline
  (Dev 1) and the upload → generate → play-lesson path (Dev 2 frontend + Dev 1 backend) are
  genuinely solid — every node, every endpoint, every page in that path was independently read
  and confirmed real, not mocked, not stubbed."* That audit also produced two register entries
  (D29, D30) and independently reproduced D18 from scratch.
- **The 16× duplication bug was reported by Dev 2** from a live Refresher-tier run — a real
  observation that no test in the suite could have produced. It triggered the entire hardening
  campaign described in §6.

Dev 1's own frontend wiring audit (`docs/reports/frontend-wiring-audit-2026-07-30.md`,
13 agents) was run separately and reached compatible conclusions. **Two independent audits, by
two different developers, using different methods, agreeing** is the reason §5 can call the
generate path real without a live run.

---

# Appendix B — Evidence Ledger (traceability)

| Claim | Where to verify it |
|---|---|
| 21/21 tasks, per-task detail | `docs/dev1-tracker.md` |
| Every defect, its fix, and its guard | `docs/DEFECT-REGISTER.md` |
| Root-cause analysis (why the defects clustered) | `docs/DEFECT-REGISTER.md` Part 1 |
| Dev 2's cross-team completion audit | `docs/sprint2-completion-audit-2026-07-29.md` |
| Dev 1's route-by-route wiring audit | `docs/reports/frontend-wiring-audit-2026-07-30.md` |
| Binding engineering rules | `CLAUDE.md` → *Defect Register — READ BEFORE FIXING ANYTHING* |
| Individual stories (ACs, review findings, resolutions) | `docs/stories/2-3{1..8}-*.md` |
| Eval harness + cost meter | `apps/api/tests/evals/` |
| Cross-dev handoffs | `docs/handoffs/` |

**Suite at report date:** 793 gating pass · 1,485 full-suite pass · 22 pre-existing failures
(Dev 3: 19, Dev 4: 3) · lint clean · format clean · type-check 24 (not Dev 1's).
