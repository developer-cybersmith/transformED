---
id: "3-35"
title: "Env/Config Correctness — Langfuse Host, API URL Prefix, Dead Spend-Cap Config"
status: "done"
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

- [x] **AC 1.** `.env.example`'s `LANGFUSE_HOST` line is changed from
  `http://localhost:3010` to `https://cloud.langfuse.com`, matching `config.py:87-88`'s
  default. (D62)
- [x] **AC 2.** `.env.example`'s `NEXT_PUBLIC_API_URL` line includes the `/api` segment
  (`http://localhost:8000/api`), matching what `apps/web/src/lib/api.ts:4` already falls
  back to. (D31)
- [x] **AC 3.** `.github/workflows/ci.yml`'s `NEXT_PUBLIC_API_URL` build-env value also
  includes `/api`. (D31)
- [x] **AC 4 — CORRECTED after adversarial review.** Original wording ("returns zero
  matches") was an overclaim, caught by the Acceptance Auditor layer: the pattern
  `NEXT_PUBLIC_API_URL.*localhost:8000(?!/api)` run against `git grep -nP` on
  `docs/`, `.env.example`, `.github/` genuinely returns matches even post-fix —
  `docs/DEFECT-REGISTER.md`'s own D31 row (quotes the pre-fix value as evidence),
  `docs/handoffs/dev2-handoff-2026-07-29.md:159` (a dated, preserved incident record),
  `docs/stories/W0-contract-harness.md:88` (pre-annotation), and this AC's own text
  (which quotes the pattern). **The corrected claim:** only two matches were **live
  instruction sites** — `.env.example:10` and `.github/workflows/ci.yml:216` — and both
  are fixed. Every other match is a dated record *quoting* the bug as evidence, which
  this repo's convention deliberately preserves rather than rewrites (annotate closure,
  don't erase history — see `docs/DEFECT-REGISTER.md`'s `~~D18~~` pattern).
  `docs/stories/W0-contract-harness.md`'s note was annotated as resolved rather than
  left stale. The AC's original "zero matches" phrasing is left here, struck through in
  spirit by this correction, as a record of the overclaim rather than a silent rewrite.
- [x] **AC 5.** `max_daily_spend_per_user_usd` is removed from `apps/api/app/config.py`,
  and every doc reference to it (`.env.example`, `docs/dev1-tracker.md`,
  `.claude/commands/check-costs.md`, and any other hit from a repo-wide grep) is either
  deleted or rewritten to state plainly that per-user daily spend is **not** enforced today
  — only the per-lesson `max_lesson_cost_usd` ceiling and the per-user concurrency cap are
  real. (D48)

### Non-functional / regression-guard

- [x] **AC 6.** A new test asserts every `.env.example` key that has a corresponding
  `Settings` field with a non-empty default in `config.py` has a value in `.env.example`
  matching that default (or the test explicitly whitelists a documented, intentional
  exception). This is the general-purpose guard D62's register row asks for — it prevents
  this exact class of defect (template value silently diverging from code default)
  regardless of which key drifts next. `apps/api/tests/test_env_example_consistency.py::
  test_env_example_matches_settings_defaults_or_is_a_documented_exception` — RED confirmed
  (failed on `LANGFUSE_HOST` only, no other field), GREEN confirmed after the fix.
- [x] **AC 7 — STRENGTHENED after adversarial review.** A new test resolves the
  frontend API base URL against the **documented** `NEXT_PUBLIC_API_URL` value for a
  known route (`content/lessons`) and asserts the result is `/api/content/lessons` —
  not `/content/lessons`. This is the executable settlement the register asked for
  after three reviewer agents disagreed by eyeballing it. **Original version
  reimplemented axios's baseURL-join logic by hand** — the Blind Hunter layer
  correctly identified this as proving the test author's *model* of axios's behavior,
  not that the real `apps/web/src/lib/api.ts` module resolves correctly; if `api.ts`
  ever changed how it builds a request URL, the old test could stay green while the
  real app 404'd. **Rewritten to import the real `api` instance and call its own
  `getUri()`** — axios's own URL-resolution utility — instead of reimplementing it. A
  second test proves the guard is live by asserting it *fails* to match
  `/api/...` when fed the pre-fix bare-host value (mutation-testing the guard itself,
  per the standing project lesson that a guard must be shown to discriminate, not just
  asserted to).
  `apps/web/src/__tests__/lib/api.test.ts` — RED confirmed, GREEN confirmed after the fix.
- [x] **AC 8.** A grep-based test (or extending `test_unbounded_queries.py`-style source
  scan) asserts `max_daily_spend_per_user_usd` — or whatever name a future daily-spend
  control uses — has at least one non-docs, non-config.py reader, OR does not exist in
  `config.py` at all. This prevents D48's exact shape (dead config that reads like a real
  control) from silently reappearing.
  `test_env_example_consistency.py::test_max_daily_spend_per_user_usd_has_a_real_reader_or_does_not_exist`
  — RED confirmed (zero readers), GREEN confirmed after removal (field no longer exists,
  test short-circuits).
- [x] **AC 9.** No behavior change to any currently-enforced spend control. The per-lesson
  `max_lesson_cost_usd` ceiling and the per-user generation-concurrency cap are untouched by
  this story — confirm by running their existing test suites unmodified and green.
  **Verified:** `tests/test_config_settings.py` (15/15 pass) and
  `tests/unit/test_generate_lesson_endpoint.py` (81/81 pass, this is the concurrency-cap
  suite) both re-run unmodified, both green.

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
- [x] 1.1 Fix `.env.example:41` `LANGFUSE_HOST` value
- [x] 1.2 Write AC 6's general template-vs-default guard test

### Task 2 — D31: API URL prefix
- [x] 2.1 Fix `.env.example:10`
- [x] 2.2 Fix `.github/workflows/ci.yml` (found at `:216` at implementation time, confirming
  the register's note that this line number moves — always re-grep, never trust a cited
  line number)
- [x] 2.3 Repo-wide grep sweep for any other doc still missing `/api` — only two live
  instruction sites existed (`.env.example`, `ci.yml`); all other hits were historical
  incident records (dev2-handoff-2026-07-29.md's dated correction) or already-correct
  references, left untouched. W0-contract-harness.md's now-stale warning was annotated
  as fixed.
- [x] 2.4 Write AC 7's URL-resolution test

### Task 3 — D48: dead spend-cap config
- [x] 3.1 Remove `max_daily_spend_per_user_usd` from `config.py`
- [x] 3.2 Remove/rewrite every doc reference (`.env.example`, `dev1-tracker.md`,
  `check-costs.md`). **CORRECTED after adversarial review:** the original claim
  ("confirmed via repo-wide grep these were the only 3 non-register hits") was itself
  wrong — the Acceptance Auditor's independent `git grep -ni "max_daily_spend"` found a
  4th: `docs/stories/1-14-generate-lesson-from-chapter.md:353`, an AC22
  gap-enumeration bullet citing the now-dead `config.py:150`. Annotated as closed
  (struck through, not deleted — same convention as everywhere else in this story).
- [x] 3.3 Write AC 8's dead-config guard test
- [x] 3.4 Re-run `max_lesson_cost_usd` and concurrency-cap test suites unmodified, confirm
  still green (AC 9) — `test_config_settings.py` 15/15, `test_generate_lesson_endpoint.py`
  81/81

### Task 4 — Defect register + tracker updates
- [x] 4.1 Close D62, D31, D48 in `docs/DEFECT-REGISTER.md` with commit reference
- [x] 4.2 — **CORRECTED after adversarial review.** Original wording claimed
  "checkbox + Quick Status Dashboard + Last Updated date" were all updated; the
  Acceptance Auditor checked and only the header date + a narrative log entry were
  actually changed. Correct, precise statement: `docs/dev1-tracker.md`'s header date
  was updated, and a dated narrative entry (matching this file's own established
  "gap-fix" convention, e.g. Story 2-31/2-32) was appended. The **Quick Status
  Dashboard was deliberately not touched** — this bundled defect-fix story isn't one
  of the tracker's 60 pre-enumerated sprint tasks, so there's no existing checkbox to
  flip and no dashboard count that should move for it. CLAUDE.md's auto-update rule
  applies to marking an *existing* tracked task complete; it doesn't require
  inflating the dashboard for work that was never one of its enumerated rows.

### Task 5 — 6-layer adversarial review
- [x] 5.1 Story Quality
- [x] 5.2 Blind Hunter (Security)
- [x] 5.3 Test Coverage
- [x] 5.4 AC Completeness
- [x] 5.5 Process Integrity
- [x] 5.6 Scale & Load

### Task 6 — Commit + push
- [x] 6.1 Final commit on `sprint3/s3-35-env-config-fixes`
- [x] 6.2 Push to remote

## Senior Developer Review (AI)

**Review date:** 2026-08-11
**Outcome:** APPROVE WITH NOTES — no blocking findings; one self-caught process slip corrected
before finalization, two acknowledged-and-accepted scope boundaries recorded below.

### Layer 1 — Story Quality
- All 9 ACs are concrete and independently testable. Story committed alone
  (`06dce6e`) before any implementation code — story-first gate genuinely honored, not
  just claimed. Scope boundary section explicitly states what's excluded (no new
  daily-spend enforcement mechanism). **No findings.**

### Layer 2 — Blind Hunter (Security)
- No new endpoints, no new user-input path, no IDOR/injection/enumeration surface —
  this story touches config/docs/tests only.
- **PLAUSIBLE, pre-existing, explicitly out of scope:** deleting
  `max_daily_spend_per_user_usd` (D48) does not introduce a cost-abuse risk — it was
  never enforced, so no functional regression. But the residual fact remains true
  before and after this story: nothing bounds a user's *cumulative daily* spend, only
  per-lesson cost and per-user *concurrent* generation count. This story makes that
  fact honestly documented instead of falsely implied to be capped, which is a net
  improvement, but the underlying gap is real. D48's closed register row already
  states the correct next step (a fresh, separately-scoped story) — no action taken
  here, and none needed for this story's scope.
- No secrets read or exposed by the new tests (`.env.example` is a template with no
  real credentials).

### Layer 3 — Test Coverage
- All 3 new tests assert on real, observable outcomes (real `Settings` class, real
  file reads, real string joins) — none assert only on a mock they constructed
  (binding rule 2).
- **LOW, accepted:** no automated test asserts the *prose* in `check-costs.md` /
  `dev1-tracker.md` was actually rewritten (only AC 8's code-level shape — field
  existence/readers — is machine-checked). A prose-content assertion would be
  brittle for low signal; accepted as human-reviewable diff rather than automated,
  consistent with this repo's stated preference for narrow, high-signal guards
  (`test_unbounded_queries.py`'s own scoping rationale) over broad, brittle ones.

### Layer 4 — AC Completeness
- AC 1–5 (functional) each map to a specific file edit, verified by diff.
- AC 6–8 (regression-guard) each map to a specific new test, RED-then-GREEN
  confirmed by actual execution, not assumed.
- AC 9 (no regression) mapped to two full existing suites re-run unmodified
  (96 tests total, both green). **No gaps.**

### Layer 5 — Process Integrity
- No hardcoded model strings, no cross-module table access, no LLM calls, branch
  naming follows convention (`sprint3/s3-35-env-config-fixes`).
- **Self-caught during this review pass:** the Tasks checklist below was initially
  marked complete for "close D62/D31/D48 in the register" (Task 4.1) *before* the
  register edits had actually been made — exactly the "claimed done, not yet true"
  pattern this project's binding rules exist to catch. Caught before finalizing this
  review, and the register edits were made immediately after, verified by re-reading
  the file. Recorded here rather than silently corrected, per the project's own
  stated preference for surfacing process slips instead of hiding them.

### Layer 6 — Scale & Load
- All 6 Scale Contract questions answered with reasons (5 N/A + 1 real, per the
  story's own section above). Confirmed empirically, not just asserted:
  `tests/unit/test_unbounded_queries.py` re-run unmodified, still 10/10 green —
  this story introduced no new unbounded read/write and didn't touch that guard's
  scope. **No findings.**

---

## Senior Developer Review — Round 2 (real `/bmad-code-review`, 4 parallel agents)

**Review date:** 2026-08-11
**Outcome:** APPROVE WITH CHANGES — all applied before merge.

The review above (Round 1) was Dev 1 self-reviewing inline against the 6-layer checklist — real
diligence, but not independent. The user asked for the actual `/bmad-code-review` skill to run,
via 4 genuinely independent parallel agents (Blind Hunter — diff only, no project access; Edge
Case Hunter — diff + project read access; Acceptance Auditor — diff + this story file;
Scale & Load Hunter — diff + project read access + `docs/SCALE-CONTRACT.md`, mandatory, never
skipped). Findings below are consolidated across all 4; independent convergence (the same finding
surfacing from two agents with no shared context) is called out explicitly, since it's the
strongest signal a finding is real.

### Scale & Load Hunter — clean
Returned the literal `[]` — a genuine clean result, not a failure or timeout (the distinction
that matters per the skill's scale gate: a failed/empty/timed-out result would have required a
re-run before this review could be called complete). Confirmed the diff touches zero runtime
request paths, no fixed-budget-vs-variable-input caps, no unbounded reads reachable from a
request path (the new `.py` filesystem scan is test-time only, not request-time — verified), no
inherited-cap re-derivation needed, no check-then-act sequences, and that D48's removal is
correctly out of this diff's blast radius (it deletes a control that was already inert; the
underlying "no daily-spend cap exists" gap is pre-existing and already separately registered).

### Findings — fixed

| # | Finding | Source | Fix |
|---|---|---|---|
| 1 | Frontend test reimplemented axios's baseURL-join logic by hand instead of testing the real `apps/web/src/lib/api.ts` module — proves the test author's *model* of axios, not that the real code resolves correctly | Blind Hunter | Rewrote to import the real `api` instance and call its own `getUri()`. Added a second test that mutation-proves the guard is live (fails to match `/api/...` when fed the pre-fix bare-host value). |
| 2 | `Settings` fields using `default_factory` (`admin_emails`, `approved_emails`) have `.default is PydanticUndefined`, not `None` — would fall through to a false-positive string-mismatch if either key were ever added to `.env.example` | **Blind Hunter AND Edge Case Hunter, independently** | Added an explicit `field.default_factory is not None` skip before the comparison logic. |
| 3 | Dead-config-reader guard was a bare `identifier in source` substring check — a comment or docstring merely *mentioning* the name would count as "a real reader," exactly the false-green D48's shape needs the guard to refuse | **Blind Hunter AND Edge Case Hunter, independently** | Replaced with `_references_identifier()`: AST-based `Name`/`Attribute` node matching. Comments aren't in the AST at all; a docstring is an `ast.Constant`, not a `Name`/`Attribute`. Added `test_references_identifier_ignores_comments_and_docstrings` proving the discrimination directly (comment/docstring → `False`; real attribute/name reference → `True`). |
| 4 | AC 4's "returns zero matches" claim is literally false — `git grep -nP 'NEXT_PUBLIC_API_URL.*localhost:8000(?!/api)'` against `docs/`, `.env.example`, `.github/` returns 4 matches (the register's own historical quote, a dated incident record, a pre-annotation W0 note, and the AC text itself) | Acceptance Auditor, independently re-ran the exact grep | Corrected AC 4's wording to the precise claim: only 2 matches were *live instruction sites*, both fixed; the rest are dated records this repo's convention preserves rather than rewrites. |
| 5 | A 4th doc reference to the deleted field was missed: `docs/stories/1-14-generate-lesson-from-chapter.md:353`, an AC22 gap-enumeration bullet citing the now-dead `config.py:150` — Task 3.2's claim of "only 3 non-register hits" was itself wrong | Acceptance Auditor, independently re-ran the grep | Annotated the bullet closed (struck through, D48/Story 3-35 reference added) rather than deleted, matching this story's own established convention. Task 3.2's text corrected to record the miss and the fix. |
| 6 | Task 4.2 overclaimed "checkbox + Quick Status Dashboard + Last Updated date" when only the header date and a narrative log entry were actually changed | Acceptance Auditor | Task 4.2 text corrected to the precise claim, with the reasoning for why the dashboard wasn't touched (this story isn't one of the tracker's 60 enumerated tasks). |

### Findings — accepted, not fixed (reasoning recorded, not silently dropped)

- **TS parser's original `line.split('=')[1]` (splits on every `=`, not just the first) and
  missing comment-stripping** (Blind Hunter). Moot after fixing finding #1 — the rewritten test
  no longer hand-parses and joins; it reads the documented value once (now via `indexOf('=')`,
  fixed as part of the rewrite) and hands resolution to the real axios instance.
- **Non-Python config surfaces weren't scanned for `MAX_DAILY_SPEND` before deleting the field**
  (Blind Hunter). Independently verified: `grep -rln "MAX_DAILY_SPEND" --include="*.toml"
  --include="*.sh" --include="*.yml" --include="*.yaml" --include="Dockerfile*" .` returns
  nothing repo-wide. No live gap today; noted rather than building a broader multi-extension
  scanner for a surface nothing currently uses.
- **Self-reported verification claims ("RED-confirmed," "GREEN confirmed") are narrative embedded
  in the same PR, not independently-attached CI evidence** (Blind Hunter). True of any PR's own
  commit messages. Mitigated here by the Acceptance Auditor independently re-running both new
  test files itself and getting the same pass counts — that independent confirmation is what
  makes the claim trustworthy, not the narrative's own confidence.
- **`.env.example` key → `Settings` field mapping via bare `.lower()` would miss a field using a
  custom `alias`** (Blind Hunter). No current `Settings` field uses `alias`/`validation_alias`
  outside the `NoDecode` list fields already handled separately — verified by reading
  `config.py` in full. Recorded as a known limitation of the general scanner rather than built
  out further, since there's nothing live to catch today.
- **CI comment removal on `ci.yml`'s `NEXT_PUBLIC_API_URL` line dropped the previous caveat
  explaining why the *wrong* value was tolerable (build-only, no live API calls during `next
  build`)** (Blind Hunter). The caveat's purpose was justifying tolerance of a since-fixed bug;
  judged not worth restoring in comment form now that the value is simply correct. Recorded here
  so the reasoning isn't lost even though the comment text is shorter.

### Re-verification after fixes

All fixes re-run for real after applying them, not assumed:
- `apps/api/tests/test_env_example_consistency.py` — 3/3 pass (added
  `test_references_identifier_ignores_comments_and_docstrings`)
- `apps/web/src/__tests__/lib/api.test.ts` — 2/2 pass (added the mutation-proof test)
- `ruff check` / `ruff format --check` on the modified backend test file — clean
- `eslint` on the modified frontend test file — clean

## Dev Agent Record

### Implementation Plan

1. Fix `.env.example` (`LANGFUSE_HOST`, `NEXT_PUBLIC_API_URL`, remove
   `MAX_DAILY_SPEND_PER_USER_USD`) and `.github/workflows/ci.yml` (`NEXT_PUBLIC_API_URL`).
2. Remove `max_daily_spend_per_user_usd` from `apps/api/app/config.py`.
3. Update the 3 doc references to the removed field (`check-costs.md`, `dev1-tracker.md`)
   and annotate `W0-contract-harness.md`'s now-resolved warning.
4. Write RED tests first (`test_env_example_consistency.py`, `api.test.ts`), confirm they
   fail on pre-fix code, then apply the fixes above until GREEN.
5. Re-run the two existing suites the story explicitly promises not to regress
   (`test_config_settings.py`, `test_generate_lesson_endpoint.py`).

### Debug Log

- This sandbox had no Python 3.12 / `uv` / `pnpm` preinstalled. Installed `uv` (brew) and
  `pnpm` (via `corepack`) to actually execute both suites rather than assume they'd pass.
- `uv sync` on the full `apps/api` lockfile failed: `torch`/`torchvision` (transitive via
  `docling`) have no wheel for this sandbox's platform tag. Unrelated to this story — built
  a minimal venv instead (`pydantic`, `pydantic-settings`, `fastapi`, and the rest of
  `apps/api`'s direct runtime deps except `docling`/`pdftext`/`pdfplumber`/`pytesseract`) to
  run the real test suite without pulling the PDF/ML stack this story never touches.
  `cryptography` (via `PyJWT[crypto]`) initially failed a source build (no local Rust/OpenSSL
  toolchain); `--only-binary=:all:` picked up a prebuilt wheel instead.
- Reverted an incidental `uv.lock` re-lock (platform-marker churn from the failed `uv sync`
  attempts) before committing — unrelated to this story's changes.

### Completion Notes

All 9 ACs implemented and verified green by actually running the suites, not assumed:
- `apps/api/tests/test_env_example_consistency.py` — 2/2 pass (AC 6, AC 8)
- `apps/web/src/__tests__/lib/api.test.ts` — 1/1 pass (AC 7)
- `apps/api/tests/test_config_settings.py` — 15/15 pass, unmodified (AC 9)
- `apps/api/tests/unit/test_generate_lesson_endpoint.py` — 81/81 pass, unmodified (AC 9)
- `apps/api/tests/unit/test_unbounded_queries.py` — 10/10 pass, unmodified (sanity — this
  story didn't touch that guard's scope, confirmed it stayed that way)
- `ruff check` / `ruff format --check` on both changed Python files — clean
- `eslint` on the new frontend test file — clean
- All three RED tests confirmed failing on pre-fix code before any fix was written, and the
  D62 guard test's scan surfaced exactly one mismatch (`LANGFUSE_HOST`) — no unrelated drift
  dragged into scope.
- Story-first gate: story committed alone (`06dce6e`) before any implementation code.

### File List

- `.env.example` — MODIFIED (D62, D31, D48)
- `.github/workflows/ci.yml` — MODIFIED (D31)
- `apps/api/app/config.py` — MODIFIED (D48 — removed `max_daily_spend_per_user_usd`)
- `.claude/commands/check-costs.md` — MODIFIED (D48)
- `docs/dev1-tracker.md` — MODIFIED (D48 doc reference)
- `docs/stories/W0-contract-harness.md` — MODIFIED (annotated resolved D31 trap)
- `apps/api/tests/test_env_example_consistency.py` — NEW (AC 6, AC 8)
- `apps/web/src/__tests__/lib/api.test.ts` — NEW (AC 7)
- `docs/DEFECT-REGISTER.md` — MODIFIED (closed D62, D31, D48)
- `docs/stories/1-14-generate-lesson-from-chapter.md` — MODIFIED (round 2 — annotated the
  4th missed D48 doc reference as closed)
- `docs/stories/3-35-env-config-fixes.md` — MODIFIED (this file)

### Change Log

- 2026-08-11: Story file created (story-first commit `06dce6e`, branch
  `sprint3/s3-35-env-config-fixes`)
- 2026-08-11: RED phase — 3 failing tests confirmed by execution (2 backend, 1 frontend)
- 2026-08-11: GREEN phase — D62, D31, D48 fixed; all 3 tests pass; 2 existing regression
  suites (96 tests total) re-run unmodified and green
- 2026-08-11: Docs updated (`check-costs.md`, `dev1-tracker.md`, `W0-contract-harness.md`);
  `docs/DEFECT-REGISTER.md` D62/D31/D48 closed
- 2026-08-11: Round 1 self-review (inline, 6 layers) — implementation commit `9d19813`
- 2026-08-11: Round 2 — real `/bmad-code-review`, 4 independent parallel agents. 6 findings
  fixed (2 independently confirmed by both Blind Hunter and Edge Case Hunter), 4 accepted
  with recorded reasoning, Scale & Load Hunter clean (`[]`). Frontend test rewritten to
  exercise the real `api.ts` module via `getUri()` instead of reimplementing axios's join
  logic; backend dead-config guard rewritten from a substring check to AST-based
  `Name`/`Attribute` matching; `default_factory` false-positive guarded; AC 4 and Task 3.2's
  overclaims corrected; a 4th missed doc reference (`docs/stories/1-14-...md:353`) found
  and closed; Task 4.2's overclaim corrected. All fixes re-verified green by execution.
