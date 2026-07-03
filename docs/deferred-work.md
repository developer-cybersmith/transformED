# Deferred Work

## Deferred from: code review of 3-22-posthog-assessment-events (2026-07-03)

- **DEFER-001** — UUID `distinct_id` sent to PostHog with no erasure pathway for DPDP right-to-erasure. PostHog builds a persistent person profile keyed on the user's internal UUID; no code path calls PostHog's person-delete API when an account is deleted. Addressable in a dedicated DPDP compliance story before real-student launch.
- **DEFER-002** — Synchronous `posthog.capture()` called from async route handlers and service functions (no `asyncio.to_thread` guard). Current PostHog Python SDK v3 queues internally and returns in microseconds — no measurable event-loop impact today. Add `asyncio.to_thread` wrapper if SDK v4 changes flush semantics.
