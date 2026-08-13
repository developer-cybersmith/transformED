import { describe, it, expect } from 'vitest';
import type { LocalControlOut } from '@/lib/ws/wireTypes';

// Review finding (2026-08-11, PR #129 six-layer review — Acceptance Auditor, Test Coverage,
// AC Completeness layers all independently flagged this): wireTypes.ts's `FlowEvent` union
// addition of 'intervention_complete' had ZERO test coverage. The Python-side allow-lists
// (_CLIENT_DRIVABLE_EVENTS, _TUTOR_CLIENT_EVENTS) are cross-checked against each other by
// test_e4_client_event_allowlists_match, but nothing checked wireTypes.ts stayed in sync with
// either — FIXED-UNGUARDED per CLAUDE.md binding rule 7.
//
// `FlowEvent` itself is module-private; `LocalControlOut` (which wraps it as `{ type: FlowEvent }`
// among other variants) is exported and is what a real client constructs. The assertion below is
// deliberately BOTH a compile-time check (the type annotation fails `tsc --noEmit` — the web CI
// job's existing gate, D25 — if 'intervention_complete' is ever removed from FlowEvent) and a
// trivial runtime one, without requiring wireTypes.ts to be restructured into a runtime-derived
// union just to be testable.
describe('wireTypes — FlowEvent includes intervention_complete (D63)', () => {
  it('accepts an intervention_complete control frame at the type level', () => {
    const frame: LocalControlOut = { type: 'intervention_complete' };
    expect(frame.type).toBe('intervention_complete');
  });

  it('still accepts the other 8 pre-existing flow events (no regression to the union)', () => {
    const events: LocalControlOut[] = [
      { type: 'segment_complete' },
      { type: 'checkin_complete' },
      { type: 'low_checkin_score' },
      { type: 'quiz_trigger' },
      { type: 'quiz_complete' },
      { type: 'quiz_failed' },
      { type: 'teachback_complete' },
      { type: 'teachback_failed' },
      { type: 'lesson_complete' },
    ];
    expect(events).toHaveLength(9);
  });
});
