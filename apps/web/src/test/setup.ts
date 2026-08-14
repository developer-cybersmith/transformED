/**
 * Global Vitest setup (Story W0 AC1).
 *
 * `vitest.config.ts` had `setupFiles: []` before this file existed, which is why
 * `@testing-library/jest-dom` — a devDependency since Sprint 1 — has never once
 * been imported and every assertion in the suite reads `expect(x).not.toBeNull()`.
 * That idiom is deliberately LEFT ALONE: importing jest-dom here would silently
 * change the matcher vocabulary for all 58 test files at once, which is a
 * repo-wide change that belongs in its own commit, not smuggled in under a
 * contract-harness story.
 */
import { afterAll, afterEach, beforeAll } from 'vitest';
import { server } from './server';
import { resetLessonStore } from './handlers';

// ── jsdom Blob gap ──────────────────────────────────────────────────────────
// jsdom's Blob/File implement neither `arrayBuffer()` nor `stream()` (verified
// in this environment: both are `undefined`). Undici — which backs MSW's request
// object — reads a multipart body by calling one of them, so a `FormData` body
// carrying a jsdom `File` never resolves and the test dies on a bare "timed out
// in 5000ms" with no mention of a Blob anywhere. That is a full 5s of silence
// for a one-line gap, so it is polyfilled here rather than rediscovered.
// Feature-detected: when jsdom ships them, these no-op.
const BlobProto = globalThis.Blob?.prototype as (Blob & Record<string, unknown>) | undefined;
if (BlobProto && typeof BlobProto.arrayBuffer !== 'function') {
    BlobProto.arrayBuffer = function arrayBuffer(this: Blob): Promise<ArrayBuffer> {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result as ArrayBuffer);
            reader.onerror = () => reject(reader.error);
            reader.readAsArrayBuffer(this);
        });
    };
}
if (BlobProto && typeof BlobProto.text !== 'function') {
    BlobProto.text = async function text(this: Blob): Promise<string> {
        return new TextDecoder().decode(await this.arrayBuffer());
    };
}
if (BlobProto && typeof BlobProto.stream !== 'function' && typeof ReadableStream === 'function') {
    BlobProto.stream = function stream(this: Blob) {
        // Read eagerly rather than aliasing `this` into the start() closure
        // (@typescript-eslint/no-this-alias). Fine for a test-only polyfill:
        // fixture blobs are bytes already in memory.
        const bytes = this.arrayBuffer();
        return new ReadableStream({
            async start(controller) {
                controller.enqueue(new Uint8Array(await bytes));
                controller.close();
            },
        });
    };
}

// ── ResizeObserver polyfill (jsdom gap) ──────────────────────────────────────
// jsdom has no ResizeObserver; recharts' <ResponsiveContainer> (used by
// AttentionChart, Story 2-46/S3-05) depends on one to measure its container and
// render at a real size. Without this, every chart measures 0x0 and silently
// renders nothing, so a test asserting on chart content would fail for a reason
// entirely unrelated to the component under test. Reports a fixed, realistic
// size synchronously so charts render immediately in tests. Feature-detected,
// same pattern as the Blob polyfill below.
if (typeof globalThis.ResizeObserver === 'undefined') {
    class MockResizeObserver {
        private readonly callback: ResizeObserverCallback;
        constructor(callback: ResizeObserverCallback) {
            this.callback = callback;
        }
        observe(target: Element) {
            const rect = { width: 800, height: 400 } as DOMRectReadOnly;
            this.callback(
                [{ target, contentRect: rect } as ResizeObserverEntry],
                this as unknown as ResizeObserver,
            );
        }
        unobserve() {}
        disconnect() {}
    }
    globalThis.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver;
}

// recharts' <ResponsiveContainer> also reads its own wrapper <div>'s
// getBoundingClientRect() directly (not only via the observer entry) --
// jsdom's default all-zero rect produces the same silent-empty-chart problem
// the polyfill above exists to prevent. Scoped to DIV specifically: recharts
// ALSO creates temporary, invisible <span> elements to measure tick-label
// text width for its overlap-avoidance algorithm -- faking those to a large
// size makes every label look like it overlaps, which silently drops nearly
// all axis ticks with no error of any kind (found building AttentionChart,
// Story 2-46/S3-05 -- Y-axis ticks rendered zero, X-axis rendered only one).
// SVG elements (<text>, <g>, ...) are untouched too, purely because they are
// never DIVs -- no separate check needed.
{
    const original = Element.prototype.getBoundingClientRect;
    Element.prototype.getBoundingClientRect = function (this: Element) {
        const rect = original.call(this);
        if (rect.width === 0 && rect.height === 0 && this.tagName === 'DIV') {
            return { ...rect, width: 800, height: 400, right: 800, bottom: 400 } as DOMRect;
        }
        return rect;
    };
}

// `@/lib/api`'s request interceptor constructs a Supabase browser client on
// every call; `createBrowserClient` throws on an undefined url. These are the
// same placeholder values `ci.yml` uses for the web build. Set before any test
// module is imported so the lazy call inside the interceptor always finds them.
process.env.NEXT_PUBLIC_SUPABASE_URL ||= 'http://localhost:54321';
process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||= 'test-anon-key';

beforeAll(() => {
    // `onUnhandledRequest: 'error'` is the whole point. A request the harness
    // does not recognise is a request the contract does not describe — it must
    // fail the test, not slip through as an unresolved promise that a `waitFor`
    // later reports as a timeout with no explanation.
    server.listen({ onUnhandledRequest: 'error' });

    // ── MSW's WebSocket interceptor, undone ─────────────────────────────────
    // `server.listen()` also installs MSW 2.x's WebSocket interceptor, which
    // REDEFINES `globalThis.WebSocket` as a non-writable property. Two test
    // files that predate this harness swap in a fake socket with a plain
    // assignment (`global.WebSocket = FakeWebSocket`) and started throwing
    // "Cannot assign to read only property 'WebSocket'" — 27 tests, none of them
    // ours, red for a reason with no visible connection to WebSockets at all.
    //
    // Restoring writability (rather than patching those two files, or dropping
    // `onUnhandledRequest: 'error'`) is the narrowest fix: this harness exists to
    // pin HTTP contracts and intercepts no WebSocket traffic, so nothing here
    // wants that interceptor's property descriptor. `configurable: true` is kept
    // so a test can still `defineProperty` over it.
    //
    // Delete this only together with the WS interception it compensates for.
    if (typeof globalThis.WebSocket !== 'undefined') {
        Object.defineProperty(globalThis, 'WebSocket', {
            value: globalThis.WebSocket,
            writable: true,
            configurable: true,
        });
    }
});

afterEach(() => {
    server.resetHandlers();
    resetLessonStore();
});

afterAll(() => {
    server.close();
});
