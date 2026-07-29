---
baseline_commit: 3e168cdb5aa39bf8f37559150f39a773ddce0fba
---

# Story 1.5: AvatarOverlay Component + Avatar Fields Schema Change

Status: ready-for-dev

## Story

As a student,
I want to see the HeyGen avatar play a brief intro/outro around my lesson (and gracefully see nothing extra when no avatar is configured for a lesson),
so that the lesson feels more personal without ever blocking or slowing down the actual content.

**Source:** `docs/dev2-sprint-tracker.md` S1-05, blocked since Sprint 1 — the frozen `LessonPackage` contract had zero avatar-related fields, so there was nowhere for the frontend to read a clip/image URL from. Scoped and drafted as `docs/proposals/avatar-fields-schema-change.md` (Dev 2), cross-team sign-off now confirmed verbally by the user on behalf of all 4 devs; this story implements it after independently re-verifying it's safe against the actual current code on `main` (not just the proposal's own claims).

**What's already built on the backend (verified directly):**
- `apps/api/app/providers/avatar/heygen.py` — a real `HeyGenAvatarProvider.get_cached_clip(clip_type)` exists, returning a signed Supabase Storage URL for one of two pre-cached, generic MP4s (`"intro"`/`"outro"` only — no static-image variant yet, no subject-specific variants yet).
- `apps/api/app/modules/content/pipeline/graph.py` (`package_builder_node` included) has **zero** avatar references — nothing populates any avatar field into a lesson today.
- **Corrected during this story's 3-agent review (both the story's original draft and the proposal it implements were stale on this point):** `GET /media/signed-url` is **not** a 501 stub — it's fully implemented (real ownership checks, real signed-URL generation), landed via earlier work already on `main` before this branch was cut. More importantly, **`avatar-clips` is no longer in its bucket allowlist at all** — Story 2-25 deliberately removed it (`apps/api/app/modules/media/router.py`'s `_ALLOWED_BUCKETS` comment): the bucket's flat clip paths (`clips/intro_default.mp4`, no UUID prefix) always 404 against this endpoint's `{lesson_id}/...`-shaped ownership check, so it was disabled as structurally unreachable rather than fixed. **This means the proposal's "open question" about signed-URL-expiry vs. a public bucket for `avatar-clips` is not just unresolved — the signed-URL path is currently closed off entirely**, and whoever picks up the remaining backend wiring (population + this endpoint) will need to either re-enable a corrected version of this bucket in the allowlist or make it public, not just answer the original expiry question.

**This story's actual scope (Dev 2's half only — confirmed with the user):**
1. The schema change itself (`packages/shared/types/lesson.ts`, `packages/shared/lesson_package.schema.json`, and the mirrored `apps/api/app/schemas/lesson.py` Pydantic model — needed for the contract to be genuinely consistent, not just a paper promise on the TS side).
2. `AvatarOverlay.tsx` (the actual S1-05 deliverable), wired into `Player.tsx`.

**Explicitly NOT in this story's scope** (Dev 1's follow-up, tracked in the proposal doc, not blocking this story): implementing `GET /media/signed-url` for real, a static-image clip variant on `HeyGenAvatarProvider`, and wiring `package_builder_node` to actually populate the 3 new fields. Until that lands, every real lesson's avatar fields will be absent/`null` — `AvatarOverlay.tsx` must handle that as its normal, expected, and only currently-reachable case. This story still ships real, tested, working code; it just won't be visibly active for a real student until Dev 1's part lands too.

## A corrected design decision vs. the proposal draft (found during this story's own research, not assumed)

The proposal's JSON-schema diff marks the 3 new fields as `required` (present-but-nullable). Re-reading `apps/api/tests/unit/test_lesson_schema.py` before touching anything surfaced a **directly relevant, already-fixed regression of exactly this shape**: `tier` was originally `required` in the JSON schema too, and `test_lesson_metadata_omitting_tier_validates_against_raw_json_schema`'s own docstring documents the resulting bug verbatim — *"a metadata dict that omits `tier` entirely must validate against the raw JSON schema... Before this story, `tier` was in LessonMetadata's `required` array — a payload omitting it failed schema validation here while silently defaulting to 'T2' in Pydantic (a real 3-way contract drift, not just a hypothetical)."* Story 2-25 fixed it by moving `tier` OUT of `required`, keeping only the Pydantic/JSON-schema `default`.

Any retroactively-added field hits this same problem: old stored lessons and old test fixtures never had the key at all, so marking it `required` breaks raw (non-Pydantic-mediated) JSON-schema validation of that pre-existing data — exactly the failure mode `tier`'s regression test now guards against. The 3 avatar fields are being added retroactively too, so **this story follows the corrected `tier` pattern instead of the proposal's original draft**: NOT in any `required` array, with a JSON-schema `"default": null` and a Pydantic `= None` default — not the proposal's literal "required" diff. Functionally equivalent for every *newly validated* lesson (the field is always present with a real or `null` value once it passes through Pydantic), but safe for old data and existing fixtures. Confirmed zero-risk by checking every call site: no direct `LessonPackage(...)` Pydantic constructor calls exist outside `apps/api/app/schemas/lesson.py` itself (only `.model_validate(dict)`, which fills defaults for missing keys); on the frontend, only `apps/web/src/mocks/data/lessonPackage.ts` and `player.machine.test.ts::makeLesson()` construct a full `LessonPackage`-shaped object, and an optional TS field (matching `tier?:`) requires zero changes to either.

## Acceptance Criteria

1. **AC-1** — `packages/shared/types/lesson.ts`'s `LessonPackage` gains `avatar_intro_url?: string | null`, `avatar_static_url?: string | null`, `avatar_outro_url?: string | null` — optional keys, matching `tier?:`'s existing pattern exactly, NOT required.
2. **AC-2** — `packages/shared/lesson_package.schema.json` gains matching `avatar_intro_url`/`avatar_static_url`/`avatar_outro_url` properties (`oneOf [{type: string, format: uri}, {type: null}]`, `"default": null`) on the root `LessonPackage` definition — NOT added to the root `required` array (see corrected-design note above).
3. **AC-3** — `apps/api/app/schemas/lesson.py`'s `LessonPackage` Pydantic model gains the same 3 fields as `str | None = None` — matching the *shape* of `LessonMetadata.tier`'s pattern (optional-with-a-default, not a bare required field), not its literal default value (`tier` defaults to `"T2"`, a real value; these default to `None` since there's no real value to fall back to yet). No other file in `apps/api` needs to change for this story (`package_builder_node` population is explicitly out of scope — see Story Notes).
4. **AC-4** — `apps/api/tests/unit/test_lesson_schema.py` gains a regression test mirroring `test_lesson_metadata_omitting_tier_validates_against_raw_json_schema` for the new fields: a `MINIMAL_PACKAGE_DICT` that omits all 3 avatar keys entirely must still validate against the raw JSON schema (proving they are genuinely not required, not just optional-with-a-default that nobody's tested against the schema directly).
5. **AC-5** — New `AvatarOverlay.tsx` component: plays `avatar_intro_url` (if present) automatically before the first audio segment begins; shows `avatar_static_url` (if present) as a persistent still image during the lesson body; plays `avatar_outro_url` (if present) after `store.endLesson()` fires. If a given URL is absent (`undefined`) or `null`, that specific piece is skipped silently — the player never blocks or waits on any avatar asset. Matches the original S1-05 acceptance criteria in `docs/dev2-sprint-tracker.md`.
6. **AC-6** — `AvatarOverlay` is a normal (non-`dynamic()`) import inside `Player.tsx`. **Corrected during implementation:** the original tracker sketch predates the current `PlayerLoader → Player` architecture and assumed `AvatarOverlay` would need its own `ssr: false` wrapper; `PlayerLoader.tsx`'s dynamic import of `Player` itself already covers every child in the tree (its own comment: *"This is the ONLY dynamic() call in the player stack; child components import normally"*) — matching how `AudioTimeline`/`SlideRenderer`/etc. are already imported. A second `dynamic()` call here would violate that established convention for no benefit.
7. **AC-7** — No regression to existing player behavior: a lesson with all 3 avatar fields absent (the only reachable case until Dev 1's backend work lands) renders and plays exactly as it does on `main` today, byte-for-byte.
8. **AC-8** — Tests: schema round-trip test (AC-4), `AvatarOverlay.tsx` component tests covering intro-plays/static-shows/outro-plays/all-three-absent-skips-silently/never-blocks-lesson-start. Full `apps/web` suite green, `tsc --noEmit` clean, `eslint` clean on every touched file. `apps/api`'s full unit suite has 23 pre-existing failures unrelated to this story (confirmed identical on `main` and this branch, independently by 2 reviewers) — "no new failures introduced" is the accurate bar here, not "green," since the suite wasn't fully green before this story either.

## Tasks / Subtasks

- [x] Task 1 (AC: 1, 2, 3, 4): Apply the corrected-design schema change across all 3 mirrors (`lesson.ts`, `lesson_package.schema.json`, `apps/api/app/schemas/lesson.py`); add the omitted-keys regression test.
  - [x] 1.1 RED: failing schema round-trip test for the omitted-keys case.
  - [x] 1.2 GREEN: implement; run full `apps/api` suite to confirm zero regressions.
- [x] Task 2 (AC: 5, 6, 7): Build `AvatarOverlay.tsx`, wire into `Player.tsx`.
  - [x] 2.1 RED: failing tests for each AC-5 behavior.
  - [x] 2.2 GREEN: implement.
- [x] Task 3 (AC: 8): Full `apps/web` and `apps/api` suites green; `tsc --noEmit` clean; `eslint` clean on every touched file.

## Dev Notes

### What NOT to do

- Do NOT mark the 3 new fields `required` in the JSON schema — see the corrected-design section above; this would repeat the exact `tier` regression Story 2-25 already fixed.
- Do NOT implement `GET /media/signed-url` for real, add a static-image variant to `HeyGenAvatarProvider`, or wire `package_builder_node` to populate these fields — all explicitly Dev 1's follow-up, out of scope here (tracked in `docs/proposals/avatar-fields-schema-change.md`'s "what still needs to happen" list).
- Do NOT call HeyGen's live API from the frontend or block lesson start waiting on any avatar asset — CLAUDE.md's avatar row is explicit: "No live HeyGen per lesson."

### Testing standards

Vitest + Testing Library for `AvatarOverlay.tsx`, matching existing player component test conventions. Pytest for the schema/Pydantic side, matching `test_lesson_schema.py`'s existing structure exactly (reuse `MINIMAL_PACKAGE_DICT`, add a variant/test analogous to the tier one).

### References

- [Source: docs/proposals/avatar-fields-schema-change.md] — the original proposal this story implements, with one corrected design decision (see above).
- [Source: apps/api/tests/unit/test_lesson_schema.py] — the `tier` regression precedent this story's corrected design follows.
- [Source: apps/api/app/providers/avatar/heygen.py] — confirms the real backend shape (plain signed URL string, `intro`/`outro` only, no static variant yet) that `AvatarOverlay.tsx` should expect once Dev 1's follow-up lands.
- [Source: docs/dev2-sprint-tracker.md S1-05] — original acceptance criteria this story fulfills.

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-07-29 | Story created after user-confirmed cross-team sign-off (verbal, on behalf of all 4 devs) on `docs/proposals/avatar-fields-schema-change.md`. Branch `sprint1/s1-5-avatar-overlay` off `main`. Corrected the proposal's schema design (required → optional/defaulted) after finding the directly-relevant `tier`/Story 2-25 regression precedent in `test_lesson_schema.py`. | Dev 2 |
| 2026-07-29 | Implemented all 3 tasks. `apps/web` full suite 54 files / 540 tests passing, `tsc --noEmit` clean, `eslint` 0 errors (1 pre-existing-pattern warning, matches `SlideRenderer.tsx`'s identical `<img>` warning). `apps/api` full unit suite: same 23 pre-existing failures confirmed present on `main` before this story's changes too (unrelated — DNA fusion/growth, tutor service, eval runner — none touch the schema); zero new failures introduced. | Dev 2 |
| 2026-07-29 | 3-agent code review round. 6 actionable findings fixed (video watchdog timeout, audioError-yield guard, honest format-checker fix, static-image error handling, effect dependency-array fix, stale doc claims corrected in both this story and the original proposal) plus 2 doc-precision wording fixes. 2 findings deliberately not actioned (documented design trade-offs). `apps/web` full suite now 54 files / 544 tests, `AvatarOverlay.test.tsx` 19 → 23 tests. `apps/api` re-verified: same 23 pre-existing failures, zero new. | Dev 2 |

## Dev Agent Record

### Implementation Plan

- Verified the corrected schema design is genuinely safe before writing any code: grepped for every `LessonPackage(` direct Pydantic constructor call (none outside `schemas/lesson.py` itself — all real usage goes through `.model_validate(dict)`, which fills in defaults for omitted keys) and every full `LessonPackage`-shaped TS object literal (`apps/web/src/mocks/data/lessonPackage.ts`, `player.machine.test.ts::makeLesson()` — both fine with an optional field, zero changes needed).
- Added the 3 fields as optional/defaulted across all 3 mirrors (`lesson.ts`, `lesson_package.schema.json`, `apps/api/app/schemas/lesson.py`), explicitly NOT in either `required` array — confirmed via a new regression test mirroring the existing tier one that a `LessonPackage` dict omitting all 3 keys still validates against the raw JSON schema.
- Designed `AvatarOverlay.tsx` to be entirely self-contained (reads `usePlayerStore` directly, takes only `lesson` as a prop) so it requires zero changes to any of `Player.tsx`'s existing status-based conditionals — the intro/outro overlays visually layer on top of whatever Player already renders (IDLE placeholder / ENDED screen) rather than requiring lifted state, keeping AC-7 (zero regression when avatar fields are absent) trivially true by construction.
- Made both intro and outro equally defensive against browser autoplay-blocking (a real risk for any non-muted `<video autoplay>`): both drive `.play()` manually via a ref + effect and catch a rejected promise, skipping/unmounting gracefully rather than leaving the student stuck behind an overlay that silently never started.
- Deliberately did not add a second `dynamic(..., { ssr: false })` wrapper — `PlayerLoader.tsx`'s existing one already covers every child in the `Player` tree; found and corrected this over-assumption from the original story draft before writing the component.

### Completion Notes

- All 3 tasks complete, all ACs (1–8) satisfied.
- `apps/web`: 54 files, 540 tests, all passing. `tsc --noEmit` clean. `eslint`: 0 errors on all touched files.
- `apps/api`: `test_lesson_schema.py` 34/34 passing (4 new avatar-specific tests — corrected here per Acceptance Auditor's review finding; an earlier draft of this note miscounted as 5). Full unit suite: same 23 pre-existing, unrelated failures confirmed present on both `main` and this branch (identical failure names, verified independently by 2 reviewers); zero new failures.
- This story's frontend half is fully real, tested, working code — but not yet visibly active for any real student, since `package_builder_node` doesn't populate the 3 new fields yet (Dev 1's separate follow-up, out of scope here by design, tracked in `docs/proposals/avatar-fields-schema-change.md`).

### File List

- `packages/shared/types/lesson.ts` (MODIFIED — 3 new optional `LessonPackage` fields)
- `packages/shared/lesson_package.schema.json` (MODIFIED — 3 new optional/defaulted properties, not in `required`)
- `apps/api/app/schemas/lesson.py` (MODIFIED — 3 new `str | None = None` fields on the `LessonPackage` Pydantic model)
- `apps/api/tests/unit/test_lesson_schema.py` (MODIFIED — 4 new avatar-field tests; review round: format-checker honesty fix)
- `apps/web/src/components/player/AvatarOverlay.tsx` (NEW; review round: watchdog timeout, audioError yield, static-image error handling)
- `apps/web/src/components/player/Player.tsx` (MODIFIED — mounts `AvatarOverlay`)
- `apps/web/src/__tests__/components/player/AvatarOverlay.test.tsx` (NEW — 19 tests, +4 in review round = 23)
- `docs/proposals/avatar-fields-schema-change.md` (MODIFIED — review round: corrected stale `GET /media/signed-url`/`avatar-clips` claim)

## Senior Developer Review (AI)

**Date:** 2026-07-29
**Outcome:** Changes Requested → all actionable findings resolved this session.
**Reviewers:** Blind Hunter (diff-only), Edge Case Hunter (diff + repo access), Acceptance Auditor (diff + spec + context docs) — per CLAUDE.md's BMAD Code Review Gate.

### Findings

| # | Severity | Source | Finding | Resolution |
|---|----------|--------|---------|------------|
| 1 | Medium/High (Blind Hunter, not corroborated but a real design gap) | Blind Hunter | No timeout/watchdog for a hung (not failed) intro/outro video load — a network stall that never fires `onEnded`/`onError` would leave the full-screen overlay stuck indefinitely, contradicting the component's own "never block" design intent. | Fixed — added an 8-second watchdog `setTimeout` to both intro and outro effects, cleared on `onEnded`/`onError`; forces the same graceful skip/unmount path if neither fires in time. New tests cover both. |
| 2 | Medium (Edge Case Hunter, code-verified) | Edge Case Hunter | The intro overlay (`z-30`) can render simultaneously with a genuine audio-load error screen (`z-20`, not gated on `status`), blocking the Retry button for the intro's entire duration. Currently unreachable (avatar fields are always absent), but will go live the moment Dev 1's pipeline wiring lands. | Fixed — intro's render condition now also requires `!audioError`, so a genuine recovery need always takes priority over the avatar feature. New test covers it. |
| 3 | Medium (corroborated 2/2 — Blind Hunter + Edge Case Hunter) | Blind Hunter, Edge Case Hunter | `"format": "uri"` on the 3 new JSON-schema properties is not actually enforced — `jsonschema.validate()` treats `format` as a no-op annotation without an explicit `FormatChecker`, so the "round trip through JSON schema" test's name implied a constraint it didn't verify. | Investigated fully: even with `format_checker=jsonschema.FormatChecker()` passed, this environment has no `"uri"` checker registered at all (confirmed via `FormatChecker().checkers` — needs the optional `rfc3987` package, not installed). An initial fix attempt (a negative test asserting a non-URI string gets rejected) failed for exactly this reason and was removed — adding a new dependency to enforce this is a cross-team `pyproject.toml` decision, out of scope here. Landed the honest fix instead: the test now passes a `FormatChecker` (exercises the intended code path) with a comment explicitly documenting that URI format is currently unenforced in this environment, rather than a test name implying enforcement that doesn't exist. |
| 4 | Low (Blind Hunter only) | Blind Hunter | The static avatar corner thumbnail had no `onError` handling, unlike intro/outro — an expired signed URL or 404 would show a broken-image icon pinned in the corner for the entire lesson body. | Fixed — added `onError` that hides the thumbnail entirely on failure, matching intro/outro's degrade-gracefully pattern. New test covers it. |
| 5 | Low (Edge Case Hunter only, currently unreachable) | Edge Case Hunter | The intro/outro `useEffect` dependency arrays omitted the URL values themselves (`introUrl`/`outroUrl`), so a same-object-reference lesson update that changed only the URL value (not identity) wouldn't re-trigger a play attempt. Currently protected only by an unrelated gating decision (retry can't fire during IDLE/ENDED), not by design. | Fixed defensively — added `introUrl`/`outroUrl` to their respective effects' dependency arrays. |
| 6 | Low (corroborated 2/2 — Acceptance Auditor + Edge Case Hunter) | Acceptance Auditor, Edge Case Hunter | The story's own background research claimed `GET /media/signed-url` was still a 501 stub and `avatar-clips` was still in the bucket allowlist — both false against current `main` (the endpoint is fully implemented; `avatar-clips` was deliberately removed from the allowlist by Story 2-25 since its flat clip paths always 404 the ownership check). Doesn't affect any AC (this story correctly never touches `media/router.py`), but is a real inaccuracy in the story's "verified directly against main" claim. | Fixed — corrected both this story's background section and the original `docs/proposals/avatar-fields-schema-change.md`, with a note that the proposal's signed-URL-expiry "open question" is now more urgent than originally framed (the signed-URL path for this bucket is currently non-functional, not just risky). |
| 7 | Low (Acceptance Auditor only) | Acceptance Auditor | Story's Completion Notes claimed "5 new avatar-specific tests" against an actual, verified count of 4 (matching the File List, which was correct). | Fixed — corrected the count in Completion Notes. |
| 8 | Low (Acceptance Auditor only, wording only) | Acceptance Auditor | AC-3's phrasing ("matches `tier`'s existing default pattern") was loosely worded — `tier` defaults to `"T2"`, a real value, not `None`; the pattern being matched is "optional-with-a-default," not the literal default value. AC-8's "Full apps/api suite green" is also imprecise given 23 pre-existing, unrelated failures. | Fixed — reworded both ACs for precision; no code change, wording only. |
| 9 | Medium (Blind Hunter only, design trade-off, not actioned) | Blind Hunter | Non-muted `<video autoplay>` will very likely fail under real browser autoplay policy for a genuine first-time page load, meaning the "talking avatar intro" may rarely autoplay in production. | Not actioned — muting would silence the avatar entirely, defeating the feature's purpose, and the existing graceful-catch-and-skip behavior already means this never produces a visible bug, only a less-effective feature. Noted as a known limitation for whoever picks up the backend follow-up; not a defect in this story's own code. |
| 10 | Low (Edge Case Hunter only, not actioned) | Edge Case Hunter | A student can click the (still-live) Play button during the intro, interrupting it mid-clip with no completion. | Not actioned — intentional. Treating this as a de-facto "skip intro" affordance is better UX than trapping a student behind an unskippable video, and it doesn't crash or leave any stuck state (confirmed by the reviewer itself). |

### Non-issues independently re-verified

- Cross-team contract safety confirmed by 2 independent reviewers: zero direct `LessonPackage(...)` Pydantic constructor calls exist outside `schemas/lesson.py` itself; both `apps/web` full-`LessonPackage`-literal sites are unaffected by an optional field; `apps/api` full suite shows the identical 23 pre-existing failures on both `main` and this branch, with the branch's +4 passing tests exactly matching the new avatar tests.
- The `tier`/Story 2-25 regression precedent this story's design is based on was independently confirmed real (both reviewers read `docs/stories/2-25-sprint2-audit-gapfix-dev1-items.md` and the current schema directly) and the analogy sound.
- No `dynamic()`/SSR regression, no `undefined`/`null`/`""` mishandling anywhere in `AvatarOverlay.tsx`, no double-`play()`/race condition (`player.machine.ts`'s `play()` is idempotent), `package_builder_node` genuinely has zero avatar references.
- The outro overlay genuinely blocks the ENDED screen's links (correct, intended behavior — not a bug).
