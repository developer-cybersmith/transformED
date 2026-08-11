# Deferred Work

## Deferred from: code review of 3-22-posthog-assessment-events (2026-07-03)

- **DEFER-001** — UUID `distinct_id` sent to PostHog with no erasure pathway for DPDP right-to-erasure. PostHog builds a persistent person profile keyed on the user's internal UUID; no code path calls PostHog's person-delete API when an account is deleted. Addressable in a dedicated DPDP compliance story before real-student launch.
- **DEFER-002** — Synchronous `posthog.capture()` called from async route handlers and service functions (no `asyncio.to_thread` guard). Current PostHog Python SDK v3 queues internally and returns in microseconds — no measurable event-loop impact today. Add `asyncio.to_thread` wrapper if SDK v4 changes flush semantics.

## Deferred from: code review of 3-34-canonical-ces-formula (2026-08-10)

- **DEFER-003** — Dead-code paths for behavioral/hp/blink=None redistribution in canonical ces.py are unreachable through the production `NormalizedSignal` wrapper (behavioral_score, head_pose_score, blink_rate typed as plain `float`, not `Optional[float]`). These paths are intentional forward-compatibility for S3-40 (MediaPipe Failure Protocol), already noted in Story 3-34 Dev Notes. Trigger: S3-40 implementation, which will update `NormalizedSignal` to allow None for these fields.
- **DEFER-004** — No codebase-wide AST scan enforcing AC1 (CES computation occurs only in `assessment/ces.py`). D62 documents the defect class; a CI guard (similar to `test_node_return_shape.py`'s source-scan pattern) would be a separate story. Trigger: before Sprint 4 hardening, or if a second CES implementation is detected in review.
- **DEFER-005** — Degenerate weight config (Scale Q5): if `ces_weight_behavioral`, `ces_weight_head_pose`, and `ces_weight_blink` are all 0.0 in settings while `quiz_accuracy=None` and `teachback_score=None` (start of lesson before any quiz), `weight_sum=0.0` → CES=0.0 silently with no log or flag. The weight validator only checks that all 5 weights sum to 1.0, not that any behavioral-signal subset is non-zero. Pre-existing behavior. Registered as D63. Trigger: the first deploy where behavioral signal weights are intentionally zeroed (unlikely but representable in config).
