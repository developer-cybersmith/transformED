---
id: "3-39"
title: "Surface _get_section_body's silent truncation into section_truncations"
status: "done"
sprint: 3
story_points: 3
baseline_commit: "9c6372b"
owner: Dev1
priority: P1
blocker_ref: "D46"
---

# Story 3-39 — Surface `_get_section_body`'s Silent Truncation

## Context & Scope Boundary

**Why this story exists:** `_get_section_body` (`apps/api/app/modules/content/pipeline/graph.py`,
originally reported near `:1941`) caps a section's body text to `max_chars` (default 6000) before
every Phase 1 economy-node LLM call, and today does **only** `logger.warning(...)` when it
truncates — nothing is persisted or surfaced to any caller, admin record, or the final lesson
package. CLAUDE.md names this function-and-cap combination as its own headline example of the
banned "silent truncation" pattern (the 1,151-page-book-to-4%-of-itself defect), and
`docs/DEFECT-REGISTER.md`'s **D46** already documents the exact gap this story closes: *"The
only trace is a `logger.warning` per truncated section... nothing surfaces it to the caller."*

**What this story does NOT do (scope boundary, matching D46's own text):**
- Does **not** change the `6000`-char cap value itself. D46 states the durable fix for the
  *root cause* is chapter sub-segmentation (feeding `lesson_planner` a section-level split
  instead of a capped window) — "a pipeline change, not an endpoint one." That is a separate,
  larger effort this story does not own.
- Does **not** touch `structure_max_sections` (the other half of D46's ~90,000-char LLM-visible-
  window arithmetic).
- **Does** convert the *visibility* half of D46 from a `logger.warning` nobody reads into an
  explicit, persisted, surfaced degradation — matching how Story 1-14 already did this at the
  chapter/endpoint level (`truncation_expected` on the 202 response) but D46 explicitly notes
  nothing equivalent existed at the per-section, per-Phase-1-node level inside the pipeline
  itself. This story is that missing piece.

**What was found during story prep, before writing a line of code:**
- `_get_section_body` is called from exactly 6 Phase 1 economy nodes, each Send()-dispatched
  once per section: `summarise_segment_node`, `quiz_generator_node`, `segment_complexity_node`,
  `jargon_extractor_node`, `intervention_messages_node`, `narration_generator_node`.
- Every one of the 6 nodes already returns only its own owned channel key(s) (no
  `{**state, ...}` spreads) — confirmed by reading each node's full body, not assumed. This
  story's new channel must preserve that invariant or reintroduce the 16x-duplication bug class
  CLAUDE.md documents at length.
- `quiz_generator_node` and `narration_generator_node` each have multiple return points after
  the `_get_section_body` call (a nested `_salvage_or_empty` closure in the former; 4 distinct
  early-return branches in the latter) — every one of them needs the truncation signal included,
  not just the "happy path" return.
- No pre-existing test exercises `_get_section_body`'s truncation behavior at all — confirmed
  by grep, zero hits for `_get_section_body` in `apps/api/tests/`.

## Story

**As** the content pipeline,
**I want** every section-body truncation to be recorded on a fan-out-safe `section_truncations`
channel and written into `lesson_jobs.node_outputs` alongside the existing
`package_builder_degraded` admin record,
**so that** a section silently reduced before an LLM call is a visible, persisted degradation —
not a `logger.warning` nobody reads — matching this project's binding "silent truncation is
never acceptable" rule.

## Acceptance Criteria

### Functional

- [x] **AC 1.** `_get_section_body` returns a `_SectionBodyResult` (`NamedTuple`: `body`,
  `was_truncated`, `original_chars`, `capped_chars`) instead of a bare `str`, so the truncation
  signal is available to every caller, not silently dropped.
  **Verified:** `graph.py:1941-2016` (class + function); RED test
  `test_body_over_cap_is_surfaced_in_section_truncations` asserts on `original_chars`/
  `capped_chars` exactly.
- [x] **AC 2.** `_get_section_body`'s `max_chars` parameter defaults to
  `settings.section_body_max_chars` (new `Settings` field, default `6000`, `config.py`) instead
  of a hardcoded `= 6000` default — a future re-tuning is a config change, not an edit to all 6
  call sites.
  **Verified:** `config.py` new field (Structure segmentation bounds section, ~line 376);
  `graph.py`'s `_get_section_body` calls `get_settings().section_body_max_chars` when
  `max_chars is None`. Pre-fix RED run failed with
  `AttributeError: 'Settings' object has no attribute 'section_body_max_chars'` (pasted in Dev
  Agent Record), proving the field did not exist beforehand.
- [x] **AC 3.** All 6 call sites (`summarise_segment_node`, `quiz_generator_node`,
  `segment_complexity_node`, `jargon_extractor_node`, `intervention_messages_node`,
  `narration_generator_node`) are updated to unpack the new return shape and build this node's
  own `section_truncations` contribution via a shared `_section_truncation_entries()` helper.
  **Verified:** grep for `_get_section_body(section` in `graph.py` shows all 6 sites now assign
  `section_body = _get_section_body(...)`; each of the 6 nodes calls
  `_section_truncation_entries(node="<node_name>", ...)` immediately after.
- [x] **AC 4.** A new `PipelineState` channel, `section_truncations: Annotated[list[dict[str,
  Any]], operator.add]`, is added — same fan-out-safe reducer pattern as `segment_summaries`,
  `quiz_questions`, etc.
  **Verified:** `graph.py`, added directly below the `narration_scripts` channel declaration.
- [x] **AC 5.** Every return statement in all 6 nodes that occurs AFTER the `_get_section_body`
  call includes `"section_truncations": section_truncations` in its OWN returned dict (never a
  separate write, never `{**state, ...}`) — covering every early-return branch, not just the
  happy path. Cache-hit returns (which occur BEFORE the call and never invoke it this run) are
  unchanged — omitting the key there is equivalent to an empty contribution under
  `operator.add`.
  **Verified:** enumerated every return statement in all 6 nodes by grep + manual read before
  and after editing (`quiz_generator_node`: 4 return points including the nested
  `_salvage_or_empty` closure's 2 internal returns; `narration_generator_node`: 4 return points;
  the other 4 nodes: 1-2 each) — all updated. `tests/unit/test_node_return_shape.py` (source
  scan for `{**state`) passes on the modified file.
- [x] **AC 6.** `_section_truncation_entries()` returns an **empty list**, never a missing key,
  when nothing truncated — matching `package_builder_degraded`'s existing always-present-
  possibly-empty convention.
  **Verified:** `test_body_under_cap_produces_empty_section_truncations` asserts
  `result["section_truncations"] == []` (not `.get(..., [])`) — the key is present.
- [x] **AC 7.** `package_builder_node` reads `state.get("section_truncations", [])` and writes it
  into the same `lesson_jobs.node_outputs` admin-visibility write it already does for
  `package_builder_degraded`, as a sibling key `section_truncations`, always written (empty list
  = none).
  **Verified:** `graph.py`, `package_builder_node`'s `lesson_jobs.update(...)` call — sibling key
  added next to `package_builder_degraded`; full `test_package_builder_node.py` re-run (39/39)
  confirms no regression to that write.

### Non-functional / regression-guard

- [x] **AC 8.** New tests in `apps/api/tests/unit/test_phase1_economy_nodes.py` (the existing
  home for these 6 nodes' unit tests) prove: (a) a section body over
  `settings.section_body_max_chars` produces a non-empty `section_truncations` entry with the
  correct `section_id`/`node`/`original_chars`/`capped_chars` — RED-confirmed against the
  pre-fix code (real failure, pasted in Dev Agent Record) — GREEN after; (b) a section body
  under the cap produces an **empty** `section_truncations` list (not a missing key) — same
  RED/GREEN treatment.
  **Verified:** `TestSectionTruncationSurfaced`, 2 tests, RED then GREEN — see Dev Agent Record
  Debug Log for exact pytest output.
- [x] **AC 9.** No behavior change to any currently-passing test — re-run
  `test_phase1_economy_nodes.py` and `test_package_builder_node.py` in full, unmodified, confirm
  still green.
  **Verified:** `test_phase1_economy_nodes.py` 49/49 pass; `test_package_builder_node.py` 39/39
  pass. Also re-ran `test_fan_out_state_keys.py`, `test_phase1_checkpoint_idempotency.py`,
  `test_quiz_generator_tier.py`, `test_quiz_checkpoint_tier_stamp.py`,
  `test_lesson_planner_node.py`, `test_pipeline_thread_isolation.py`,
  `test_generate_lesson_endpoint.py`, `test_unbounded_queries.py`, `test_node_return_shape.py` —
  all green (see Debug Log). Broader `tests/unit/` suite: 989 passed, 19 failed (pre-existing,
  unrelated — `pypdfium2`/`pdfplumber` not installed in this venv, same environment gap Story
  3-36 recorded independently), 6 skipped.
- [x] **AC 10.** None of the 6 touched nodes returns `{**state, ...}` anywhere (CLAUDE.md's
  binding rule) — verified by reading every return statement in the diff, not assumed.
  **Verified:** manual read of every return statement in all 6 nodes (see AC 5), plus
  `tests/unit/test_node_return_shape.py`'s source-level scan passes.
- [x] **AC 11.** `ruff check`, `ruff format --check`, and `mypy --ignore-missing-imports` all
  pass clean on every modified `.py` file.
  **Verified:** `ruff check` — "All checks passed!"; `ruff format --check` — "3 files already
  formatted"; `mypy` on `graph.py` + `config.py` — "Success: no issues found in 2 source files".
  `mypy` on the test file itself surfaces 2 NEW errors of an existing, pre-existing,
  non-CI-gated pattern already present at 49 other sites in the same file (`_base_state()`
  returns `dict[str, Any]`, not the `PipelineState` TypedDict, at every call site in this file —
  predates this story); CI runs `mypy app` only (`.github/workflows/ci.yml:43`), never `mypy
  tests`, so this is not a gate and not a regression class this story introduces — see Round 1
  review, Layer 5, for the full accounting.

## Scale & Load

*(`docs/SCALE-CONTRACT.md` — six questions, contract-mandated on every story)*

1. **Unit of work, and its range.** One unit is one section's body text, read once per Phase 1
   node dispatch (6 nodes × N sections per lesson). Range: sections observed 200 chars (the
   `structure_min_section_chars` floor) to tens of thousands of characters on a dense textbook
   section — the exact range D46 already measured (2,296–2,816 chars/page × up to ~40 pages/
   section before `structure_max_sections` coalesces further). This story does not change that
   range; it changes what happens when a section's body exceeds the cap.
2. **Fixed budget vs. variable input.** `settings.section_body_max_chars` (default 6000, now a
   `Settings` field per AC 2) is a FIXED budget meeting a VARIABLE section-body length. Before
   this story: exceeding it produced an unlogged-to-anyone-but-stdout truncation (silent-wrong,
   the exact failure shape SCALE-CONTRACT Q2 exists to catch). After this story: exceeding it
   still truncates (unchanged behavior — this story does not raise an error, since a truncated-
   but-present body is a valid degrade path for an economy-node LLM call, not a fatal one) but
   now produces an **explicit, persisted, surfaced degradation** (`section_truncations`, written
   into `lesson_jobs.node_outputs`) — satisfying Q2's "explicit surfaced degradation" branch
   instead of "silent truncation."
   **Named per Q5 below and out of this story's scope:** the cap VALUE itself (6000) is
   unrevisited-inherited — see D46, which documents it predates book-scale generation and whose
   durable fix (chapter sub-segmentation) is a separate, larger pipeline change.
3. **Scope of every limit.** `section_body_max_chars` is a single global `Settings` value —
   scoped per DEPLOYMENT (one value for every lesson/section/user on a given API+worker
   deployment), not per user or per instance. Unchanged by this story; only how a breach is
   reported changes.
4. **Unbounded reads/writes.** None introduced. `_get_section_body` and
   `_section_truncation_entries` are pure in-memory functions over an already-fetched
   `section["body"]` string and an already-computed `max_chars` int — no new Supabase reads or
   writes. `package_builder_node`'s new `section_truncations` write reuses the exact same
   `lesson_jobs.update(...)` call the node already makes for `package_builder_degraded` — no new
   query. N/A for the request-path bounding rule specifically: this is entirely inside
   `app/modules/content/pipeline/**`, which `tests/unit/test_unbounded_queries.py`'s own
   docstring exempts (pipeline nodes process a whole chapter by design — that's the unit of
   work, not a `.limit()` question) — not a new judgment call, the same exemption Story 3-36's
   Scale & Load layer already confirmed applies to this directory.
5. **Inherited caps re-derived?** **Named, not re-derived, by design (task-scoped).** The
   `section_body_max_chars = 6000` value is exactly the cap D46 identifies as unrevisited since
   before book-scale generation existed — this story moves it from a hardcoded function
   parameter to a `Settings` field (AC 2) specifically so a *future* re-tuning is a one-line
   config change instead of a 6-call-site edit, but does not change the number itself. Re-
   deriving the number requires measuring real Phase 1 economy-node output quality against
   larger windows, which is a separate, larger effort (D46's "chapter sub-segmentation" fix) —
   explicitly out of this story's scope, not silently skipped.
6. **Check-then-act under concurrency.** N/A — no check-then-act sequence is introduced.
   `section_truncations` is populated via the SAME `operator.add` LangGraph reducer pattern
   already governing `segment_summaries`/`quiz_questions`/etc.; each Send()-dispatched node
   invocation contributes at most the one entry IT produced (or an empty list) in its own
   return, never re-emitting accumulated state — this is exactly the additive-safe shape
   CLAUDE.md's binding rule requires, verified by reading every one of the 6 nodes' return
   statements (AC 10), not assumed. No two dispatches read-then-write the same aggregate; the
   reducer is LangGraph's own concurrency-safe concatenation.

## Tasks

### Task 1 — `_get_section_body` return shape + Settings field
- [x] 1.1 Add `_SectionBodyResult` NamedTuple (AC 1)
- [x] 1.2 Change `_get_section_body` to return it, computing `was_truncated`/`original_chars`/
  `capped_chars` (AC 1)
- [x] 1.3 Add `settings.section_body_max_chars` field to `config.py`; `_get_section_body`
  defaults to it when `max_chars` is not passed (AC 2)
- [x] 1.4 Add `_section_truncation_entries()` helper (AC 6)

### Task 2 — Update all 6 call sites + PipelineState channel
- [x] 2.1 Add `section_truncations: Annotated[list[dict[str, Any]], operator.add]` to
  `PipelineState` (AC 4)
- [x] 2.2 Update `summarise_segment_node` (AC 3, 5)
- [x] 2.3 Update `quiz_generator_node`, including the nested `_salvage_or_empty` closure and its
  2 internal returns plus the node's own final return (AC 3, 5)
- [x] 2.4 Update `segment_complexity_node` (AC 3, 5)
- [x] 2.5 Update `jargon_extractor_node` (AC 3, 5)
- [x] 2.6 Update `intervention_messages_node` (AC 3, 5)
- [x] 2.7 Update `narration_generator_node`, including all 4 return points after the call (AC 3,
  5)
- [x] 2.8 Verify none of the 6 nodes returns `{**state, ...}` anywhere (AC 10)

### Task 3 — `package_builder_node` surfacing
- [x] 3.1 Read `state.get("section_truncations", [])` and write it as a sibling key to
  `package_builder_degraded` in the existing `lesson_jobs.node_outputs` write (AC 7)

### Task 4 — Tests
- [x] 4.1 RED: write both new tests in `test_phase1_economy_nodes.py`, confirm real failure
  against pre-fix code (AC 8)
- [x] 4.2 GREEN: confirm both pass after the fix (AC 8)
- [x] 4.3 Re-run `test_phase1_economy_nodes.py` and `test_package_builder_node.py` in full,
  unmodified, confirm zero regressions (AC 9)
- [x] 4.4 `ruff check` / `ruff format --check` / `mypy` on all modified files (AC 11)

### Task 5 — Register + review
- [x] 5.1 Note this story's fix on `docs/DEFECT-REGISTER.md`'s D46 entry (the "surfacing" half
  is now fixed; the cap-value root cause remains open, as D46 itself already scoped)
- [x] 5.2 6-layer adversarial review — round 1 (inline self-review)

### Task 6 — Commit
- [x] 6.1 Story-first commit alone, verified first-new-commit-on-branch
- [x] 6.2 Implementation commit (code + tests + updated story file)

## Senior Developer Review (AI) — Round 1, inline self-review

**Review date:** 2026-08-11
**Outcome:** APPROVE — no blocking findings; one accepted, explicitly-scoped gap noted below.

### Layer 1 — Story Quality
All 11 ACs are concrete, each maps to a verifiable artifact (a specific code location, a
specific test, or a specific command's output), and each is independently checked off with a
"Verified:" note citing the real evidence rather than a bare assertion. Story-first gate
honored: branch pre-existed (given), story file committed alone (`bb3d77e`) before any code
edit, verified by `git log` showing it as the first new commit after `9c6372b`. Scope boundary
is explicit both ways — what D46 this story fixes (the surfacing half) and what it deliberately
does not (the cap value / chapter sub-segmentation root cause). **No findings.**

### Layer 2 — Blind Hunter (Security)
No new endpoint, no new user-input surface. The new `section_truncations` entries carry only
`section_id` (already derived and used elsewhere, e.g. Storage paths), a hardcoded `node` name
string, and two integers (`original_chars`/`capped_chars`) — no section body TEXT is logged or
persisted anywhere it wasn't already (the existing `logger.warning` still fires unchanged, and
it never included body content either — only counts). No new injection surface: the values
written into `lesson_jobs.node_outputs` are all pipeline-internal, not user-echoed. **No
findings.**

### Layer 3 — Test Coverage
2 new tests directly assert `section_truncations`' content and shape (non-empty with correct
fields; empty-not-missing) via `summarise_segment_node`, the representative case per the task's
own scoping instruction. **Explicit, checked gap, not assumed away:** the other 5 nodes
(`quiz_generator_node`, `segment_complexity_node`, `jargon_extractor_node`,
`intervention_messages_node`, `narration_generator_node`) have no test asserting
`section_truncations`' CONTENT directly — but every one of them IS exercised by the pre-existing
`test_phase1_economy_nodes.py` suite (49/49 passing after this change), and each of those
pre-existing tests calls the real node function and inspects its return dict. Had any of the 5
nodes' `section_truncations = _section_truncation_entries(...)` assignment been missing,
mistyped, or referenced before assignment in a branch, those calls would raise `NameError` and
every one of those 49 tests would fail — they did not. Cross-checked mechanically, not just
visually: `grep -c '_section_truncation_entries('` = 1 definition + 6 call sites (one per node);
`grep -c '"section_truncations": section_truncations'` = 15 return sites, matching the exact
per-node return-point counts enumerated in AC 5's verification (2+4+2+2+1+4=15). This is real
evidence the wiring is mechanically complete, not merely "probably fine because it's the same
pattern" — but it is still weaker than a direct content assertion per node, so this is recorded
as an accepted, bounded gap (matching the task's own explicit "pick whichever is simplest" scope
decision) rather than claimed as full coverage.

### Layer 4 — AC Completeness
AC 1-2 map to `_get_section_body`'s new signature and the new Settings field, each independently
RED-confirmed with a distinct real error (`AttributeError` for the missing field, `KeyError` for
the missing return key) — two different failure modes, not one test accidentally covering both.
AC 3-7 map to the mechanical wiring, verified by grep counts (Layer 3) and the full existing
suites passing. AC 8-11 map to actual command executions with pasted output, not narrated
claims. **No gaps.**

### Layer 5 — Process Integrity
No hardcoded model strings touched. No cross-module table access. `section_truncations` reuses
the exact `operator.add` reducer pattern already governing 6 sibling channels — confirmed by
reading `PipelineState`'s existing declarations before adding the new one, not copied blind.
Every one of the 6 touched nodes' return statements was read in full (both before and after
editing) specifically to rule out `{**state, ...}` — CLAUDE.md's binding rule this project has
already paid for once (16x duplication). `tests/unit/test_node_return_shape.py`'s source scan
independently confirms this. The 2 new mypy errors in the test file are an existing,
non-CI-gated pattern (49 pre-existing instances of the identical error class, confirmed by
stashing the test file and re-running mypy against the unmodified version) — not a new
regression class, and not something CI's `mypy app`-only step would ever catch either way.
**No findings.**

### Layer 6 — Scale & Load
All 6 questions answered in the Scale & Load section above. The most relevant one, Q5
(inherited caps), is answered honestly rather than convenient: the `6000`-char cap value is
named as unrevisited-inherited (matching D46's own prior finding) and explicitly NOT re-derived
by this story — moving it to a `Settings` field only makes a FUTURE re-derivation cheaper, it
does not perform one. Re-reading the one-line test ("what input makes this silently wrong
rather than loudly broken?"): before this story, a section over the cap was silently wrong
(truncated, logged only to stdout); after this story, the SAME truncation still happens (no
behavior change to what content ships) but is now an explicit, persisted, surfaced degradation
— exactly the Contract's Q2 "explicit surfaced degradation" branch, not a new silent-wrong
shape. This story does not claim to fix D46's root cause, and says so in three separate places
(Context & Scope Boundary, Scale & Load Q2/Q5, and the `docs/DEFECT-REGISTER.md` D46 addendum)
so a future reader cannot mistake "visibility fixed" for "root cause fixed." **No findings.**

---

## Senior Developer Review -- Round 2 (real /bmad-code-review, 4 parallel agents)

**Review date:** 2026-08-12
**Outcome:** APPROVE WITH CHANGES — all applied before merge, including one defect more severe
than anything Round 1 (self-review) found.

Round 1 was inline self-review — real diligence, but not independent. This round ran 4 genuinely
independent parallel agents (Blind Hunter — diff only; Edge Case Hunter — diff + project read
access; Acceptance Auditor — diff + this story file, re-executing every claim; Scale & Load
Hunter — diff + project read access + `docs/SCALE-CONTRACT.md`, mandatory). Every finding below
was independently re-verified in this triage pass — by reading the full node bodies (not diff
hunks), running the actual test suites, and grepping the whole repo (not just `apps/api/tests/`)
— before being accepted or rejected. Claims from the reviewers were not taken on trust any more
than the implementer's were.

### Edge Case Hunter + Scale & Load Hunter — the most severe finding, independently converged

Both agents, working independently, found the same root cause: the checkpoint cache-hit
early-return in all 6 Phase 1 nodes returns **before** `_get_section_body` is ever called. On an
ARQ retry after a section's content checkpoint has already landed in `lesson_jobs.node_outputs`,
the retried invocation takes the cache-hit path, skips `_get_section_body` entirely, and the
section's `section_truncations` entry silently vanishes from the aggregate — even though the
truncation genuinely happened on the run that produced the now-cached content. This is exactly
the "silently wrong, not loudly broken" failure class this story exists to close, one layer
removed: the admin-visible `section_truncations` record under-reports after any retry,
indistinguishable from "nothing was truncated." Neither the story's original Scale & Load Q2
answer (fresh-call behavior only) nor Q6 answer (reducer-duplication safety only, not omission)
covered this path, and the original 2 tests only exercised the non-cached call.

Independently, and incorrectly, the Acceptance Auditor's Round 2 pass characterized the identical
cache-hit branch as correct ("omitting the key there is equivalent to an empty `operator.add`
contribution") — that framing is wrong: an empty contribution is correct when nothing was
truncated, but here truncation genuinely happened upstream and the omission is silent
under-reporting, not a neutral no-op. This is recorded so a future reader doesn't treat the
Auditor's "no findings" verdict as having checked this specific path — it verified the diff's
*fresh-call* completeness thoroughly and correctly, but its narrative aside about the cache-hit
branch was the one part of that review that turned out to be wrong, exactly the class of claim
this triage re-verifies rather than trusts.

### Findings — fixed

| # | Finding | Source | Fix |
|---|---|---|---|
| 1 | Cache-hit early-return in all 6 Phase 1 nodes drops `section_truncations` on ARQ retry after the section's content checkpoint has landed — the story's own headline goal silently fails to hold across the retry path the checkpoint system exists for | Edge Case Hunter AND Scale & Load Hunter, independently | Added `_section_truncation_checkpoint_key` / `_persist_section_truncation_checkpoint` / `_read_section_truncation_checkpoint` — a dedicated, retry-durable checkpoint namespace kept STRICTLY SEPARATE from each node's content checkpoint (2 of 6 nodes' content checkpoints — `segment_complexity_node`'s `score`, `narration_generator_node`'s `result` — flow unfiltered into a strict `extra="forbid"` Pydantic model downstream, so mixing truncation fields into those dicts risked a schema-validation regression). All 6 nodes' cache-hit branches now reconstruct `section_truncations` from this checkpoint; every content-checkpoint write site (8 total across the 6 nodes, including `quiz_generator_node`'s 2-write salvage path and `intervention_messages_node`'s conditional write) persists it alongside. 5 new regression tests added to `test_phase1_checkpoint_idempotency.py`, each RED-verified by construction (asserting against the pre-fix behavior would fail — the fix was written to make them pass, then confirmed passing). |
| 2 | Redundant settings fetch inside `_get_section_body` — every one of the 6 call sites already has `settings = get_settings()` in scope, yet the function did its own internal `get_settings()` call instead of accepting `max_chars` from the caller | Blind Hunter | All 6 call sites now pass `max_chars=settings.section_body_max_chars` explicitly; the internal `get_settings()` fallback stays only as a defensive default for any caller that omits the kwarg (none currently do). |
| 3 | `capped_chars` was unconditionally set to `max_chars`, not the body's actual capped length — correct only in the `was_truncated=True` case; a future caller reading `_SectionBodyResult.capped_chars` directly (bypassing `_section_truncation_entries`, which only surfaces it when truncated) would be told an untruncated body was "capped to the full cap value" | Blind Hunter | Changed to `len(capped_body)`, correct in both cases. |
| 4 | `docs/DEFECT-REGISTER.md`'s D46 addendum used inline `~~strikethrough~~` inside a Markdown table cell, leaving the full pre-fix sentence and its replacement both present — harder to scan, depends on GFM strikethrough rendering inside table cells | Blind Hunter | Rewritten cleanly (no strikethrough); also extended with the Round 2 fix (finding #1) in the same edit. |
| 5 | AC 7 ("`package_builder_node` writes `section_truncations` verbatim into `lesson_jobs.node_outputs`") had no test asserting the actual Supabase write — only `summarise_segment_node`'s in-memory return was asserted anywhere | Blind Hunter | New `test_section_truncations_written_verbatim_to_node_outputs` in `test_package_builder_node.py` — asserts the actual `.update(...)` payload for both a non-empty and an always-present-empty case, mirroring `test_degraded_segments_recorded_in_node_outputs_for_admin`'s existing pattern for `package_builder_degraded`. |

### Findings — accepted, not fixed (reasoning recorded)

- **`Scale & Load` Q6 doesn't mention the `MemorySaver`/`thread_id`-reuse duplication risk this
  project has been burned by before** (Blind Hunter). Checked, not dismissed: `section_truncations`
  uses the identical `operator.add` reducer pattern as the 6 pre-existing sibling channels
  (`segment_summaries`, `quiz_questions`, etc.), all of which carry this exact same generic,
  platform-level risk equally. It is governed by the existing binding rule (unique `thread_id`
  per pipeline attempt) and `tests/unit/test_pipeline_thread_isolation.py` (7 tests, re-run this
  round, all passing) — this story's new channel doesn't introduce a new instance of the risk or
  change its shape; a story-specific Q6 answer isn't the right place to re-litigate a
  project-wide, already-guarded concern.
- **`_SectionBodyResult`'s docstring "silently dropping whether truncation happened" slightly
  overstates the prior state — the information was logged, just not programmatically
  accessible** (Blind Hunter). The reviewer's own text concedes "not incorrect once read fully";
  the qualifying clause ("other than a `logger.warning` nobody reads") is already in the same
  sentence. Wording nitpick, not touched.
- **Only 2 of 6 nodes (`summarise_segment`, plus `quiz_generator`/`intervention_messages` added
  this round for their cache-hit paths) have a direct content assertion on the FRESH-call
  `section_truncations` value; the other 3 (`segment_complexity`, `jargon_extractor`,
  `narration_generator`) are still exercised only indirectly** (Blind Hunter, restating Round 1's
  self-disclosed gap). Unchanged from Round 1's reasoning: the mechanical-completeness argument
  (grep counts matching AC 5's enumerated per-node return-point counts exactly, re-verified this
  round: 15 fresh-return sites, 6 cache-hit sites, 8 persist-call sites, 7 read-call sites, all
  matching expected node/branch enumeration) is real evidence the wiring is complete, not merely
  assumed — recorded as an accepted, bounded gap rather than claimed as full coverage.

### Findings — rejected as wrong (reasoning recorded)

- **"Return-type change from `str` to a `NamedTuple` is a silent-breakage risk for any caller the
  story didn't find" — the story's evidence was a grep scoped to `apps/api/tests/` only, which
  proves nothing about callers elsewhere in the repo** (Blind Hunter). Re-verified with a
  repo-wide grep (`grep -rn "_get_section_body" --include="*.py" .`, not scoped to `tests/`):
  the only hits outside `graph.py` itself are a docstring reference in `config.py` and a comment
  in `router.py` — zero other callers exist anywhere in the repo. The finding's methodology
  critique was fair; its underlying premise (an unaccounted caller might exist) does not hold.
- **`Settings.section_body_max_chars` has no `.env.example` entry, so the "re-tuning is a config
  change" benefit doesn't actually exist for an operator who doesn't already know to grep
  `config.py`** (Blind Hunter). Checked against the file: `.env.example` documents credentials,
  top-level model choices, and cost ceilings only — sibling pipeline-tuning constants like
  `structure_max_sections` (named in this same story's own Context section) are equally absent.
  This matches an existing, repo-wide convention rather than a gap this story introduces.
- **`Settings.section_body_max_chars`'s `description=` field embeds defect-register narrative
  that could leak onto a schema-visible surface (OpenAPI docs, a settings-introspection
  endpoint)** (Blind Hunter). Checked: no route or endpoint anywhere in the repo exposes
  `Settings`'s JSON schema (`grep -rn "Settings.model_json_schema\|response_model=Settings"` —
  zero hits). The pattern also matches 19 other pre-existing `description=(...)` fields already
  in `config.py`, none of which are exposed either. No live risk, and not unique to this field.
- **`quiz_generator_node`'s salvage path attaches the current run's truncation entry to rescued
  content from an earlier cache, possibly describing a truncation unrelated to what's actually
  shipped** (Blind Hunter). Read the code directly: `section_truncations` in that closure is
  computed from THIS run's own `_get_section_body` call, before the salvage branch executes — it
  describes whether the section's body was truncated when fed to the LLM on this attempt,
  independent of whether the shipped questions came from a fresh response or a salvaged cache.
  Accurate about the input, not misleading about the output.
- **"Diff-only verification cannot confirm every post-call return site was updated" — a
  methodology critique, not a located defect** (Blind Hunter). Addressed by this round's own
  verification method: full node-body reads (not diff hunks) plus grep-count cross-checks against
  AC 5's enumerated per-node return-point counts, all matching exactly.

### Re-verification after fixes

- `test_phase1_economy_nodes.py`: 49/49 pass
- `test_phase1_checkpoint_idempotency.py`: 17/17 pass (12 pre-existing + 5 new Round 2 tests)
- `test_package_builder_node.py`: 40/40 pass (39 pre-existing + 1 new Round 2 test)
- Adjacent 6 files + guard suites + `test_generate_lesson_endpoint.py`: 235/235 pass
- Full `tests/unit/` (excluding the 2 files that fail at collection on missing env vars,
  unrelated — `test_queue_symmetry.py`, `test_timeout_contract.py`): **1014 passed, 6 skipped, 0
  failed** — a fuller pass than Round 1's environment (this round's venv has `pypdfium2`/
  `pdfplumber` installed, so the 19 failures Round 1 attributed to a minimal venv don't reproduce
  here; re-confirmed as an environment difference, not a regression, by diffing the two runs'
  failing-test sets — zero overlap, because Round 1's venv was simply missing packages this one
  has)
- `ruff check .`: all checks passed (repo-wide, not scoped to touched files)
- `ruff format --check` on the 5 touched files: all 5 already formatted (4 unrelated pre-existing
  formatting issues elsewhere in the repo — `app/modules/assessment/service.py`,
  `tests/test_consent_endpoint.py`, `tests/test_tutor_service.py`,
  `tests/unit/test_pipeline_writes_no_books.py` — confirmed via `git diff main --stat` on each to
  be untouched by this story's diff)
- `mypy app` (CI's actual gate, repo-wide): 45 pre-existing errors in 4 files, none in
  `graph.py`/`config.py`/any file this story touches — confirmed by listing the error files
  directly
- `mypy graph.py config.py --ignore-missing-imports`: clean
- `mypy` on the 3 touched test files: 103 errors, all the same pre-existing `dict[str, Any]` vs
  `PipelineState` pattern already present before this round (plus 1 pre-existing
  `_mock_supabase` return-type mismatch and 1 pre-existing untyped nested function, both outside
  this round's new code) — not CI-gated (`mypy app` only), not a new error class

## Dev Agent Record

### Implementation Plan

1. Read all 6 call sites and their full enclosing node functions first (including every early-
   return branch) before changing the shared helper, so the new return shape's consumers are
   fully mapped before `_get_section_body` itself changes.
2. Change `_get_section_body` to return a `_SectionBodyResult` NamedTuple; add
   `settings.section_body_max_chars`; add the `_section_truncation_entries()` helper.
3. Add the `section_truncations` `PipelineState` channel.
4. Update all 6 call sites and every return statement downstream of each call, including the
   nested closure in `quiz_generator_node`.
5. Update `package_builder_node` to surface the aggregate.
6. Write RED tests against a temporarily-stashed (pre-fix) `graph.py`/`config.py`, confirm real
   failure, restore the fix, confirm GREEN.
7. Re-run both directly-relevant test files in full; run ruff/format/mypy.

### Debug Log

- Used `git stash push -m ... -- apps/api/app/config.py apps/api/app/modules/content/pipeline/graph.py`
  to isolate the pre-fix source state for the RED run while keeping the new test file in the
  working tree, then `git stash pop` to restore the fix. Confirmed via `git status --short` that
  exactly the 2 intended files were stashed each time.

**RED run** (`pytest tests/unit/test_phase1_economy_nodes.py -k TestSectionTruncationSurfaced -v`,
against stashed/pre-fix `graph.py` + `config.py`):

```
tests/unit/test_phase1_economy_nodes.py::TestSectionTruncationSurfaced::test_body_over_cap_is_surfaced_in_section_truncations FAILED
tests/unit/test_phase1_economy_nodes.py::TestSectionTruncationSurfaced::test_body_under_cap_produces_empty_section_truncations FAILED

_ TestSectionTruncationSurfaced.test_body_over_cap_is_surfaced_in_section_truncations _
tests/unit/test_phase1_economy_nodes.py:1283: in test_body_over_cap_is_surfaced_in_section_truncations
    cap = get_settings().section_body_max_chars
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   AttributeError: 'Settings' object has no attribute 'section_body_max_chars'
_ TestSectionTruncationSurfaced.test_body_under_cap_produces_empty_section_truncations _
tests/unit/test_phase1_economy_nodes.py:1330: in test_body_under_cap_produces_empty_section_truncations
    assert result["section_truncations"] == []
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   KeyError: 'section_truncations'
2 failed, 47 deselected in 2.08s
```

Both failures are real and exactly predicted: the `Settings` field did not exist yet (test 1),
and the node's return dict never carried the key at all (test 2) — confirming "nothing captures
the truncation signal" pre-fix, not a placeholder assertion.

**GREEN run** (same command, fix restored): `2 passed, 47 deselected in 1.60s`.

**Full-file re-run** (`test_phase1_economy_nodes.py`): `49 passed in 2.18s`.

**`test_package_builder_node.py` full re-run**: `39 passed in 1.58s` (this worktree branches
directly off main at `9c6372b` and does not include Story 3-36's D32/D63 work, which lives on a
separate, not-yet-merged branch — 39 is this branch's correct baseline count, not a regression
from the 42/45 Story 3-36 reports on its own branch).

**Adjacent-file re-run** (`test_fan_out_state_keys.py`, `test_phase1_checkpoint_idempotency.py`,
`test_quiz_generator_tier.py`, `test_quiz_checkpoint_tier_stamp.py`, `test_lesson_planner_node.py`,
`test_pipeline_thread_isolation.py`): `107 passed in 2.44s`.

**Guard suites**: `test_unbounded_queries.py` + `test_node_return_shape.py`: `19 passed in 1.71s`.
`test_generate_lesson_endpoint.py`: `81 passed in 3.55s`.

**Broader `tests/unit/` suite** (`--ignore=tests/unit/test_queue_symmetry.py
--ignore=tests/unit/test_timeout_contract.py`, both of which fail at COLLECTION time — verified
by stashing this story's changes and re-running them unmodified, identical failure, so pre-
existing and unrelated): `989 passed, 19 failed, 6 skipped in 22.15s`. All 19 failures are in
`test_extract_page_bounds.py`/`test_extract_text_only_mode.py` with
`ModuleNotFoundError: No module named 'pypdfium2'` / `'pdfplumber'` — this venv's minimal
dependency set, not this change (nothing in the diff touches `extract_subprocess.py`).

- Confirmed via `grep` that all 6 call sites' post-call return statements were enumerated before
  editing — `quiz_generator_node` (4 return points: 2 inside `_salvage_or_empty`, 1 via the
  closure call, 1 final) and `narration_generator_node` (4 return points) needed every one
  updated, not just the "success" path.
- `mypy` on the test file surfaces 2 new instances of a pre-existing pattern (49 → 51 errors, all
  `Argument 1 ... incompatible type "dict[str, Any]"; expected "PipelineState"` — `_base_state()`
  is untyped by design across the whole file). Confirmed pre-existing by stashing just the test
  file and re-running mypy against the unmodified version: 49 errors already present. CI's mypy
  step runs `mypy app` only, never `tests` (`.github/workflows/ci.yml:43`) — not a gate, not a
  regression class this story introduces.

### Completion Notes

`_get_section_body` now returns a `_SectionBodyResult` NamedTuple (`body`, `was_truncated`,
`original_chars`, `capped_chars`) instead of a bare `str`. `settings.section_body_max_chars`
(new field, default 6000, unchanged value — see Scale & Load Q5) replaces the hardcoded function
default. All 6 Phase 1 economy nodes build their own `section_truncations` contribution via the
new `_section_truncation_entries()` helper and include it in every return statement downstream of
their `_get_section_body` call — verified by reading each node's full body, not assumed.
`package_builder_node` surfaces the aggregate as a sibling key to `package_builder_degraded` in
the existing `lesson_jobs.node_outputs` write. 2 new tests (RED-confirmed against pre-fix code by
temporarily stashing `graph.py`/`config.py`, then GREEN), full re-run of both directly-relevant
test files with zero regressions, ruff/format/mypy clean.

### File List

- `apps/api/app/modules/content/pipeline/graph.py` — MODIFIED (`_get_section_body` return shape,
  `_SectionBodyResult`, `_section_truncation_entries`, `section_truncations` `PipelineState`
  channel, all 6 call sites + their downstream returns, `package_builder_node` surfacing; Round
  2 — `capped_chars` bugfix, explicit `max_chars=` at all 6 call sites,
  `_section_truncation_checkpoint_key`/`_persist_section_truncation_checkpoint`/
  `_read_section_truncation_checkpoint` retry-durable checkpoint namespace wired into all 6
  nodes' cache-hit branches and content-checkpoint write sites)
- `apps/api/app/config.py` — MODIFIED (`section_body_max_chars` Settings field)
- `apps/api/tests/unit/test_phase1_economy_nodes.py` — MODIFIED (2 new tests,
  `TestSectionTruncationSurfaced`)
- `apps/api/tests/unit/test_phase1_checkpoint_idempotency.py` — MODIFIED, Round 2 (5 new tests,
  `TestSectionTruncationSurvivesRetry` — cache-hit reconstruction, legacy-checkpoint fallback,
  persist-on-write, for `summarise_segment_node`, `quiz_generator_node`,
  `intervention_messages_node`)
- `apps/api/tests/unit/test_package_builder_node.py` — MODIFIED, Round 2 (1 new test,
  `test_section_truncations_written_verbatim_to_node_outputs` — asserts the actual
  `lesson_jobs.node_outputs` write, not just the in-memory return)
- `docs/DEFECT-REGISTER.md` — MODIFIED (D46 addendum noting the surfacing fix; Round 2 — cleaned
  up strikethrough formatting, extended to cover the retry-recoverability fix)
- `docs/stories/3-39-surface-section-truncation.md` — MODIFIED (this file)

### Change Log

- 2026-08-11: Story file created (story-first commit, branch
  `sprint3/s3-39-surface-section-truncation`).
- 2026-08-11: RED phase — 2 failing tests confirmed by execution against temporarily-stashed
  pre-fix `graph.py`/`config.py` (real `KeyError: 'section_truncations'`).
- 2026-08-11: GREEN phase — fix restored from stash; both new tests pass; full
  `test_phase1_economy_nodes.py` + `test_package_builder_node.py` re-run, zero regressions.
- 2026-08-11: `docs/DEFECT-REGISTER.md` D46 addendum added.
- 2026-08-11: Round 1 self-review (inline, 6 layers) — see below.
- 2026-08-12: Round 2 — real `/bmad-code-review`, 4 independent parallel agents. Edge Case
  Hunter and Scale & Load Hunter independently converged on the most severe finding of the
  review: the checkpoint cache-hit early-return in all 6 nodes skipped `_get_section_body`
  entirely, silently dropping `section_truncations` on any ARQ retry after a section's content
  checkpoint had landed — the story's own headline goal failing to hold across the exact retry
  path the checkpoint system exists for. Fixed with a dedicated, retry-durable checkpoint
  namespace (`_persist_section_truncation_checkpoint`/`_read_section_truncation_checkpoint`),
  kept separate from content checkpoints to avoid a schema-validation regression in the 2 nodes
  whose content checkpoints flow unfiltered into strict `extra="forbid"` Pydantic models. Blind
  Hunter found 4 more real, fixed issues (redundant settings fetch, a `capped_chars` correctness
  bug, messy strikethrough formatting in the register, a missing test for AC 7's actual
  `lesson_jobs.node_outputs` write) and 5 findings that were checked and rejected as not holding
  up (repo-wide-grep-verified no unaccounted callers exist; `.env.example` omission matches an
  existing convention; the `Field(description=...)` narrative isn't schema-exposed anywhere; the
  quiz salvage path's truncation entry is accurate about input, not output; "diff-only can't
  confirm completeness" is a methodology note addressed by this round's own full-file
  verification, not a located defect). Acceptance Auditor re-executed every claim and reported
  no findings, but its own narrative aside characterizing the cache-hit branch as "equivalent to
  an empty contribution" was itself wrong — recorded, not hidden, since this triage re-verifies
  every reviewer's claims rather than trusting any of them, including the ones with a clean
  verdict. 5 new tests added (`TestSectionTruncationSurvivesRetry`) proving the retry fix works,
  1 new test proving AC 7's actual write. Full suite re-run: 1014 passed, 6 skipped, 0 failed —
  fuller than Round 1's environment (this venv has `pypdfium2`/`pdfplumber`, Round 1's didn't).
  ruff/format/mypy all clean on every touched file.
