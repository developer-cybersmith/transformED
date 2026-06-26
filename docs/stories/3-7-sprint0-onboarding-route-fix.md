---
story_id: "3-7"
title: "Sprint 0 Closure — Fix Onboarding Route Group + Resolve PR Conflict"
status: "done"
branch: "sprint0/s0-7-onboarding-fix"
baseline_commit: "e709e71"
---

# Story 3.7 — Sprint 0 Closure: Fix Onboarding Route + Merge Conflict

## Context

Sprint 0 Task 7 (OpenAPI spec published) is code-complete and pushed. Dev 2 reviewed the
spec, confirmed all 5 endpoint shapes, and gave sign-off with ONE blocker:

> "Your onboarding page is at `app/(app)/onboarding/page.tsx` but we have no `(app)` route
> group — our structure only has `(auth)/` and `(dashboard)/`. It'll 404 on merge. Please
> move it to `app/onboarding/page.tsx` and change line 6 from
> `import { apiClient } from '@/lib/api/client'` to `import api from '@/lib/api`."

Additionally, Dev 2's Sprint 1 PR (#13, branch `dev2/sprint-1`) has a merge conflict because:
- Dev 4 merged `pnpm-lock.yaml` + `pnpm-workspace.yaml` to main (session-lifecycle work)
- Dev 2's branch also adds/modifies these files (they added frontend packages)
- Both sides added `pnpm-lock.yaml` with different content → conflict in PR #13

**Investigation findings (parallel agent run 2026-06-26):**
- `(app)/onboarding/page.tsx` IS tracked on main (added by dev3-sprint0-task4)
- `(app)/` route group has NO `layout.tsx` — it provides zero structural value
- Dev 2's `dev2/sprint-1` branch does NOT have `(app)/onboarding/page.tsx` (their branch predates it)
- The only merge conflict in PR #13 is `pnpm-lock.yaml` / `pnpm-workspace.yaml`
- Fixing our file first, then merging main into dev2/sprint-1 + `pnpm install` clears everything

## User Story

As Dev 3 completing Sprint 0, I fix the onboarding page route group and broken import per
Dev 2's review, and help resolve the pnpm conflict in Dev 2's PR, so that all Sprint 0 PRs
can merge cleanly and Sprint 0 is fully closed.

## Acceptance Criteria

### Fix 1 — Onboarding page route + import (Dev 3 owns this file)
- [x] AC1: `apps/web/src/app/(app)/onboarding/page.tsx` deleted from repo
- [x] AC2: `apps/web/src/app/onboarding/page.tsx` created with identical content EXCEPT:
  - Line 6 changed: `import { api } from '@/lib/api'` (named export, curly braces required)
  - Line 86 changed: `await api.post('assessment/onboarding/submit', { responses })` (no leading slash, no `/api/` prefix — avoids URL doubling with baseURL)
- [x] AC3: The `(app)/` directory is completely removed (no empty group remains)
- [x] AC4: The onboarding page still has all 20 questions, 3 dimensions intact
- [x] AC5: The submit payload shape `{ responses: [...] }` is unchanged

### Fix 2 — pnpm conflict in PR #13 (dev2/sprint-1)
- [x] AC6: `dev2/sprint-1` has `origin/main` merged into it (all Dev 4 + Dev 3 sprint0 work included)
- [x] AC7: `pnpm-lock.yaml` regenerated clean (no conflict markers)
- [x] AC8: `dev2/sprint-1` pushes cleanly to origin

### Fix 3 — Sprint 0 fully closed
- [x] AC9: Sprint 0 Task 7 marked `[x]` with Dev 2 sign-off noted in tracker
- [x] AC10: Sprint 0 dashboard shows 7/7 Done, 0 Remaining

## Tasks

- [x] T1: Create `apps/web/src/app/onboarding/page.tsx` with fixed import + api call
- [x] T2: Delete `apps/web/src/app/(app)/onboarding/page.tsx`
- [x] T3: Git rm the `(app)/` directory (ensure it's gone from tracked files)
- [x] T4: Run backend unit tests: `pytest -m unit` from `apps/api/` — 14/14 pass confirmed
- [x] T5: Commit onboarding fix on `sprint0/s0-7-onboarding-fix`
- [x] T6: Push branch, merge to main via PR #14
- [x] T7: Checkout `dev2/sprint-1` locally, merge `origin/main` into it
- [x] T8: Delete `pnpm-lock.yaml`, run `pnpm install` to regenerate clean
- [x] T9: Commit pnpm fix, push `dev2/sprint-1` to origin (PR #13 resolved + merged)
- [x] T10: Update tracker: Task 7 done with sign-off, Sprint 0 complete

## Dev Notes

- CORRECTION vs. story draft: `lib/api.ts` uses `export const api` (NAMED export). Import must be
  `import { api } from '@/lib/api'` with curly braces — NOT `import api from '@/lib/api'` (default syntax).
  The draft Dev Notes were incorrect. Named import with `{ }` is required.
- API call: `api.post('assessment/onboarding/submit', { responses })` — no leading slash prevents
  axios from doubling the `/api` segment that already exists in baseURL (`http://localhost:8000/api`).
- `(app)/` has no layout.tsx so deleting it is safe; URL `/onboarding` still resolves correctly
- Backend tests unaffected (frontend-only change for T1-T5)
- For pnpm: `pnpm-workspace.yaml` had placeholder text on Dev 2's branch (`set this to true or false`);
  resolved by taking the concrete boolean values from main (`sharp: false`, `unrs-resolver: false`)
- Do NOT manually edit `pnpm-lock.yaml` — always regenerate via `pnpm install`

## Dev Agent Record

### Agent Model
claude-sonnet-4-6

### Debug Log
| Issue | Root Cause | Resolution |
|-------|------------|------------|
| Named vs default import | `lib/api.ts` uses `export const api` (named), not `export default` | Changed to `import { api }` with curly braces |
| URL doubling `/api/api/...` | axios `combineURLs` appends relative path to baseURL; leading `/` causes double segment | Changed to relative path `assessment/onboarding/submit` |
| `pnpm-workspace.yaml` placeholder | Dev 2's branch had `sharp: set this to true or false` (invalid YAML bool) | Took concrete `false` values from main |
| `pnpm-lock.yaml` add/add conflict | Both main and dev2/sprint-1 added the file with different content | Deleted file, `pnpm install` regenerated from merged package.json files |

### Completion Notes
- File moved via git rename (98% similarity detected by git)
- All 20 questions (8 cognitive c1-c8, 5 emotional e1-e5, 7 self_direction s1-s7) intact after move
- `pnpm install` resolved 677 packages (57.8s) — regenerated lock compatible with both branches' packages
- PR #14 (`sprint0/s0-7-onboarding-fix`) merged to main — onboarding page at correct root-level path
- PR #13 (`dev2/sprint-1`) conflict resolved, pushed, and merged to main
- Git log confirms both merges: `fcd4b15` (PR #14) and `96a50ad` (PR #13)
- BMAD post-merge audit (2026-06-27): Dev 2 integration agent confirmed zero shape mismatches between
  `assessment.ts` and `openapi-assessment.json`; onboarding page named import and API path verified correct

### File List
| File | Action |
|------|--------|
| `apps/web/src/app/onboarding/page.tsx` | CREATED (renamed from `(app)/onboarding/page.tsx`) |
| `apps/web/src/app/(app)/onboarding/page.tsx` | DELETED via git rm |
| `pnpm-workspace.yaml` (on dev2/sprint-1) | CONFLICT RESOLVED — concrete bool values from main |
| `pnpm-lock.yaml` (on dev2/sprint-1) | DELETED + REGENERATED via `pnpm install` |

### Change Log
| Date | Change | Reason |
|------|--------|--------|
| 2026-06-26 | Moved onboarding page from `(app)/` route group to root `app/` | `(app)` route group has no layout.tsx — 404 on merge per Dev 2 review |
| 2026-06-26 | Fixed import: `{apiClient}` from non-existent module → `{api}` named export | `lib/api.ts` exports named const `api`, not a default export |
| 2026-06-26 | Fixed API path: `/api/assessment/...` → `assessment/...` | Removes double `/api` segment caused by axios baseURL + leading slash combination |
| 2026-06-26 | Resolved pnpm-workspace.yaml conflict | Dev 2's branch had placeholder text; took concrete booleans from main |
| 2026-06-26 | Regenerated pnpm-lock.yaml via `pnpm install` | Add/add conflict from both branches adding the file independently |

## Senior Developer Review (AI)

**Outcome:** APPROVED
**Date:** 2026-06-27

All 10 ACs verified in filesystem and git log. Route move confirmed — `apps/web/src/app/(app)/` directory does not exist. Named import `{ api }` and relative URL path `assessment/onboarding/submit` confirmed in `apps/web/src/app/onboarding/page.tsx`. Both PRs (#13, #14) confirmed merged to main.

**Critical catch:** Story draft Dev Notes incorrectly said "default export" — implementation correctly used named export. This correction is documented above and must not be reverted. The `dev2-assessment-api-handoff.md` doc also shows the wrong default import syntax in one code example; flag for Sprint 2 cleanup.

**No action items.** Story 3.7 is complete.
