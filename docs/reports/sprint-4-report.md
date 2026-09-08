# Sprint 4 Report

**Sprint:** Weeks 8–9 (Load test + calibration + Razorpay + hardening)
**Report date:** 2026-09-07

---

## Story status

| # | Story | Status |
|---|-------|--------|
| S4-1 | Load test, 50 concurrent | Harness built and merged (#178). Clean run (#11) completed: 50/50 accepted, 48 ready / 2 failed terminal, zero crash-like errors. Report update PR #207 open, mergeable, awaiting review. |
| S4-2 | Pipeline reliability fixes | **Done, merged** (#193). All 9 checkable ACs closed. |
| S4-3 | Payment integration (Razorpay) | **Not merged.** PR #157 open, approved, ready to merge. |
| S4-4 | Rate limiting per route | **Done, merged.** |
| S4-5 | RLS security audit | **Done, merged.** |
| S4-6 | Fly.io backups + disaster recovery | **Not started.** No DR doc exists. |
| S4-7 | On-call runbook | Written, PR #208 open, mergeable, awaiting review. Independent teammate walkthrough/sign-off (AC 7) not yet done. |
| S4-8 | Image-fallback migration (D121) | **Done, merged** (#172). Gemini "Nano Banana" primary, GPT Image 2 fallback. |

**5 of 8 done. 2 written and mergeable, pending review. 1 (S4-6) not started.**

---

## Findings (this sprint window, D144–D164)

- **D145 — Fly region drift.** Live region list is `sin` (Singapore), not `bom` (Mumbai) as `fly.toml` declares. Registered, not fixed. DPDP/data-residency compliance gap.
- **D146 — 3-hour production outage.** `RATE_LIMIT_STORAGE_URL` missing as a live Fly secret after a deploy; guard behaved correctly, deploy checklist didn't. Fixed.
- **D147 — pypdfium2 version drift in the Docker image**, reintroducing a closed defect (D134) in production. Fixed-guarded.
- **D148/D149 — Sarvam TTS silently broken.** Request never pinned a `model` field; server-side default drifted to `bulbul:v3` (v2 deprecated). A second bug (v3 batches multiple inputs into one clip) would have re-broken narration even after the first fix. Both fixed.
- **D150/D151 — No deploy-time secret verification**, the actual root cause of D146. Verification script added and wired into CI (fixed). Two narrower gaps in that same script — verifies names only, no values; no lock against concurrent mutation — registered, not fixed.
- **D152/D153 — Load-test harness bugs**, found via runs #9/#10: (1) harness deleted disposable users while their real ARQ jobs were still running, destroying real in-flight, paid generation work (~$23.77 of run #10's spend); (2) 100% of large book uploads failed on a dropped TLS connection with zero retry protection. Both fixed (harness now waits for real terminal status via service-role API; upload wrapped in existing retry machinery).
- **D154 — No per-node timeout budget/observability.** Real load-test data (P50 20.6min / P95 25.2min per lesson) shows nothing breaks, but there is no signal for which node a slow lesson is in. Registered, not fixed — deferred to future monitoring work.
- **D157 — flyctl JSON shape mismatch** in D150's own deploy guard blocked 100% of production deploys. Fixed.
- **D158/D159 — Tutor Q&A real backend** shipped, replacing the "Ask Tutor" UI's mocked stub. Fixed.
- **D160 — Missing DB migration in production.** Every session-report page 500'd for ~2 days because a merged migration was never applied to the live Supabase project. Fixed live.
- **D161 — SSR/CSR locale hydration mismatch** on report pages. Fixed.
- **D162 — Upstash Redis at its hard request cap** (500,000/500,000). Registered, not fixed — deliberately deferred per explicit instruction.
- **D163 — Every lesson-start session-creation call returning 500** since Story 4-13 merged (two compounding bugs). Critical, fixed same day.
- **D164 — Ask-Tutor rate-limit Redis fallback failed open, not closed.** Fixed.

---

## Current metrics

- **Load test (run #11, 50 concurrent):** 50/50 Phase B requests accepted, 48 ready / 2 failed terminal (96%), 0 crash-like (5xx) errors, 0 Redis-connection errors. Completion duration — P50: 981.1s (16.4 min), P95: 1468.1s (24.5 min), max: 1481.6s.
- **Real spend, run #11:** $22.45 across 49 harvested lessons (~$0.46/lesson average), 440 images generated.
- **Test suite:** 1466 unit tests passing, 6 skipped, 0 regressions (latest full run).
- **Defect register:** 21 defects opened this sprint window (D144–D164); 15 fixed, 5 registered-not-fixed (D145, D151, D154, D162, plus D144 which is a dead-code removal, not a defect).
- **Open PRs (this author):** 3 — #207, #208, #209 — all mergeable, all blocked only on required review (branch protection; auto-merge is not enabled on this repo).

---

## Known gaps

- **D145** — Fly region is Singapore, not Mumbai as declared. Open DPDP/data-residency compliance item.
- **D151** — Deploy-secret verification checks names only, not values; no lock against concurrent mutation.
- **D154** — No per-node timeout/progress visibility during a pipeline run.
- **D162** — Upstash Redis at its request cap; reset cadence and blast radius on live traffic not yet characterized.
- **Register-ID collision on PR #209** — its D-number (originally D158, currently D164) collides with an unrelated defect merged to `main` while the PR was open. Needs renumbering before merge (same pattern as D152/D153/D158's own prior renumbering).
- **S4-3 (Razorpay)** — approved, not merged.
- **S4-6 (DR)** — not started at all.
- **S4-7 Task 5** — independent teammate sign-off not done; story not "done" until it is.

---

## Next steps

1. Get #207, #208, #209 reviewed and merged (currently the only blocker on all three).
2. Merge #157 (Razorpay) — approved and ready.
3. Renumber PR #209's colliding D-number before it merges.
4. Start S4-6 (Fly.io backups + DR test).
5. Complete S4-7's independent teammate walkthrough (AC 7).
6. Revisit D145 (region) and D162 (Upstash cap) before real-student launch — both are launch-blocking classes of gap, not deferred indefinitely.
