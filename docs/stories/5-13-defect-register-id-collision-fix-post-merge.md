---
status: done
baseline_commit: 5abaed6
---

# Story 5-13 — Defect Register ID Collision Fix (Post-Big-Merge)

## Story

**As a** developer reading `docs/DEFECT-REGISTER.md`,
**I want** every defect entry to have a unique ID,
**so that** a bare D-nn reference in code, comments, or tests unambiguously resolves to exactly one registered defect.

## Background

The big merge of 2026-09-28 (PR #261 and related) brought together multiple long-lived feature branches,
each of which had independently allocated D-entry IDs from the same free range without first re-reading
main's highest-allocated number — the exact rule the register's own banner (fourth-occurrence note) states,
violated again.

A `Group-Object` sweep of `docs/DEFECT-REGISTER.md` on 2026-09-28 found **110 total entries, 102 unique
D-numbers** — 8 IDs each appearing twice.

**D64** is an intentional, documented dual-entry (see the ⚠️ fourth-occurrence banner at the file's top
and the reconcile-by-note at D64's own row) — both entries deliberately kept, per the register's
established convention. This story does NOT touch D64.

**D166, D168, D169, D170, D173, D174, D192** are genuine collisions introduced by the big merge.
For each, the **first occurrence** (lower line number = was in the register on main first) keeps its ID.
The **second occurrence** (interloper, from a branch that allocated the same number without re-checking)
is renumbered to a free ID above D199.

### Collision map

| Canonical (keep) | Interloper (rename) | New ID | Interloper description (one-liner) |
|---|---|---|---|
| D166 L1200 — CaptionOverlay karaoke dead-zone | L1247 — `scripts/dna_profile_quality_check.py` unbounded `.limit(500)` | **D200** | Scale: silent truncation of quality-check report at 501st profile |
| D168 L1207 — `lesson_planner_node` `segment_summaries` sort gap | L1248 — `SixtyDbTTSProvider.COST_PER_CHAR` unconfirmed placeholder | **D201** | Cost: 60db rate is Sarvam placeholder, never confirmed |
| D169 L1208 — `narration_generator` `check_ceiling` TOCTOU | L1249 — `SarvamTTSProvider._synthesize_inner` retries entire loop | **D202** | Cost: Sarvam retries re-bill all already-succeeded batches |
| D170 L1209 — degrade-not-fabricate guard duplicated × 3 nodes | L1250 — `.env.example` CES weights stale vs `config.py` | **D203** | Config: `.env.example` CES weights drift pre-existing from main |
| D173 L1210 — `process_onboarding` plain `.insert()` (FIXED) | L1251 — `SixtyDbTTSProvider._chunk_text` duplicates `sarvam.py` | **D204** | Code: 60db chunker is a near-verbatim copy of Sarvam's |
| D174 L669 — book-context text in Langfuse traces (DPDP gap) | L1252 — Story 232 unbounded chunk loop / no per-segment TTS budget | **D205** | Scale: no overall elapsed-time ceiling across a segment's TTS chunk loop |
| D192 L927 — Sidebar expand toggle invisible (clipped) | L1261 — S5-4 shipped wrong headline-number reading (FIXED via S5-5) | **D206** | Correctness: S5-4 read 15/30/45 as seat-time, not narration minimum |

### Code cross-references to update

The interloper entries are cited in source files. These citations must be updated to the new IDs:

| File | Line(s) | Old ID | New ID |
|------|---------|--------|--------|
| `apps/api/app/providers/tts/sixtydb.py` | 35, 75 | D168 | D201 |
| `apps/api/app/providers/tts/sixtydb.py` | 88 | D173 | D204 |
| `apps/api/app/providers/tts/sixtydb.py` | ~208 | D168/D169 | D201/D202 |
| `apps/api/app/providers/tts/sixtydb.py` | ~351 | D174 | D205 |
| `apps/api/app/schemas/lesson.py` | 68 | D192 | D206 |

`apps/api/tests/test_249_context_wiring.py` mentions D192 in three test docstrings — those
refer to an internal development label for a finding that was **fixed within story 249 itself**
and has no register entry; they do NOT reference either of the two register D192 entries, and
are left unchanged.

## Acceptance Criteria

1. **AC1 — Register de-duplicated:** `docs/DEFECT-REGISTER.md` contains no two entries with the same
   `D-nn` ID (where ID = the number in `## Dxxx` headings or `| **Dxxx** |` table cells).
   The only permitted exception is D64, which carries an explicit reconcile-by-note.

2. **AC2 — Canonical entries unchanged:** The 7 canonical entries (D166 L1200, D168 L1207, D169 L1208,
   D170 L1209, D173 L1210, D174 L669, D192 L927) retain their original ID and content verbatim.

3. **AC3 — Interloper entries renumbered:** The 7 interloper entries appear with their new IDs
   (D200–D206) and their content is otherwise unchanged.

4. **AC4 — Cross-references updated:** Every code/doc file that cited an interloper ID now cites
   the new ID. Specifically: `sixtydb.py` D168→D201, D173→D204, D168/D169→D201/D202, D174→D205;
   `schemas/lesson.py` D192→D206.

5. **AC5 — Banner updated:** The ⚠️ ID-collision banner at the top of `DEFECT-REGISTER.md` is
   amended with a fifth-occurrence note naming the seven collisions introduced by the 2026-09-28
   big merge and how they were resolved.

6. **AC6 — Guard test passes:** `tests/unit/test_no_hardcoded_models.py` (or equivalent CI guards)
   still pass with no regressions introduced by this change.

7. **AC7 — Register last-updated date:** The `Last updated:` line in `DEFECT-REGISTER.md`'s header
   is updated to 2026-09-28.

## Scale & Load

**S1 — Unit of work:** One DEFECT-REGISTER.md edit pass + 2 source files updated.
Range: 7 ID replacements in the register + 6 line edits across `sixtydb.py` and `schemas/lesson.py`.
Fixed, bounded set — no unbounded queries or loops.

**S2 — Fixed budgets:** No LLM calls, no DB queries, no HTTP calls. All edits are in-repo file edits
touching a known, enumerated set of lines.

**S3 — Scope:** Per-repo change only. One file (DEFECT-REGISTER.md) is the authoritative register;
all edits are local.

**S4 — Unbounded reads/writes:** None. The edit set is statically known from this story's collision
map above.

**S5 — Inherited caps:** Not applicable — no pipeline, no concurrency, no budget ceiling.

**S6 — Check-then-act safety:** Not applicable — no concurrent writes to the register; single-author
branch, merged via PR.

## Tasks

- [x] **T1 — Create story file and commit (BMAD gate)**
  - [x] T1.1 — Write this file at `docs/stories/5-13-defect-register-id-collision-fix-post-merge.md`
  - [x] T1.2 — Commit as story-first commit: `git commit -m "docs(story-first): Story 5-13 — Defect Register ID collision fix (post-big-merge)"`
  - [x] T1.3 — Push story-only commit to remote

- [x] **T2 — Write failing test (RED phase)**
  - [x] T2.1 — Write `tests/unit/test_defect_register_no_duplicate_ids.py` that:
    - Parses `docs/DEFECT-REGISTER.md` for all `## Dxxx` and `| **Dxxx** |` patterns
    - Asserts each D-number appears at most once (with explicit D64 exception per existing convention)
    - Confirms the test FAILS on current main (pre-fix) — confirmed: 7 collisions detected

- [x] **T3 — Fix DEFECT-REGISTER.md (GREEN phase)**
  - [x] T3.1 — Rename interloper D166→D200 (line ~1247)
  - [x] T3.2 — Rename interloper D168→D201 (line ~1248)
  - [x] T3.3 — Rename interloper D169→D202 (line ~1249)
  - [x] T3.4 — Rename interloper D170→D203 (line ~1250)
  - [x] T3.5 — Rename interloper D173→D204 (line ~1251)
  - [x] T3.6 — Rename interloper D174→D205 (line ~1252)
  - [x] T3.7 — Rename interloper D192→D206 (line ~1261)
  - [x] T3.8 — Add ⚠️ fifth-occurrence banner note at file header

- [x] **T4 — Update cross-references in source files**
  - [x] T4.1 — `sixtydb.py` L35: `D168` → `D201`
  - [x] T4.2 — `sixtydb.py` L75: `D168` → `D201`
  - [x] T4.3 — `sixtydb.py` L88: `D173` → `D204`
  - [x] T4.4 — `sixtydb.py` L~208: `D168/D169` → `D201/D202`
  - [x] T4.5 — `sixtydb.py` L~351: `D174` → `D205`
  - [x] T4.6 — `schemas/lesson.py` L68: `D192` → `D206`

- [x] **T5 — Update register header**
  - [x] T5.1 — Change `Last updated: 2026-09-03` → `Last updated: 2026-09-28`

- [x] **T6 — Run guard tests**
  - [x] T6.1 — `pytest tests/unit/test_defect_register_no_duplicate_ids.py -v` — 3 passed
  - [x] T6.2 — `pytest tests/unit/test_node_return_shape.py tests/unit/test_unbounded_queries.py -v` — 21 passed, 1 pre-existing `tinytag` ModuleNotFoundError (confirmed pre-existing, not introduced here)
  - [x] T6.3 — `ruff check sixtydb.py schemas/lesson.py` — All checks passed

## Dev Agent Record

### Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-09-28 | Story file created | Dev 3 / Claude |

### Completion Notes

All 7 genuine collisions renumbered. D64's intentional dual-entry left intact.
`test_defect_register_no_duplicate_ids.py` added to `tests/unit/` — will gate CI on future collisions.
Pre-existing `tinytag` ModuleNotFoundError on `test_tts_node_returns_only_its_own_keys` is unrelated
(local dev env missing the package) and confirmed pre-existing before this branch.

**Internal D192 labels in `graph.py` — intentionally left unchanged:**
`graph.py` lines 7808, 7933, and 8089 carry `# D192 (2026-09-25)` comments that are
Story-249 internal development labels for a finding (narration_generator_node's truncation-warning
suppression was dead code until `book_context_truncated`/`chapter_context_truncated` were added
to `_FAN_OUT_STATE_KEYS`) that was fixed entirely within Story 249 and has no register entry.
These are the same category as the three `test_249_context_wiring.py` internal labels
already noted in the story — both files were written during Story 249's development using
the same informal `D192` tag for this internal finding. Neither refers to the canonical
register D192 (Sidebar expand toggle, frontend) nor to D206 (S5-4 headline-number reading,
now renamed from the interloper D192). All three graph.py comments correctly remain D192.

### Debug Log

_To be filled in if needed._

## Senior Developer Review (AI)

**Date:** 2026-09-28 | **Outcome:** Approved

**6-layer review results:**

| Layer | Result | Notes |
|-------|--------|-------|
| Story Quality | PASS | Story-first commit `a5f25c4` precedes implementation `dc5ed51`; all 7 ACs defined; Scale & Load complete |
| Blind Hunter (Security) | PASS | Pure file read within repo; no new attack surface |
| Test Coverage | PASS | Regex correct: `\b` rejects `D166foo`; `group(1) or group(2)` handles alternation; BOM irrelevant; `d64_count >= 1` intentional |
| AC Completeness | PASS | AC1 guarded by machine test; ACs 2/3/4/5/7 rely on diff review (acceptable for doc-only housekeeping) |
| Process Integrity | PASS (after patch) | Patch: `status: in-progress` → `status: done` (applied) |
| Scale & Load | PASS | N/A with reasons for all 6 questions; no pipeline, no DB, no LLM |

**Action Items (all resolved):**
- [x] P1 (Low): `status: in-progress` → `status: done` in story frontmatter — FIXED
