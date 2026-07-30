import { api } from './api';
import { usePlayerStore } from '@/stores/player.machine';

// Matches apps/api/app/modules/analytics/service.py::KNOWN_EVENT_TYPES exactly --
// verify against the real Python before adding a new type (unknown types are
// accepted but logged at WARNING server-side, not rejected).
export type AnalyticsEventType =
  | 'tab_switch'
  | 'retry_after_fail'
  | 'jargon_hover'
  | 'quiz_skip'
  | 'teachback_skip'
  | 'intervention_acknowledged'
  | 'segment_complete'
  | 'session_start'
  | 'session_end';

// Fire-and-forget behavioral event ingestion (POST /api/analytics/events).
// Never awaited by callers, never throws -- a dropped analytics event must
// never affect the lesson experience. Reads sessionId fresh from the player
// store so callers don't need to thread it through as a prop. No-ops before
// a session exists (nothing to attribute the event to yet).
export function trackEvent(
  eventType: AnalyticsEventType,
  payload: Record<string, unknown> = {}
): void {
  const sessionId = usePlayerStore.getState().sessionId;
  if (!sessionId) return;

  api
    .post('/analytics/events', {
      events: [
        {
          session_id: sessionId,
          event_type: eventType,
          payload,
          client_timestamp_ms: Date.now(),
        },
      ],
    })
    .catch(() => {
      // Fire-and-forget -- analytics failures must never surface to the student.
    });
}
