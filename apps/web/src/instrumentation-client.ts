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
        // Review fix (Scale & Load Hunter): the `defaults` dating mechanism
        // does NOT turn these off -- autocapture and pageview/pageleave
        // tracking all remain at their true default of `true` regardless of
        // which dated preset is chosen. Left on, every click (quiz options,
        // Submit/Next, upload dropzone, dashboard nav) and every route
        // change would fire additional $autocapture/$pageview/$pageleave
        // events on top of this story's 8 named ones -- ~3-4x the volume
        // Scale & Load Q1 modeled, reaching the free-tier 1M-events/month
        // quota materially sooner with zero in-app signal when it's hit
        // (Q2/Q3). This story's stated scope is 8 specific, named events,
        // not general autocapture -- turned off explicitly rather than
        // inherited as an unreviewed default. Also closes a related privacy
        // gap (Blind Hunter): DOM autocapture could otherwise grab raw text
        // from TeachBackModal's free-text answer field.
        autocapture: false,
        capture_pageview: false,
        capture_pageleave: false,
    });
}
