import posthog from 'posthog-js';

// Story 2-54 (S4-03). Next.js's officially-recommended App Router
// integration point for client-side instrumentation (stable since 15.3) --
// runs once in the browser before hydration, no PostHogProvider component
// or layout.tsx change needed.
//
// Skipped entirely if the key is unset (local dev/CI without a configured
// project) -- never silently sends events to a misconfigured/absent
// project, and never crashes a build that hasn't set this up yet.
const POSTHOG_KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY;
const POSTHOG_HOST = process.env.NEXT_PUBLIC_POSTHOG_HOST;

if (POSTHOG_KEY) {
    posthog.init(POSTHOG_KEY, {
        api_host: POSTHOG_HOST,
        defaults: '2026-05-30',
    });
}
