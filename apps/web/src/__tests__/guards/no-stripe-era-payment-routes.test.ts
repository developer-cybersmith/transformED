import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

/**
 * Story 2-53 (S4-02) AC-5. The tracker's original S4-02 write-up described a
 * Stripe-shaped flow (create-checkout-session, /payment/success?session_id=,
 * /payment/cancel) that has no counterpart on the real (Razorpay) backend
 * branch (origin/razorpay-backend-endpoints-dev3) -- reintroducing any of
 * these would build UI against endpoints/routes that don't exist. Also
 * guards AC-1: the client must never send `amount_paise` to create-order,
 * since the server ignores it and sending it implies a price control the
 * frontend doesn't have (S4-1 patch 1, price-bypass fix).
 */

const SRC_DIR = join(__dirname, '..', '..');
// Review finding (Acceptance Auditor, Test Coverage): a colon-only match
// missed `amount_paise=`, bracket/dot access, and shorthand property usage
// -- widened to a word-boundary match so any reference is caught regardless
// of syntax shape.
const DEAD_ROUTES = /create-checkout-session|['"]\/payment\/success|['"]\/payment\/cancel/;
const AMOUNT_PAISE = /amount_paise\b/;
const SKIP_DIRS = new Set(['node_modules', '.next']);
const SELF = relative(SRC_DIR, __filename).split('\\').join('/');
// Test names/comments legitimately describe the forbidden term in prose
// (e.g. "never amount_paise" in a test title) -- that's the guard's own
// subject matter, not a live reference. Scoped to `__tests__/` broadly
// rather than one named file, since any test file's description could
// mention either forbidden pattern going forward, not just this one.
const IS_TEST_DIR = /(^|\/)__tests__\//;
// The service's own doc comment additionally mentions amount_paise by name
// to explain why it's never sent -- also prose, not a live reference.
const AMOUNT_PAISE_EXEMPT_FILE = 'services/payment.service.ts';

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

describe('guard — no Stripe-era payment routes, no client-side amount_paise (Story 2-53 AC-1/AC-5)', () => {
    it('finds zero non-test source files matching create-checkout-session|/payment/success|/payment/cancel', () => {
        const hits: string[] = [];
        for (const file of walk(SRC_DIR)) {
            const relPath = relative(SRC_DIR, file).split('\\').join('/');
            if (relPath === SELF || IS_TEST_DIR.test(relPath)) continue;
            const content = readFileSync(file, 'utf-8');
            if (DEAD_ROUTES.test(content)) {
                hits.push(relPath);
            }
        }
        expect(hits).toEqual([]);
    });

    it('finds zero non-test source files referencing amount_paise (outside payment.service.ts\'s own doc comment)', () => {
        const hits: string[] = [];
        for (const file of walk(SRC_DIR)) {
            const relPath = relative(SRC_DIR, file).split('\\').join('/');
            if (relPath === SELF || IS_TEST_DIR.test(relPath) || relPath.endsWith(AMOUNT_PAISE_EXEMPT_FILE)) {
                continue;
            }
            const content = readFileSync(file, 'utf-8');
            if (AMOUNT_PAISE.test(content)) {
                hits.push(relPath);
            }
        }
        expect(hits).toEqual([]);
    });
});
