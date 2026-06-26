---
story_id: "3-7"
title: "Sprint 0 Closure — Fix Onboarding Route Group + Resolve PR Conflict"
status: "in-progress"
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
- [ ] AC1: `apps/web/src/app/(app)/onboarding/page.tsx` deleted from repo
- [ ] AC2: `apps/web/src/app/onboarding/page.tsx` created with identical content EXCEPT:
  - Line 6 changed: `import api from '@/lib/api'` (NOT `import { apiClient } from '@/lib/api/client'`)
  - Line 86 changed: `await api.post(...)` (NOT `await apiClient.post(...)`)
- [ ] AC3: The `(app)/` directory is completely removed (no empty group remains)
- [ ] AC4: The onboarding page still has all 20 questions, 3 dimensions intact
- [ ] AC5: The submit payload shape `{ responses: [...] }` is unchanged

### Fix 2 — pnpm conflict in PR #13 (dev2/sprint-1)
- [ ] AC6: `dev2/sprint-1` has `origin/main` merged into it (all Dev 4 + Dev 3 sprint0 work included)
- [ ] AC7: `pnpm-lock.yaml` regenerated clean (no conflict markers)
- [ ] AC8: `dev2/sprint-1` pushes cleanly to origin

### Fix 3 — Sprint 0 fully closed
- [ ] AC9: Sprint 0 Task 7 marked `[x]` with Dev 2 sign-off noted in tracker
- [ ] AC10: Sprint 0 dashboard shows 7/7 Done, 0 Remaining

## Tasks

- [ ] T1: Create `apps/web/src/app/onboarding/page.tsx` with fixed import + api call
- [ ] T2: Delete `apps/web/src/app/(app)/onboarding/page.tsx`
- [ ] T3: Git rm the `(app)/` directory (ensure it's gone from tracked files)
- [ ] T4: Run backend unit tests: `pytest -m unit` from `apps/api/` — must still be 14/14 pass
- [ ] T5: Commit onboarding fix on `sprint0/s0-7-onboarding-fix`
- [ ] T6: Push branch, merge to main via PR
- [ ] T7: Checkout `dev2/sprint-1` locally, merge `origin/main` into it
- [ ] T8: Delete `pnpm-lock.yaml`, run `pnpm install` to regenerate clean
- [ ] T9: Commit pnpm fix, push `dev2/sprint-1` to origin
- [ ] T10: Update tracker: Task 7 done with sign-off, Sprint 0 complete

## Dev Notes

- Use `import api from '@/lib/api'` (default export) — `lib/api.ts` exports axios instance as default
- API call stays identical: `api.post('/api/assessment/onboarding/submit', { responses })`
- No logic changes — only import line and call site change
- `(app)/` has no layout.tsx so deleting it is safe; URL `/onboarding` still resolves correctly
- Backend tests are unaffected (frontend-only change)
- For pnpm: `pnpm install` regenerates lock from all `package.json` files — merges both sides' packages
- Do NOT manually edit `pnpm-lock.yaml` — always regenerate via `pnpm install`

## Dev Agent Record

### Change Log
| File | Action | Reason |
|------|--------|--------|
| `apps/web/src/app/(app)/onboarding/page.tsx` | DELETE | Wrong route group — no (app) group in project structure |
| `apps/web/src/app/onboarding/page.tsx` | CREATE | Correct location per Dev 2 review |
| `dev2/sprint-1 pnpm-lock.yaml` | REGENERATE | Resolve conflict from Dev 4's pnpm changes on main |
