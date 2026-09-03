---
title: "Story 2-56 — Performance: Code Splitting + Lazy Loading (S4-05)"
status: in-progress
owners: [Dev 2]
sprint: 4
---

# Story 2-56 — Performance: Code Splitting + Lazy Loading

## Problem Statement

`docs/dev2-sprint-tracker.md`'s S4-05 line lists four bullets with no prior story file, no
status marker, and no grounding against the real code — it was pure backlog text. Grounded
research (this story) found the real state differs from what the bullet list implies:

1. **MediaPipe WASM bundle** — already lazy-loaded, already consent-gated. `useAttentionMonitor.ts`
   already does `await import('@mediapipe/tasks-vision')` inside `createFaceLandmarker()`, gated on
   `consentStatus === 'accepted' && hasReachedTeaching` (line ~174). No static import of
   `@mediapipe/tasks-vision` exists anywhere in `apps/web/src`. **This bullet is already satisfied —
   closing it as verified, not implementing anything new.**
2. **Chart library (recharts) dynamic import** — genuinely NOT done. `AttentionChart.tsx` imports
   `recharts` statically; `SessionReport.tsx` imports `AttentionChart` statically and renders it
   conditionally (`report.ces_timeline !== null`). Next.js route-based splitting already keeps
   `recharts` out of every OTHER route's bundle (no other file imports it), but within
   `/reports/[sessionId]` itself, `recharts`'s JS is still fetched/parsed on every page load
   regardless of whether `ces_timeline` is ever non-null for that session. **This is the one bullet
   with real, actionable scope.**
3. **HeyGen video preload** — moot. HeyGen was removed entirely as dead/unwired code (D144,
   2026-09-02, `docs/DEFECT-REGISTER.md`). There is no HeyGen video anywhere in the lesson page to
   preload. **Dropped, not implemented — closing as not-applicable, not silently deleting the line
   with no record.**
4. **Lighthouse score target `/lesson/[id]` > 70** — no Lighthouse tooling exists anywhere in the
   repo (no config, no CI job, no npm script, no prior recorded score — confirmed by search). The
   route itself sits behind Supabase auth + a real generated `LessonPackage`; a true authenticated
   Lighthouse run needs a real signed-in session with a real completed lesson, which this session
   does not have standing credentials for (matches the established "no test credentials" limitation
   already recorded in `docs/DEPLOYMENT-OPS-NOTES.md`'s Playwright section). **Scoped down to what is
   actually verifiable without new credentials**: a real `next build` bundle-size comparison
   (before/after AC1's fix) as the concrete, checkable performance evidence, plus a best-effort
   Lighthouse run against whatever the route actually serves without auth — reported honestly for
   what it does and doesn't prove, not presented as a verified `/lesson/[id] > 70` claim.

## Acceptance Criteria

- **AC1** — `AttentionChart` is loaded via `next/dynamic` (`ssr: false`, matching this repo's one
  existing convention for a heavy client-only component — `PlayerLoader.tsx`'s `Player` dynamic
  import) inside `SessionReport.tsx`, with a lightweight loading skeleton matching the chart's real
  layout footprint (avoids layout shift). `recharts`' JS is not fetched until the dynamic import
  actually resolves, not merely not-SSR'd.
- **AC2** — MediaPipe lazy-loading is verified (not re-implemented) and documented as already
  satisfying this bullet, with the exact file/line evidence, in this story's Dev Notes — so future
  readers don't reopen already-closed work.
- **AC3** — The HeyGen-preload bullet is recorded as dropped/not-applicable (D144 cross-referenced),
  not silently removed with no trace.
- **AC4** — A real `next build` is run before and after AC1's change; the `/reports/[sessionId]`
  route's reported First Load JS size is captured both times as concrete before/after evidence.
- **AC5** — A best-effort Lighthouse run is attempted against `/lesson/[id]` using the locally
  installed Chrome; whatever is actually measurable without a real authenticated session is
  reported honestly, including the limitation itself if a full authenticated measurement isn't
  reachable — never a fabricated or assumed score.
- **AC6** — Existing `SessionReport.test.tsx`/`AttentionChart.test.tsx` tests still pass; no new
  test needed for a pure loading-strategy change (the component's own behavior — props, rendering
  logic — is unchanged, only when its JS is fetched).
- **AC7** — `tsc --noEmit` and targeted `eslint` clean on touched files; full frontend suite green.

## Scale & Load

1. **Unit of work / range**: one `/reports/[sessionId]` page load, per session, per user. Range:
   0 to N intervention events / timeline points per `ces_timeline` (already bounded upstream by
   session duration — not a new bound introduced here).
2. **Fixed budgets vs variable input**: N/A — this story changes WHEN a fixed JS bundle loads, not
   any data-shaped budget. No new fixed budget introduced.
3. **Scope of limits**: N/A — client-side bundle-loading behavior, no server-side or per-user/
   per-instance limit involved.
4. **Unbounded reads/writes**: none — no new Supabase read/write introduced; purely a client bundle-
   splitting change.
5. **Inherited caps re-derived**: N/A — no cap inherited or changed.
6. **Check-then-act under concurrency**: N/A — no shared mutable state; `next/dynamic` is a pure
   client-side module-loading concern, not a concurrency-sensitive one.

(Five of six questions are genuinely N/A for a pure frontend code-splitting change — stated with
reason per `docs/SCALE-CONTRACT.md`'s own rule that a bare "N/A" is a missing answer.)

## Dev Notes

- MediaPipe evidence: `apps/web/src/hooks/useAttentionMonitor.ts` — dynamic `import('@mediapipe/tasks-vision')`
  inside `createFaceLandmarker()`, gated on `consentStatus === 'accepted' && hasReachedTeaching`.
  `AttentionConsentModal.tsx`'s own test asserts its source contains no `@mediapipe` reference at all
  (proves the modal itself never eagerly pulls in the WASM bundle either).
- Chart evidence: `apps/web/src/components/reports/AttentionChart.tsx` (static `recharts` import) ←
  `apps/web/src/components/reports/SessionReport.tsx` (static `AttentionChart` import) ←
  `apps/web/src/app/reports/[sessionId]/page.tsx` (the only real route reaching either file).
- `PlayerLoader.tsx`'s existing `dynamic(() => import('./Player'), { ssr: false, loading: ... })`
  is the pattern this story's AC1 mirrors.

## References

- [Source: apps/web/src/hooks/useAttentionMonitor.ts] — MediaPipe dynamic import + consent gate
- [Source: apps/web/src/components/reports/AttentionChart.tsx] — static recharts import
- [Source: apps/web/src/components/reports/SessionReport.tsx] — static AttentionChart import, conditional render
- [Source: apps/web/src/components/player/PlayerLoader.tsx] — existing `next/dynamic` convention this story mirrors
- [Source: docs/DEFECT-REGISTER.md#D144] — HeyGen removal, closes the preload bullet as moot
- [Source: docs/DEPLOYMENT-OPS-NOTES.md] — "no test credentials" limitation this story's Lighthouse AC inherits
