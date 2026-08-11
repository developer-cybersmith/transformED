import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import path from 'path';

// D31 regression guard: `NEXT_PUBLIC_API_URL`'s documented value must resolve every
// API call to the real `/api`-mounted route, never to the bare, unprefixed path.
// `main.py` mounts every FastAPI router under `/api` with no unprefixed alias, so a
// documented value missing that segment 404s every single call for anyone who
// actually follows the setup docs -- src/lib/api.ts's own hardcoded fallback
// (`http://localhost:8000/api`) already has this right, which is exactly why a dev
// who configures nothing works and a dev who reads `.env.example` does not.

function readDocumentedApiUrl(): string {
    const envExamplePath = path.resolve(__dirname, '../../../../../.env.example');
    const content = readFileSync(envExamplePath, 'utf-8');
    const line = content
        .split('\n')
        .find((l) => l.trim().startsWith('NEXT_PUBLIC_API_URL='));
    if (!line) {
        throw new Error('NEXT_PUBLIC_API_URL not found in .env.example');
    }
    return line.split('=')[1].trim();
}

// Mirrors how axios joins `baseURL` with a relative request path: strip any
// trailing slash from the base, strip any leading slash from the path, join with
// exactly one slash. This is the same join `apps/web/src/lib/api.ts`'s axios
// instance performs for every call the app makes (e.g. `api.get('content/lessons')`).
function resolveApiPath(baseURL: string, relativePath: string): string {
    return `${baseURL.replace(/\/+$/, '')}/${relativePath.replace(/^\/+/, '')}`;
}

describe('.env.example NEXT_PUBLIC_API_URL (D31 regression guard)', () => {
    it('resolves a known route to the real /api-mounted path, not a bare path', () => {
        const documented = readDocumentedApiUrl();
        const resolved = resolveApiPath(documented, 'content/lessons');
        expect(resolved).toBe('http://localhost:8000/api/content/lessons');
    });
});
