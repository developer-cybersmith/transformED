---
id: "3-35"
title: "Env/Config Correctness — Langfuse Host, API URL Prefix, Dead Spend-Cap Config"
status: "ready-for-dev"
sprint: 3
story_points: 2
baseline_commit: ""
owner: Dev1
priority: P1
blocker_ref: "D31, D48, D62"
---

# Story 3-35 — Env/Config Correctness (D31 + D48 + D62)

## Context & Scope Boundary

**Why this story exists:** three small, independently-registered defects share one root
cause — a documented/templated config value disagrees with the code that actually runs, or
a documented config value has no code behind it at all. `docs/DEFECT-REGISTER.md` already
names all three with owner Dev 1. Bundling them into one story is a deliberate exception to
"one story per unit of work": each fix is a one-to-a-few-line change, and three separate
story-first commits for that would be process overhead the CLAUDE.md checklist doesn't
intend. (Compare: substantive fixes in this sprint — the narration cap, the audio-timing
fix, the package_builder defensive-skip pair — each get their own story.)

**What this story does:**
1. **D62** — correct `.env.example`'s `LANGFUSE_HOST` template value to match the code
   default (Langfuse Cloud, not self-hosted).
2. **D31** — correct `NEXT_PUBLIC_API_URL` to include the `/api` segment everywhere it's
   documented, and add an executable test so this can never silently regress again.
3. **D48** — remove `max_daily_spend_per_user_usd`: dead config that looks like a real
   spend control but has zero enforcing call sites.

**What this story does NOT do:**
- Does not implement a new daily-spend enforcement mechanism. D48's register row offers two
  options (implement or delete); this story takes the delete path because building a new
  Redis-backed spend control is a distinct, larger unit of work with its own Scale & Load
  answers. If daily-spend limiting is still wanted, that is a fresh, separately-scoped story.
- Does not touch the frontend's already-correct fallback in `apps/web/src/lib/api.ts:4` —
  that value is right today; this story fixes the *documentation and CI config* that
  disagree with it.
- Does not touch Langfuse credentials/auth — D62 is a host-value bug, not a 401 auth bug
  (those are separate; a 401 with the *correct* host is out of scope here).

## Story

**As** a developer setting up this repo, or CI running against it,
**I want** every documented/templated env value to match the code default it's supposed to
describe, and every config value that claims to enforce something to actually enforce it,
**so that** following the setup docs works on the first try, and no config exists that looks
like a safety control while doing nothing.

## Acceptance Criteria

### Functional

- [ ] **AC 1.** `.env.example`'s `LANGFUSE_HOST` line is changed from
  `http://localhost:3010` to `https://cloud.langfuse.com`, matching `config.py:87-88`'s
  default. (D62)
- [ ] **AC 2.** `.env.example`'s `NEXT_PUBLIC_API_URL` line includes the `/api` segment
  (`http://localhost:8000/api`), matching what `apps/web/src/lib/api.ts:4` already falls
  back to. (D31)
- [ ] **AC 3.** `.github/workflows/ci.yml`'s `NEXT_PUBLIC_API_URL` build-env value also
  includes `/api`. (D31)
- [ ] **AC 4.** A repo-wide grep for `NEXT_PUBLIC_API_URL.*localhost:8000` with no trailing
  `/api` returns zero matches in any tracked file under `docs/`, `.env.example`, or
  `.github/`. (D31 — closes the "six places disagree" problem at the root rather than
  patching individual sites one at a time.)
- [ ] **AC 5.** `max_daily_spend_per_user_usd` is removed from `apps/api/app/config.py`,
  and every doc reference to it (`.env.example`, `docs/dev1-tracker.md`,
  `.claude/commands/check-costs.md`, and any other hit from a repo-wide grep) is either
  deleted or rewritten to state plainly that per-user daily spend is **not** enforced today
  — only the per-lesson `max_lesson_cost_usd` ceiling and the per-user concurrency cap are
  real. (D48)

### Non-functional / regression-guard

- [ ] **AC 6.** A new test asserts every `.env.example` key that has a corresponding
  `Settings` field with a non-empty default in `config.py` has a value in `.env.example`
  matching that default (or the test explicitly whitelists a documented, intentional
  exception). This is the general-purpose guard D62's register row asks for — it prevents
  this exact class of defect (template value silently diverging from code default)
  regardless of which key drifts next.
- [ ] **AC 7.** A new test resolves the frontend API base URL construction (the same join
  `apps/web/src/lib/api.ts` performs) against the **documented** `NEXT_PUBLIC_API_URL` value
  and asserts the result, for a known route (e.g. `content/lessons`), ends in
  `/api/content/lessons` — not `/content/lessons`. This is the executable settlement the
  register asked for after three reviewer agents disagreed by eyeballing it.
- [ ] **AC 8.** A grep-based test (or extending `test_unbounded_queries.py`-style source
  scan) asserts `max_daily_spend_per_user_usd` — or whatever name a future daily-spend
  control uses — has at least one non-docs, non-config.py reader, OR does not exist in
  `config.py` at all. This prevents D48's exact shape (dead config that reads like a real
  control) from silently reappearing.
- [ ] **AC 9.** No behavior change to any currently-enforced spend control. The per-lesson
  `max_lesson_cost_usd` ceiling and the per-user generation-concurrency cap are untouched by
  this story — confirm by running their existing test suites unmodified and green.

## Scale & Load

*(`docs/SCALE-CONTRACT.md` — six questions, contract-mandated on every story)*

1. **Unit of work, and its range.** This story touches zero runtime request paths. The
   "unit of work" is a static config/doc value; there is no variable input to bound. N/A —
   reason: config/docs-only change, no data flows through the changed lines at runtime.
2. **Fixed budgets vs. variable input.** D62/D31 fixes introduce no new budget. D48's
   *removal* eliminates a budget that was already inert (zero enforcement code read it), so
   removing it changes documentation truth, not runtime behavior — there is no budget-vs-input
   interaction to characterize because the "budget" never executed.
3. **Scope of every limit.** N/A for D62/D31 (no limit involved). For D48: the limit being
   removed was nominally per-user — but since it was never read, it had no effective scope.
   After this story, per-lesson (`max_lesson_cost_usd`) and per-user-concurrency remain the
   only real spend limits, both already scoped and already covered by existing tests.
4. **Unbounded reads/writes.** None introduced. AC 6/7/8's new tests are static/source-scan
   checks, not request-path queries — they don't touch the `test_unbounded_queries.py`
   guard's domain.
5. **Inherited caps re-derived?** N/A — no caps are being sized or resized in this story;
   D48 is being deleted, not re-tuned.
6. **Check-then-act under concurrency.** N/A — no check-then-act sequence exists in this
   story's changes; nothing here reads then writes shared state.

**Why five of six are N/A, stated plainly per CLAUDE.md's rule that a bare "N/A" is not
acceptable:** this story's actual changes are (a) two documentation/template string edits
and (b) deletion of code that had already never executed on any request path. The Scale
Contract's questions are about request-path behavior under load; this story has none. The
one question with real teeth is Q2/Q4-adjacent — AC 8 exists specifically so a *future*
daily-spend control cannot re-introduce D48's shape (a budget that looks enforced but isn't)
without a test catching it.

## Tasks

### Task 1 — D62: Langfuse host
- [ ] 1.1 Fix `.env.example:41` `LANGFUSE_HOST` value
- [ ] 1.2 Write AC 6's general template-vs-default guard test

### Task 2 — D31: API URL prefix
- [ ] 2.1 Fix `.env.example:10`
- [ ] 2.2 Fix `.github/workflows/ci.yml:126` (or current line number — re-verify, register
  notes this moved once already, `:126` → `:188`, when D57 was found to duplicate D31)
- [ ] 2.3 Repo-wide grep sweep for any other doc still missing `/api` (register mentions
  "six places disagree" — find all six, not just the two named above)
- [ ] 2.4 Write AC 7's URL-resolution test

### Task 3 — D48: dead spend-cap config
- [ ] 3.1 Remove `max_daily_spend_per_user_usd` from `config.py`
- [ ] 3.2 Remove/rewrite every doc reference (`.env.example`, `dev1-tracker.md`,
  `check-costs.md`, others found by grep)
- [ ] 3.3 Write AC 8's dead-config guard test
- [ ] 3.4 Re-run `max_lesson_cost_usd` and concurrency-cap test suites unmodified, confirm
  still green (AC 9)

### Task 4 — Defect register + tracker updates
- [ ] 4.1 Close D62, D31, D48 in `docs/DEFECT-REGISTER.md` with commit reference
- [ ] 4.2 Update `docs/dev1-tracker.md` checkbox + Quick Status Dashboard + Last Updated date
  (per CLAUDE.md's Dev 1 tracker auto-update rule — same response as marking complete)

### Task 5 — 6-layer adversarial review
- [ ] 5.1 Story Quality
- [ ] 5.2 Blind Hunter (Security)
- [ ] 5.3 Test Coverage
- [ ] 5.4 AC Completeness
- [ ] 5.5 Process Integrity
- [ ] 5.6 Scale & Load

### Task 6 — Commit + push
- [ ] 6.1 Final commit on `sprint3/s3-35-env-config-fixes`
- [ ] 6.2 Push to remote

## Dev Agent Record

### Implementation Plan
*(populated during implementation)*

### Debug Log
*(populated during implementation)*

### Completion Notes
*(populated during implementation)*

### File List
*(populated during implementation)*

### Change Log

- 2026-08-11: Story file created (story-first commit, branch `sprint3/s3-35-env-config-fixes`)
