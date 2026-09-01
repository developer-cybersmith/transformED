import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Story 2-54 (S4-03) AC-4. `apps/web/src/lib/analytics.ts`'s `trackEvent()`
 * and its `AnalyticsEventType` union are Dev 3's backend-owned CES/
 * behavioral-scoring contract -- it must match
 * `apps/api/app/modules/analytics/service.py::KNOWN_EVENT_TYPES` exactly.
 * This story's 8 PostHog events are a separate, additive system (direct
 * `posthog.capture(...)` calls) and must never be added to that union or
 * sent via `trackEvent()` -- doing so would silently widen a contract Dev 3
 * owns. This guard fails if any of the 8 event name strings ever appears in
 * analytics.ts.
 */

const ANALYTICS_TS = join(__dirname, '..', '..', 'lib', 'analytics.ts');

const POSTHOG_EVENT_NAMES = [
    'onboarding_completed',
    'upload_started',
    'upload_completed',
    'lesson_started',
    'lesson_completed',
    'quiz_answered',
    'teachback_submitted',
    'intervention_received',
];

describe('guard — no Story 2-54 PostHog event name appears in Dev 3\'s analytics.ts contract', () => {
    it.each(POSTHOG_EVENT_NAMES)('%s is not referenced in lib/analytics.ts', (eventName) => {
        const content = readFileSync(ANALYTICS_TS, 'utf-8');
        expect(content).not.toContain(eventName);
    });
});
