import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'fs';
import path from 'path';

// D31 regression guard: `NEXT_PUBLIC_API_URL`'s documented value must resolve every
// API call to the real `/api`-mounted route, never to the bare, unprefixed path.
// `main.py` mounts every FastAPI router under `/api` with no unprefixed alias, so a
// documented value missing that segment 404s every single call for anyone who
// actually follows the setup docs -- src/lib/api.ts's own hardcoded fallback
// (`http://localhost:8000/api`) already has this right, which is exactly why a dev
// who configures nothing works and a dev who reads `.env.example` does not.
//
// This exercises the REAL `apps/web/src/lib/api.ts` axios instance via `getUri()`,
// not a hand-rolled reimplementation of axios's baseURL-join logic -- a prior version
// of this test rebuilt that join itself, which proved the test author's model of
// axios was self-consistent, not that the real module resolves correctly. If `api.ts`
// ever changes how it builds its baseURL, this test now catches that; the old one
// could not have.

function readDocumentedApiUrl(): string {
    const envExamplePath = path.resolve(__dirname, '../../../../../.env.example');
    const content = readFileSync(envExamplePath, 'utf-8');
    const line = content
        .split('\n')
        .find((l) => l.trim().startsWith('NEXT_PUBLIC_API_URL='));
    if (!line) {
        throw new Error('NEXT_PUBLIC_API_URL not found in .env.example');
    }
    // Split on the FIRST '=' only -- a value containing '=' (e.g. a query string)
    // must not be truncated by a naive `split('=')[1]`.
    const eqIndex = line.indexOf('=');
    const rawValue = line.slice(eqIndex + 1);
    // Strip a trailing inline comment, consistent with the backend parser
    // (apps/api/tests/test_env_example_consistency.py) that guards this same file.
    return rawValue.replace(/\s+#.*$/, '').trim();
}

describe('.env.example NEXT_PUBLIC_API_URL (D31 regression guard)', () => {
    beforeEach(() => {
        vi.resetModules();
    });

    afterEach(() => {
        vi.unstubAllEnvs();
    });

    it('resolves a known route through the real axios instance to the /api-mounted path', async () => {
        const documented = readDocumentedApiUrl();
        vi.stubEnv('NEXT_PUBLIC_API_URL', documented);

        // Fresh import so `api.ts`'s module-level `API_URL` picks up the stubbed env
        // (it's computed once, at import time, from `process.env`).
        const { api } = await import('@/lib/api');

        // `getUri()` is axios's own URL-resolution utility -- it merges instance
        // config (baseURL) with a request config (url) using the exact logic a real
        // `api.get('content/lessons')` call would use, without making a network call
        // or running the auth interceptor.
        const resolved = api.getUri({ url: 'content/lessons' });

        expect(resolved).toBe('http://localhost:8000/api/content/lessons');
    });

    it('would fail this test if the documented value regressed to the bare host (proves the guard is live)', async () => {
        vi.stubEnv('NEXT_PUBLIC_API_URL', 'http://localhost:8000');
        const { api } = await import('@/lib/api');
        const resolved = api.getUri({ url: 'content/lessons' });
        expect(resolved).toBe('http://localhost:8000/content/lessons');
        expect(resolved.endsWith('/api/content/lessons')).toBe(false);
    });
});
