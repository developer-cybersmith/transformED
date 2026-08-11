# Dev 1 — Lesson Delivery Sprint Plan

**Date created:** 2026-08-11
**Owner:** Dev 1 (infra, content pipeline, all 11 nodes, embeddings, provider abstraction, Langfuse)
**Status:** in progress — Story 3-35 done, code review running on the next story's predecessor

> **This document is a readable index of a plan already recorded elsewhere. It is not a new
> source of truth.** `DEV1-FIX-PLAN.md` (2026-07-28) is on record in this same root directory as
> the cautionary case for prose plans: it was written, then deviated from four times in a single
> day, and every deviation was caught by review — none by a machine (`docs/DEFECT-REGISTER.md`
> Part 1). This plan does not repeat that risk, because it isn't the enforcement mechanism:
> - The **task list and its live status** live in the session's task tracker (`TaskList`), not here.
> - **Each story's actual state** lives in its own file under `docs/stories/`.
> - **Every defect closure** lives in `docs/DEFECT-REGISTER.md`.
> - **Dev 1's running log** lives in `docs/dev1-tracker.md`.
>
> If this file and any of those disagree, **they win, not this file** — update this file to match,
> not the other way around. This exists so a reader (human or agent) can pick up the sprint cold
> without re-deriving the plan from eight source documents.

---

## 1. Sprint goal

One real student completes one full lesson, generated from one real uploaded book, start to
finish — quiz at every segment, one teach-back, attention measured with consent, at least one
intervention that recovers. Source of truth: `docs/LESSON-DELIVERY-TRACKER.md`. Companion:
`docs/SCALE-CONTRACT.md` (binding on every story in this plan).

**What this is not:** a rewrite, a redesign, or a new feature. Every item below either makes an
already-decided architecture actually run once, or closes a defect already sitting in the
register with Dev 1's name on it.

## 2. Dev 1's scope within the sprint

| Phase / Item | What | Source |
|---|---|---|
| L0 | Not mine — the user unblocks spending (OpenAI credits) + fixes the Langfuse 401 | `docs/LESSON-DELIVERY-TRACKER.md` |
| L1 | The acceptance run: 2 real chapters × 2 tiers, real providers, measured cost/timing | `docs/handoffs/lesson-delivery-dev1.md` |
| L2 | Narration char cap, real audio-duration slide timing, surfaced truncation | same |
| L3 | Hand a real `lesson_id` + signed URLs to Dev 2/3/4 the moment L1 passes | same |
| Repo-wide defects | D31, D32, D33, D48, D53, D54, D59(a), D62 — all Dev-1-owned, found before or alongside this sprint | `docs/DEFECT-REGISTER.md` |

Everything else (L4–L8) belongs to Dev 2/3/4; this plan tracks only where Dev 1's output is a
dependency for them (see §5).

## 3. Process every story in this plan follows — no exceptions

This is CLAUDE.md's BMAD Pre-Implementation Checklist plus the Sprint Task Branch Rule, applied
literally to every item, including small defect fixes:

1. **Branch first**, before any file edit: `git checkout main && git checkout -b <branch>`,
   named `sprint{N}/s{N}-{M}-{slug}`.
2. **Story file first**: `docs/stories/{N}-{M}-{slug}.md`, full ACs, mandatory
   `## Scale & Load` section answering all six `docs/SCALE-CONTRACT.md` questions (a bare "N/A"
   is a missing answer — every N/A carries a reason).
3. **Commit the story alone.** No implementation code in that commit.
4. **Push, then verify** the story commit is chronologically first on the branch.
5. **RED** — write the failing tests, confirm they actually fail against current code by
   executing them (not by assuming). A test that passes before the fix isn't testing the defect.
6. **GREEN** — implement until the new tests pass, and re-run whatever existing suites the story
   promises not to regress, unmodified.
7. **6-layer adversarial review** before merge (`/bmad-code-review`): Blind Hunter, Edge Case
   Hunter, Acceptance Auditor, Scale & Load Hunter (the skill's 4 built-in layers) plus Story
   Quality, Test Coverage, AC Completeness, Process Integrity (supplied by the invoking prompt —
   not automatic). Scale & Load Hunter never skips.
8. **Close the loop**: update `docs/DEFECT-REGISTER.md` for every defect ID closed, update
   `docs/dev1-tracker.md` per its auto-update rule (checkbox/dashboard/date in the same response),
   commit, push, open a PR.

**Bundling rule for this sprint specifically:** several open defects are one-to-a-few-line fixes
sharing one root cause. Rather than one story file per defect ID, related trivial fixes are
bundled into a single story (e.g. Story 3-35 below bundles D31+D48+D62 — all three are
"documented/templated value disagrees with the code that runs, or exists with zero enforcement").
Substantive work (the acceptance run, the narration cap, the audio-timing fix, the
package_builder defensive-skip pair) each get their own story. This was an explicit choice, not a
default — see the conversation record for the reasoning.

## 4. The story list, in order, with current status

| # | Story | Bundles | Status | Branch |
|---|---|---|---|---|
| 1 | Story 3-35 — env/config correctness | D31 (High, live in prod) + D48 + D62 | **Done** — story-first, RED, GREEN, self-review complete; `/bmad-code-review` running now | `sprint3/s3-35-env-config-fixes` |
| 2 | package_builder defensive fixes | D32 + D33 | Not started | *(not yet created)* |
| 3 | L2a — narration char cap (10,000 chars/lesson) | — | Not started | *(not yet created)* |
| 4 | L2b — real audio-duration slide timing | — | Not started | *(not yet created)* |
| 5 | L2c — surface `_get_section_body`'s silent truncation | — | Not started | *(not yet created)* |
| 6 | L1 — the acceptance run | — | **Blocked on L0** (user's OpenAI credits) | *(not yet created)* |
| 7 | L3 support — hand off real `lesson_id` | — | Blocked on L1 | — |
| 8 | D53 — stale-`generating` lesson reaper | High, live in prod | Not started | *(not yet created)* |
| 9 | D54 — `?force=true` regeneration endpoint | Depends on D53 | Not started | *(not yet created)* |
| 10 | D59(a) — bound `admin/router.py:191` query | Low priority, trigger = S3-4 starting | Not started | *(not yet created)* |

Live status for this table is the session's task tracker, not this file — this table is a
snapshot as of 2026-08-11.

## 5. Ordering logic — why this order and not another

- **L2 before L1**: TTS dominates lesson cost; capping narration after the paid acceptance run
  means paying twice.
- **package_builder fixes (D32+D33) before L1**: both are crash risks in the *last* pipeline
  node, after 100% of the lesson's spend. Fixing them first protects the acceptance run's budget.
- **L1 blocked on L0**: nothing generates without the user adding OpenAI credits — tracked, not
  actionable by Dev 1.
- **L3 support is a hand-off, not a build**: the moment L1 produces a real `status='ready'`
  lesson, Dev 1 announces its id to Dev 2 (player verification), Dev 3 (quiz/teach-back
  payloads), and Dev 4 (`lesson_ready` observation) — this is Sync-C in
  `docs/LESSON-DELIVERY-TRACKER.md`'s interdependency map.
- **D53/D54/D59(a) are independent of the L-phases** and can slot in wherever there's a gap —
  D53 is High/live-in-prod so it shouldn't slip indefinitely, but nothing else blocks on it.

## 6. Cross-team dependencies Dev 1 does not control

- **SYNC-A** (Dev 3 + Dev 4): which CES formula implementation survives. Doesn't block Dev 1
  directly, but L1's real cost numbers feed the eventual CES-weight re-derivation.
- **SYNC-B** (Dev 2 + 3 + 4): attention-signal wire scale + `behavioral_score` definition. Blocks
  Dev 2's L6, which is on the critical path to L8 — not a Dev 1 blocker, tracked for awareness.
- **Dev 4's `INTERVENING` fix must land before Dev 2's MediaPipe work ships** — noted here only
  because Dev 1's L1 cost/timing numbers are an input to that conversation, not because Dev 1 owns
  either side of it.

## 7. What "done" means for this plan

Same gate as `docs/LESSON-DELIVERY-TRACKER.md`'s own rule: a phase or story is done when it has
been **observed working**, with real numbers or a real green test run recorded in its own story
file — never "should work," never a green suite alone. This plan is complete when every row in
§4 is `Done` and L1's observed result is written into `docs/LESSON-DELIVERY-TRACKER.md`.
