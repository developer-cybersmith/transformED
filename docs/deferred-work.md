# Deferred Work

## Deferred from: code review of 3-22-posthog-assessment-events (2026-07-03)

- **DEFER-001** — UUID `distinct_id` sent to PostHog with no erasure pathway for DPDP right-to-erasure. PostHog builds a persistent person profile keyed on the user's internal UUID; no code path calls PostHog's person-delete API when an account is deleted. Addressable in a dedicated DPDP compliance story before real-student launch.
- **DEFER-002** — Synchronous `posthog.capture()` called from async route handlers and service functions (no `asyncio.to_thread` guard). Current PostHog Python SDK v3 queues internally and returns in microseconds — no measurable event-loop impact today. Add `asyncio.to_thread` wrapper if SDK v4 changes flush semantics.

## Deferred from: code review of 2-42-attention-consent-modal (2026-08-06)

- **DEFER-003** — `useAttentionConsent`'s exported `consentStatus`/localStorage dismissal key are easy for a future dev to mistake for the real security-initialize gate, and the hook only re-reads Supabase on mount/user-change, not "every check" as AC-4's wording implies (`apps/web/src/hooks/useAttentionConsent.ts`). Applies to code (`AttentionMonitor`, S3-02) that doesn't exist yet — flag explicitly in that story's Dev Notes rather than fixing here.
- **DEFER-004** — Hook's Supabase mocks (`apps/web/src/__tests__/hooks/useAttentionConsent.test.ts`) are hand-shaped to match the implementation exactly, so no test can disconfirm a wrong assumption about the real `.maybeSingle()` response shape. Identical un-premise-tested pattern already shared by `proxy.ts`'s own tests — fixing only this one hook would be inconsistent; needs a project-wide register entry and a shape-premise test (same class of gap as D58/D59).
- **DEFER-005** — No ARIA modal semantics (`role="dialog"`, `aria-modal`, focus trap, Escape handling) on `AttentionConsentModal.tsx`, a legally-relevant DPDP consent dialog. Appears to be a gap shared by other modals in this codebase (e.g. `TeachBackModal`) — candidate for its own register entry covering all modals, not unique to this diff.
