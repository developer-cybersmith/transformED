/**
 * W4 AC1 — nothing reachable from the book-scale screens may import a mock.
 *
 * The phase was written as "MSW off", on the assumption that MSW intercepts in
 * the running app. It never did: `msw` is a devDependency wired only into
 * `vitest.config.ts`'s `setupFiles`, so every one of its importers lives under
 * `src/test/` or `src/__tests__/`. There was nothing to switch off.
 *
 * What actually stands between this UI and a real backend is the older
 * hand-rolled `src/mocks/` layer — plain async functions imported directly by
 * services. `reports.service.ts` and `settings.service.ts` still use it and are
 * outside book-scale; `dashboard.service.ts` uses it for `learningPulse` only,
 * scoped and wrapped. The book-scale path itself is already clean.
 *
 * "Already clean" is a fact about today, not a property. This guard is what makes
 * it a property. Without it, one `import { lessonApi } from '@/mocks/api'` in
 * `books.service.ts` turns Phase 7's browser run into a demonstration that the
 * fixtures work — green screens, real-looking data, and nothing proved. That is
 * the failure this whole effort keeps finding.
 *
 * TYPE-ONLY imports are deliberately allowed. `import type { LearningPulse }
 * from "@/mocks/data/reports"` is compile-time coupling, not mock data in the
 * render path; it disappears at build time. Do not "fix" those under this
 * story's banner — moving those types is a different change with a different
 * owner.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');

/** Entry points a student actually renders on the book-scale path. */
const ENTRY_POINTS = [
    'services/books.service.ts',
    'services/upload.service.ts',
    'hooks/useBooks.ts',
    'hooks/useChapters.ts',
    'app/(dashboard)/books/page.tsx',
    'app/(dashboard)/books/[id]/page.tsx',
    'components/dashboard/books/BookDetail.tsx',
    'components/dashboard/books/ChapterRow.tsx',
    'components/dashboard/books/ChapterGenerateControl.tsx',
    'components/dashboard/upload/UploadFlow.tsx',
];

const FORBIDDEN = [/(^|['"])msw(\/|['"])/, /@\/mocks/, /\.\.?\/mocks\//];

/** `import type { … } from 'x'` / `export type { … } from 'x'` — erased at build. */
const TYPE_ONLY = /^\s*(?:import|export)\s+type\s/;

const IMPORT_RE = /^\s*(?:import|export)\b[^;]*?from\s+['"]([^'"]+)['"]/gm;

function resolveImport(spec: string, fromFile: string): string | null {
    let base: string;
    if (spec.startsWith('@/')) base = resolve(SRC, spec.slice(2));
    else if (spec.startsWith('.')) base = resolve(dirname(fromFile), spec);
    else return null; // node_modules — not ours to walk
    for (const ext of ['.ts', '.tsx', '/index.ts', '/index.tsx']) {
        if (existsSync(base + ext)) return base + ext;
    }
    return existsSync(base) ? base : null;
}

/** Walk the import graph from `entry`, returning every offending edge. */
function mockImportsReachableFrom(entry: string): string[] {
    const seen = new Set<string>();
    const offences: string[] = [];
    const stack = [resolve(SRC, entry)];

    while (stack.length) {
        const file = stack.pop() as string;
        if (seen.has(file) || !existsSync(file)) continue;
        seen.add(file);

        const source = readFileSync(file, 'utf8');
        for (const line of source.split('\n')) {
            const m = /(?:import|export)\b[^;]*?from\s+['"]([^'"]+)['"]/.exec(line);
            if (!m) continue;
            const spec = m[1];
            if (FORBIDDEN.some((re) => re.test(spec))) {
                // A type-only import is erased at build time — no mock data ships.
                if (TYPE_ONLY.test(line)) continue;
                offences.push(`${file.replace(SRC, 'src')} imports ${spec}`);
            }
            const next = resolveImport(spec, file);
            if (next) stack.push(next);
        }
    }
    return offences;
}

describe('W4 AC1 — the book-scale path imports no mocks', () => {
    it.each(ENTRY_POINTS)('%s reaches no mock module', (entry) => {
        expect(existsSync(resolve(SRC, entry)), `${entry} not found — is this list stale?`).toBe(
            true,
        );
        expect(mockImportsReachableFrom(entry)).toEqual([]);
    });

    it('the walker actually walks — a known mock importer IS flagged', () => {
        // Premise (binding rule 3). Without this, a walker that resolved nothing
        // would report every entry point clean and the guard would pass forever.
        // `reports.service.ts` imports `../mocks/api` at runtime and is
        // legitimately outside book-scale — it is the perfect positive control.
        expect(mockImportsReachableFrom('services/reports.service.ts').length).toBeGreaterThan(0);
    });

    it('a type-only mock import is NOT flagged', () => {
        // `LearningPulse.tsx` does `import type { … } from "@/mocks/data/reports"`.
        // Erased at build time, so no mock data reaches the render path.
        expect(mockImportsReachableFrom('components/dashboard/sections/LearningPulse.tsx')).toEqual(
            [],
        );
    });

    it('msw is a devDependency only — it was never in the app path', () => {
        const pkg = JSON.parse(
            readFileSync(resolve(SRC, '..', 'package.json'), 'utf8'),
        ) as Record<string, Record<string, string>>;
        expect(pkg.dependencies?.msw).toBeUndefined();
        expect(pkg.devDependencies?.msw).toBeDefined();
    });
});
