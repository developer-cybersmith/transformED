/**
 * MSW request handlers for every book-scale endpoint and every documented
 * failure (Story W0 AC3).
 *
 * These intercept real HTTP at the network layer, so a test that exercises
 * `uploadService`/`booksService` goes through axios, the `@/lib/api` instance,
 * its interceptors and the real URL resolution. A module mock cannot disconfirm
 * any of that — see DEFECT-REGISTER binding rule 2.
 *
 * URL matching: `@/lib/api` is axios with
 * `baseURL = NEXT_PUBLIC_API_URL || "http://localhost:8000/api"` and services
 * pass RELATIVE paths with no leading slash (`'content/lessons'`). The handler
 * patterns below are the resolved ABSOLUTE urls; resolve the base the same way
 * the client does so the two can never disagree.
 */
import { http, HttpResponse } from 'msw';
import {
    ALL_CHAPTERS,
    BOOKS,
    BOOK_NOT_FOUND_DETAIL,
    BOOK_NOT_READY_DETAIL,
    CHAPTERS,
    CHAPTER_NOT_FOUND_DETAIL,
    CONCURRENCY_CAP_DETAIL,
    DEFAULT_TIER,
    PROCESSING_BOOK,
    RATE_LIMITED_CHAPTER,
    READY_BOOK,
    TIER_ON_UPLOAD_DETAIL,
    TOO_LARGE_CHAPTER,
    VALID_TIERS,
    isTooLarge,
    pageSpan,
    truncationExpected,
    type ContractChapter,
} from './fixtures';
import { MAX_PAGE_SPAN } from './contract';

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api').replace(
    /\/+$/,
    ''
);

const ALL_BOOKS = [...BOOKS, READY_BOOK].filter(
    (b, i, arr) => arr.findIndex((x) => x.book_id === b.book_id) === i
);

function findBook(bookId: string) {
    return ALL_BOOKS.find((b) => b.book_id === bookId);
}

function findChapter(chapterId: string): ContractChapter | undefined {
    return ALL_CHAPTERS.find((c) => c.chapter_id === chapterId);
}

/**
 * Best-effort idempotency store, mirroring the backend's own best-effort
 * pre-check (contract note: TOCTOU-racy, DEFECT-REGISTER D45). Keyed by
 * (chapter, tier) because the SAME chapter at a DIFFERENT tier is deliberately
 * a new lesson.
 */
const lessonStore = new Map<string, { lesson_id: string; status: string }>();

export function resetLessonStore(): void {
    lessonStore.clear();
}

/** Exposed so a test can assert what the harness actually created. */
export function lessonStoreSize(): number {
    return lessonStore.size;
}

export const handlers = [
    // ── POST /content/lessons — book ingestion (NOT lesson creation) ─────────
    http.post(`${API_BASE}/content/lessons`, async ({ request }) => {
        const form = await request.formData();

        // The whole reason this story exists. `tier` on upload is a 422 —
        // unconditionally, before any file handling.
        if (form.has('tier')) {
            return HttpResponse.json({ detail: TIER_ON_UPLOAD_DETAIL }, { status: 422 });
        }

        // Deliberately NOT `instanceof File`: MSW parses the multipart body with
        // undici, so the entry is undici's File, not jsdom's global one, and the
        // instanceof check silently fails for every real upload. "Present and not
        // a plain string field" is the property that actually matters.
        const file = form.get('file');
        if (file === null || typeof file === 'string') {
            return HttpResponse.json(
                { detail: [{ loc: ['body', 'file'], msg: 'field required', type: 'missing' }] },
                { status: 422 }
            );
        }

        return HttpResponse.json(
            { book_id: PROCESSING_BOOK.book_id, job_id: 'arq:book_ingest:1', status: 'queued' },
            { status: 202 }
        );
    }),

    // ── GET /content/books ───────────────────────────────────────────────────
    http.get(`${API_BASE}/content/books`, ({ request }) => {
        const url = new URL(request.url);
        const limit = Number(url.searchParams.get('limit') ?? 50);
        const offset = Number(url.searchParams.get('offset') ?? 0);
        return HttpResponse.json(BOOKS.slice(offset, offset + limit), { status: 200 });
    }),

    // ── GET /content/books/{book_id} ─────────────────────────────────────────
    http.get(`${API_BASE}/content/books/:bookId`, ({ params }) => {
        const book = findBook(params.bookId as string);
        // Byte-identical body for absent / malformed-uuid / someone else's book.
        // Never 403 — a 403 confirms the id exists.
        if (!book) return HttpResponse.json({ detail: BOOK_NOT_FOUND_DETAIL }, { status: 404 });
        return HttpResponse.json(book, { status: 200 });
    }),

    // ── GET /content/books/{book_id}/chapters ────────────────────────────────
    http.get(`${API_BASE}/content/books/:bookId/chapters`, ({ params }) => {
        const book = findBook(params.bookId as string);
        if (!book) return HttpResponse.json({ detail: BOOK_NOT_FOUND_DETAIL }, { status: 404 });
        // A book still ingesting has no chapters yet. That is the normal state,
        // not an error — chapter_count is 0, the list is empty, no 404.
        if (book.status !== 'ready') return HttpResponse.json([], { status: 200 });
        return HttpResponse.json(CHAPTERS, { status: 200 });
    }),

    // ── POST /content/books/{book_id}/chapters/{chapter_id}/lessons ──────────
    http.post(
        `${API_BASE}/content/books/:bookId/chapters/:chapterId/lessons`,
        async ({ params, request }) => {
            const bookId = params.bookId as string;
            const chapterId = params.chapterId as string;

            let body: { tier?: unknown } = {};
            try {
                body = (await request.json()) as { tier?: unknown };
            } catch {
                body = {};
            }
            const tier = body.tier === undefined ? DEFAULT_TIER : body.tier;

            // 422 — FastAPI validation, raised during request parsing, i.e.
            // BEFORE any database call. Order matters: it beats the 404s.
            if (typeof tier !== 'string' || !(VALID_TIERS as readonly string[]).includes(tier)) {
                return HttpResponse.json(
                    {
                        detail: [
                            {
                                type: 'literal_error',
                                loc: ['body', 'tier'],
                                msg: "Input should be 'T1', 'T2' or 'T3'",
                                input: tier,
                            },
                        ],
                    },
                    { status: 422 }
                );
            }

            // 429 — applied by the slowapi decorator, so it also precedes the
            // handler's own database lookups.
            if (chapterId === RATE_LIMITED_CHAPTER.chapter_id) {
                return HttpResponse.json(
                    { detail: CONCURRENCY_CAP_DETAIL },
                    { status: 429, headers: { 'Retry-After': '60' } }
                );
            }

            const book = findBook(bookId);
            if (!book) return HttpResponse.json({ detail: BOOK_NOT_FOUND_DETAIL }, { status: 404 });

            // 409 — the book exists and the caller owns it, there is simply
            // nothing to generate from yet. Retryable without user action.
            if (book.status !== 'ready') {
                return HttpResponse.json({ detail: BOOK_NOT_READY_DETAIL }, { status: 409 });
            }

            const chapter = findChapter(chapterId);
            if (!chapter) {
                return HttpResponse.json({ detail: CHAPTER_NOT_FOUND_DETAIL }, { status: 404 });
            }

            // 422 — chapter_too_large. The detail is an OBJECT, not a string.
            if (isTooLarge(chapter)) {
                return HttpResponse.json(
                    {
                        detail: {
                            code: 'chapter_too_large',
                            page_span: pageSpan(chapter),
                            max_page_span: MAX_PAGE_SPAN,
                            boundary_confidence: chapter.boundary_confidence,
                        },
                    },
                    { status: 422 }
                );
            }

            const key = `${chapterId}:${tier}`;
            const existing = lessonStore.get(key);
            if (existing) {
                // 200 idempotent hit. SAME lesson_id, nothing enqueued, and
                // job_id is ALWAYS null on this path.
                return HttpResponse.json(
                    {
                        lesson_id: existing.lesson_id,
                        chapter_id: chapterId,
                        tier,
                        status: existing.status,
                        job_id: null,
                        truncation_expected: truncationExpected(chapter),
                    },
                    { status: 200 }
                );
            }

            const lessonId = crypto.randomUUID();
            lessonStore.set(key, { lesson_id: lessonId, status: 'generating' });
            return HttpResponse.json(
                {
                    lesson_id: lessonId,
                    chapter_id: chapterId,
                    tier,
                    status: 'queued',
                    job_id: `arq:content_pipeline:${lessonId}`,
                    truncation_expected: truncationExpected(chapter),
                },
                { status: 202 }
            );
        }
    ),
];

export { TOO_LARGE_CHAPTER };
