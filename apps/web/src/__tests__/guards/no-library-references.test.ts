import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

/**
 * Story 2-47 (S4-06) review fix: AC-9's "zero dead references" check was
 * previously verified only by a one-time manual grep during implementation
 * (FIXED-UNGUARDED per this repo's Defect Register binding rule 7) -- a
 * future PR could silently reintroduce a dead `/library` reference (a bad
 * merge, a copy-pasted comment) and nothing would fail. This test re-runs
 * that check on every CI run instead.
 *
 * Matches the AC-9 grep pattern exactly: `useLibrary`, `libraryService`,
 * `LibraryView`, or a literal quoted `/library` path. Historical prose
 * mentions of "the Library route"/"My Library" (no quotes, no live
 * import/path) are allowed -- they document the removal, they don't
 * reference anything live. See the (now reworded) comments in
 * RecentLessons.tsx, ContinueLearningCard.tsx, QuickActions.tsx,
 * TopUtilityBar.tsx, and books/page.tsx for the exact wording this test
 * would have caught a regression of.
 */

const SRC_DIR = join(__dirname, '..', '..');
const FORBIDDEN = /useLibrary|libraryService|LibraryView|['"]\/library['"]/;
const SKIP_DIRS = new Set(['node_modules', '.next']);
// This guard file itself documents the forbidden patterns in prose above.
const SELF = relative(SRC_DIR, __filename).split('\\').join('/');

function walk(dir: string, files: string[] = []): string[] {
    for (const entry of readdirSync(dir)) {
        if (SKIP_DIRS.has(entry)) continue;
        const full = join(dir, entry);
        const stat = statSync(full);
        if (stat.isDirectory()) {
            walk(full, files);
        } else if (/\.(ts|tsx)$/.test(entry)) {
            files.push(full);
        }
    }
    return files;
}

describe('guard — no dead /library references (Story 2-47 AC-9)', () => {
    it('finds zero source files matching useLibrary|libraryService|LibraryView|\'/library\'|"/library"', () => {
        const hits: string[] = [];
        for (const file of walk(SRC_DIR)) {
            const relPath = relative(SRC_DIR, file).split('\\').join('/');
            if (relPath === SELF) continue;
            const content = readFileSync(file, 'utf-8');
            if (FORBIDDEN.test(content)) {
                hits.push(relPath);
            }
        }
        expect(hits).toEqual([]);
    });
});
