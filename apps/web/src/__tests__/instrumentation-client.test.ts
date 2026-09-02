import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Story 2-54 (S4-03). Review finding (Blind Hunter, AC Completeness, Test
// Coverage -- corroborated by 3 layers): this file previously had zero test
// coverage despite AC-1's "skip if unset, no crash" clause. `vi.resetModules`
// + `vi.stubEnv` + a fresh dynamic import is the established pattern in this
// repo for a module that reads `process.env` at import time (see
// __tests__/lib/api.test.ts's identical D31 guard).

const { initMock } = vi.hoisted(() => ({ initMock: vi.fn() }));

vi.mock('posthog-js', () => ({
    default: { init: initMock },
}));

beforeEach(() => {
    vi.resetModules();
    initMock.mockReset();
});

afterEach(() => {
    vi.unstubAllEnvs();
});

describe('instrumentation-client', () => {
    it('skips posthog.init entirely when NEXT_PUBLIC_POSTHOG_KEY is unset -- no crash, no call', async () => {
        vi.stubEnv('NEXT_PUBLIC_POSTHOG_KEY', '');
        vi.stubEnv('NEXT_PUBLIC_POSTHOG_HOST', '');

        await expect(import('@/instrumentation-client')).resolves.toBeDefined();
        expect(initMock).not.toHaveBeenCalled();
    });

    it('calls posthog.init with the real key/host and explicit autocapture/pageview opt-outs when the key is set', async () => {
        vi.stubEnv('NEXT_PUBLIC_POSTHOG_KEY', 'phc_test_key');
        vi.stubEnv('NEXT_PUBLIC_POSTHOG_HOST', 'https://eu.i.posthog.com');

        await import('@/instrumentation-client');

        expect(initMock).toHaveBeenCalledWith('phc_test_key', {
            api_host: 'https://eu.i.posthog.com',
            defaults: '2026-05-30',
            autocapture: false,
            capture_pageview: false,
            capture_pageleave: false,
        });
    });
});
