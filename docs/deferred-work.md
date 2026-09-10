# Deferred Work

## Deferred from: code review of 3-22-posthog-assessment-events (2026-07-03)

- **DEFER-001** — UUID `distinct_id` sent to PostHog with no erasure pathway for DPDP right-to-erasure. PostHog builds a persistent person profile keyed on the user's internal UUID; no code path calls PostHog's person-delete API when an account is deleted. Addressable in a dedicated DPDP compliance story before real-student launch.
- **DEFER-002** — Synchronous `posthog.capture()` called from async route handlers and service functions (no `asyncio.to_thread` guard). Current PostHog Python SDK v3 queues internally and returns in microseconds — no measurable event-loop impact today. Add `asyncio.to_thread` wrapper if SDK v4 changes flush semantics.

## Deferred from: S3-02 AttentionMonitor (Story 2-44, 2026-08-10)

- **DEFER-012 / D66** — `apps/web/src/hooks/useAttentionMonitor.ts`'s `MODEL_ASSET_URL` points at a floating `float16/latest/face_landmarker.task` tag rather than a pinned MediaPipe model version. Now carries a real register ID — see `docs/DEFECT-REGISTER.md` **D66** for owner, severity, and trigger (Story 2-45 closed the missing-ID gap; the underlying floating-tag risk itself is still open). Originally allocated as D63, which collided with a pre-existing closed D63 on `sprint3-master`; corrected to D66 in Story 2-45's own code review.

## Deferred from: code review of 2-42-attention-consent-modal (2026-08-06)

- **DEFER-003** — `useAttentionConsent`'s exported `consentStatus`/localStorage dismissal key are easy for a future dev to mistake for the real security-initialize gate, and the hook only re-reads Supabase on mount/user-change, not "every check" as AC-4's wording implies (`apps/web/src/hooks/useAttentionConsent.ts`). Applies to code (`AttentionMonitor`, S3-02) that doesn't exist yet — flag explicitly in that story's Dev Notes rather than fixing here.
- **DEFER-004** — Hook's Supabase mocks (`apps/web/src/__tests__/hooks/useAttentionConsent.test.ts`) are hand-shaped to match the implementation exactly, so no test can disconfirm a wrong assumption about the real `.maybeSingle()` response shape. Identical un-premise-tested pattern already shared by `proxy.ts`'s own tests — fixing only this one hook would be inconsistent; needs a project-wide register entry and a shape-premise test (same class of gap as D58/D59).
- **DEFER-005** — No ARIA modal semantics (`role="dialog"`, `aria-modal`, focus trap, Escape handling) on `AttentionConsentModal.tsx`, a legally-relevant DPDP consent dialog. Appears to be a gap shared by other modals in this codebase (e.g. `TeachBackModal`) — candidate for its own register entry covering all modals, not unique to this diff.

## Deferred from: code review of 2-43-notifications-ui (2026-08-06)

> Renumbered DEFER-003 through DEFER-008 → DEFER-006 through DEFER-011 on merge into `sprint3-master` (2026-08-07): this branch forked from `main` before Story 2-42's DEFER-003/004/005 were added there, producing a collision — same recurring ID-collision pattern already seen with D57–D65 this sprint.

- **DEFER-006** — `useNotificationPreferences`'s PATCH failure handling collapses 503 (retryable)/500/401/403 (session-expired) into identical treatment (log + conditional rollback), with no retry-on-503 and no re-auth prompt on 401 (`apps/web/src/hooks/useNotificationPreferences.ts`). Matches how every other non-critical settings toggle in this codebase already behaves — a session-expiry UX improvement is cross-cutting, not specific to notifications.
- **DEFER-007** — No ARIA semantics (role="dialog", aria-modal, focus trap, Escape handling) on `NotificationSettingsModal.tsx`. Same gap as DEFER-005 (`AttentionConsentModal`). Needs a cross-cutting accessibility story covering all modals in the codebase.
- **DEFER-008** — `users.notification_preferences` JSONB column has no schema validation at the DB layer; any JSON shape is accepted. A server-side CHECK constraint or trigger could enforce the {lesson_updates, system_alerts, marketing_emails} key set. Low priority — only one server path writes this column and it validates via Pydantic before the write.
- **DEFER-009** — Supabase mock in `useNotificationPreferences.test.ts` hand-shapes the `.single()` response to exactly what the code expects; no test disconfirms a wrong assumption about the real Supabase response shape. Same class as DEFER-004. Project-wide pattern, not specific to this diff.
- **DEFER-010** — `useNotificationPreferences` reads the current preferences on mount and discards the result if the component unmounts before the async call completes (no abort controller or isMounted guard). Standard React async-on-mount gap, shared by all async hooks in this codebase.
- **DEFER-011** — Notification API endpoint (`PATCH /api/users/me/notifications`) has no rate limiting. Shared pattern with other profile-update endpoints — rate-limit coverage is a cross-cutting concern for a future API hardening story.

## Deferred from: S3-02 AttentionMonitor detail review (2026-08-11)

- **DEFER-013** — `AttentionMonitor`'s `postureScore` returns a constant `0.9` (no real computation). Acknowledged placeholder; real posture scoring (MediaPipe pose or shoulder keypoints) is deferred to a future story.
- **DEFER-014** — `useAttentionMonitor`'s `latestSignals` ref is read and posted every 5 s via `setInterval`, but `latestSignals.current` could theoretically be stale if the interval fires between a React render writing new ref values. Benign in practice (refs update synchronously with renders), but a shared ring-buffer or `useReducer` would be cleaner in a future refactor.
- **DEFER-015** — Whether attention monitoring should pause entirely (stop calling `detectForVideo`) when the browser tab is backgrounded (`document.hidden`), beyond the wall-clock correction applied to the blink-rate calculation for timer-throttling. A broader UX/architecture question (does a backgrounded tab's `<video>` element even keep decoding real frames across browsers) requiring product input, not a mechanical fix.

## Deferred from: code review of 2-45-signed-url-refresh-and-defer-012 (2026-08-11)

- **DEFER-016 / D67** — `GET /api/media/signed-url` (`apps/api/app/modules/media/router.py`) has no rate limiting, and Story 2-45 gives it its first real, automatic, unattended caller. Requires an `apps/api` change (a Dev 1 module) — out of scope for this frontend-only story. See `docs/DEFECT-REGISTER.md` **D67** for owner, severity, and trigger.

## Deferred from: code review of 4-1-razorpay-payment-backend (2026-08-26)

- **DEFER-017** — `supabase.table("lesson_access").insert(row).execute()` is a synchronous call inside `async def handle_payment_captured()` in `apps/api/app/modules/payments/service.py`, blocking the event loop during a live Supabase HTTP request. Pre-existing pattern shared by all service modules (`assessment/service.py`, `analytics/service.py`, etc.); fixing only the payments module in isolation would be inconsistent. Addressable in a dedicated async-supabase refactor story that wraps all sync `.execute()` calls with `asyncio.to_thread`.
