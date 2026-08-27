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
const FORBIDDEN = /create-checkout-session|['"]\/payment\/success|['"]\/payment\/cancel|amount_paise:/;
const SKIP_DIRS = new Set(['node_modules', '.next']);
const SELF = relative(SRC_DIR, __filename).split('\\').join('/');
// The service's own doc comment mentions amount_paise by name to explain
// why it's never sent — that mention is prose, not a live reference.
const ALLOWED_COMMENT_FILE = 'services/payment.service.ts';

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
    it('finds zero source files matching create-checkout-session|/payment/success|/payment/cancel|amount_paise:', () => {
        const hits: string[] = [];
        for (const file of walk(SRC_DIR)) {
            const relPath = relative(SRC_DIR, file).split('\\').join('/');
            if (relPath === SELF || relPath.endsWith(ALLOWED_COMMENT_FILE)) continue;
            const content = readFileSync(file, 'utf-8');
            if (FORBIDDEN.test(content)) {
                hits.push(relPath);
            }
        }
        expect(hits).toEqual([]);
    });
});
