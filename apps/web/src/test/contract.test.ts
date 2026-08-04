/**
 * Contract conformance tests (Story W0, AC1–AC4, AC6).
 *
 * These are the tests the mutation check targets. They go through the REAL
 * axios instance (`@/lib/api`), its real interceptors and its real URL
 * resolution, against MSW handlers built from the frozen contract's captured
 * `real_example`. Nothing here mocks a module.
 *
 * The literal expectations below (1151, 21, 'd2l.pdf', 'toc', …) live in this
 * file, NOT in the fixture. That separation is what makes AC4 work: renaming or
 * re-valuing a field in `docs/contracts/book-api.v1.json` cannot also rewrite
 * the assertion that reads it.
 */
import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { api } from '@/lib/api';
import { extractErrorMessage, uploadService } from '@/services/upload.service';
import { server } from './server';
import { API_BASE } from './handlers';
import {
    BOOK_NOT_FOUND_DETAIL,
    CHAPTER_NOT_FOUND_DETAIL,
    PROCESSING_BOOK,
    RATE_LIMITED_CHAPTER,
    READY_BOOK,
    SMALL_CHAPTER,
    TOO_LARGE_CHAPTER,
    TRUNCATING_CHAPTER,
    UNKNOWN_BOOK_ID,
    UNKNOWN_CHAPTER_ID,
    UNLESSONED_CHAPTER,
} from './fixtures';

/** axios rejects on 4xx/5xx; this returns the raw response instead. */
const raw = { validateStatus: () => true };

function pdf(): File {
    return new File(['%PDF-1.4'], 'd2l.pdf', { type: 'application/pdf' });
}

function generateUrl(bookId: string, chapterId: string): string {
    return `content/books/${bookId}/chapters/${chapterId}/lessons`;
}

describe('MSW harness itself (AC1)', () => {
    it('fails a request the contract does not describe instead of letting it pass silently', async () => {
        await expect(api.get('content/not-a-real-endpoint')).rejects.toBeDefined();
    });

    it('resolves relative service paths against the axios baseURL the app actually uses', () => {
        expect(API_BASE).toBe('http://localhost:8000/api');
        expect(api.defaults.baseURL).toBe(API_BASE);
    });
});

describe('GET /content/books (AC3)', () => {
    it('returns the captured 2026-08-04 list, newest first', async () => {
        const { data } = await api.get('content/books');

        expect(data).toHaveLength(2);
        expect(data[0].filename).toBe('d2l.pdf');
        expect(data[0].status).toBe('processing');
        // A book still ingesting: page_count is null, chapter_count is 0 —
        // never null. This is the honest progress signal UploadFlow renders.
        expect(data[0].page_count).toBeNull();
        expect(data[0].chapter_count).toBe(0);

        expect(data[1].status).toBe('ready');
        expect(data[1].page_count).toBe(1151);
        expect(data[1].chapter_count).toBe(21);
    });

    it('honours limit/offset pagination', async () => {
        const { data } = await api.get('content/books', { params: { limit: 1, offset: 1 } });
        expect(data).toHaveLength(1);
        expect(data[0].book_id).toBe(READY_BOOK.book_id);
    });
});

describe('GET /content/books/{book_id} (AC3)', () => {
    it('returns the same shape as the list route', async () => {
        const data = await uploadService.getBookStatus(READY_BOOK.book_id);

        expect(data.book_id).toBe('dfea46ac-1c6e-401a-a936-269eedd3e5d9');
        expect(data.filename).toBe('d2l.pdf');
        expect(data.status).toBe('ready');
        expect(data.page_count).toBe(1151);
        expect(data.chapter_count).toBe(21);
        expect(data.created_at).toBe('2026-08-04T10:55:09.608627+00:00');
    });

    it('404s with the enumeration-safe body — never 403', async () => {
        const res = await api.get(`content/books/${UNKNOWN_BOOK_ID}`, raw);
        expect(res.status).toBe(404);
        expect(res.data).toEqual({ detail: BOOK_NOT_FOUND_DETAIL });
    });
});

describe('GET /content/books/{book_id}/chapters (AC3)', () => {
    it('returns chapters ordered by chapter_index with real lesson linkage', async () => {
        const { data } = await api.get(`content/books/${READY_BOOK.book_id}/chapters`);

        expect(data).toHaveLength(3);
        expect(data.map((c: { chapter_index: number }) => c.chapter_index)).toEqual([0, 1, 2]);

        const intro = data[0];
        expect(intro.title).toBe('Introduction');
        expect(intro.page_start).toBe(40);
        expect(intro.page_end).toBe(68);
        expect(intro.boundary_confidence).toBe('toc');
        // One chapter carrying THREE lessons — the case the dead scalar
        // chapters.lesson_id could never express.
        expect(intro.lesson_count).toBe(3);
        expect(intro.has_lesson).toBe(true);
        expect(intro.latest_lesson.status).toBe('failed');
        expect(intro.latest_lesson.tier).toBe('T3');
        expect(intro.latest_lesson.lesson_id).toBe(intro.lesson_id);
    });

    it('represents a chapter with no lessons as the NORMAL state, not an error', async () => {
        const { data } = await api.get(`content/books/${READY_BOOK.book_id}/chapters`);
        const bare = data[2];

        expect(bare.lesson_id).toBeNull();
        expect(bare.has_lesson).toBe(false);
        expect(bare.lesson_count).toBe(0);
        expect(bare.latest_lesson).toBeNull();
    });

    it('has_lesson=true is NOT sufficient to render a Watch button — the newest lesson failed', async () => {
        const { data } = await api.get(`content/books/${READY_BOOK.book_id}/chapters`);
        const intro = data[0];
        expect(intro.has_lesson).toBe(true);
        expect(intro.latest_lesson.status).toBe('failed');
    });

    it('returns an empty list (not a 404) for a book still ingesting', async () => {
        const res = await api.get(`content/books/${PROCESSING_BOOK.book_id}/chapters`, raw);
        expect(res.status).toBe(200);
        expect(res.data).toEqual([]);
    });

    it('404s for an unknown book', async () => {
        const res = await api.get(`content/books/${UNKNOWN_BOOK_ID}/chapters`, raw);
        expect(res.status).toBe(404);
        expect(res.data).toEqual({ detail: BOOK_NOT_FOUND_DETAIL });
    });
});

describe('POST /content/lessons — book ingestion (AC3, AC5)', () => {
    it('202s over real HTTP and returns a book_id, with NO lesson_id anywhere', async () => {
        const data = await uploadService.uploadLesson(pdf());

        expect(data.book_id).toBe(PROCESSING_BOOK.book_id);
        expect(data.status).toBe('queued');
        expect(data).not.toHaveProperty('lesson_id');
    });

    it('422s when tier is present — the failure that made 100 % of uploads fail', async () => {
        const form = new FormData();
        form.append('file', pdf());
        form.append('tier', 'T3');

        const res = await api.post('content/lessons', form, raw);

        expect(res.status).toBe(422);
        expect(res.data.detail).toContain('a book has no tier');
    });

    it('the real uploadService never trips that 422', async () => {
        const res = await uploadService.uploadLesson(pdf());
        expect(res.book_id).toBeTruthy();
    });
});

describe('POST /content/books/{id}/chapters/{cid}/lessons (AC3)', () => {
    it('202 on create: status queued, non-null job_id, tier echoed back', async () => {
        const res = await api.post(
            generateUrl(READY_BOOK.book_id, UNLESSONED_CHAPTER.chapter_id),
            { tier: 'T1' },
            raw
        );

        expect(res.status).toBe(202);
        expect(res.data.status).toBe('queued');
        expect(res.data.job_id).not.toBeNull();
        expect(res.data.tier).toBe('T1');
        expect(res.data.chapter_id).toBe(UNLESSONED_CHAPTER.chapter_id);
        // 121..163 = 43 pages, past the 40-page LLM-visible window.
        expect(res.data.truncation_expected).toBe(true);
    });

    it('defaults to T2 when tier is omitted', async () => {
        const res = await api.post(
            generateUrl(READY_BOOK.book_id, UNLESSONED_CHAPTER.chapter_id),
            {},
            raw
        );
        expect(res.status).toBe(202);
        expect(res.data.tier).toBe('T2');
    });

    it('truncation_expected is false for a chapter inside the visible window', async () => {
        // Chapter 0: pages 40..68 = 29 pages.
        const res = await api.post(
            generateUrl(READY_BOOK.book_id, SMALL_CHAPTER.chapter_id),
            { tier: 'T2' },
            raw
        );
        expect(res.status).toBe(202);
        expect(res.data.truncation_expected).toBe(false);
    });

    it('200 on the idempotent repeat: SAME lesson_id, job_id ALWAYS null', async () => {
        const first = await api.post(
            generateUrl(READY_BOOK.book_id, TRUNCATING_CHAPTER.chapter_id),
            { tier: 'T3' },
            raw
        );
        const second = await api.post(
            generateUrl(READY_BOOK.book_id, TRUNCATING_CHAPTER.chapter_id),
            { tier: 'T3' },
            raw
        );

        expect(first.status).toBe(202);
        expect(second.status).toBe(200);
        expect(second.data.lesson_id).toBe(first.data.lesson_id);
        expect(second.data.job_id).toBeNull();
        expect(second.data.status).toBe('generating');
    });

    it('the same chapter at a DIFFERENT tier is always a new lesson', async () => {
        const t1 = await api.post(
            generateUrl(READY_BOOK.book_id, TRUNCATING_CHAPTER.chapter_id),
            { tier: 'T1' },
            raw
        );
        const t3 = await api.post(
            generateUrl(READY_BOOK.book_id, TRUNCATING_CHAPTER.chapter_id),
            { tier: 'T3' },
            raw
        );

        expect(t1.status).toBe(202);
        expect(t3.status).toBe(202);
        expect(t3.data.lesson_id).not.toBe(t1.data.lesson_id);
    });

    it('404 "Book not found" for an unknown book', async () => {
        const res = await api.post(
            generateUrl(UNKNOWN_BOOK_ID, SMALL_CHAPTER.chapter_id),
            { tier: 'T2' },
            raw
        );
        expect(res.status).toBe(404);
        expect(res.data).toEqual({ detail: BOOK_NOT_FOUND_DETAIL });
    });

    it('404 "Chapter not found" for a chapter of a different book the caller owns', async () => {
        const res = await api.post(
            generateUrl(READY_BOOK.book_id, UNKNOWN_CHAPTER_ID),
            { tier: 'T2' },
            raw
        );
        expect(res.status).toBe(404);
        expect(res.data).toEqual({ detail: CHAPTER_NOT_FOUND_DETAIL });
    });

    it('409 when the book is still detecting chapters — retryable, not a 404', async () => {
        const res = await api.post(
            generateUrl(PROCESSING_BOOK.book_id, SMALL_CHAPTER.chapter_id),
            { tier: 'T2' },
            raw
        );
        expect(res.status).toBe(409);
        expect(res.data.detail).toBe('Book is not ready — chapter detection has not finished');
    });

    it('422 FastAPI array form for a tier outside T1/T2/T3', async () => {
        const res = await api.post(
            generateUrl(READY_BOOK.book_id, SMALL_CHAPTER.chapter_id),
            { tier: 'T9' },
            raw
        );
        expect(res.status).toBe(422);
        expect(Array.isArray(res.data.detail)).toBe(true);
        expect(res.data.detail[0].loc).toEqual(['body', 'tier']);
    });

    it('422 chapter_too_large with an OBJECT detail, not a string', async () => {
        const res = await api.post(
            generateUrl(READY_BOOK.book_id, TOO_LARGE_CHAPTER.chapter_id),
            { tier: 'T2' },
            raw
        );

        expect(res.status).toBe(422);
        expect(typeof res.data.detail).toBe('object');
        expect(Array.isArray(res.data.detail)).toBe(false);
        expect(res.data.detail.code).toBe('chapter_too_large');
        // The whole 1,151-page document detected as one chapter — the rung-5
        // failure the 200-page gate exists to refuse.
        expect(res.data.detail.page_span).toBe(1151);
        expect(res.data.detail.max_page_span).toBe(200);
        expect(res.data.detail.boundary_confidence).toBe('fallback');
    });

    it('429 carries Retry-After so the client can back off', async () => {
        const res = await api.post(
            generateUrl(READY_BOOK.book_id, RATE_LIMITED_CHAPTER.chapter_id),
            { tier: 'T2' },
            raw
        );
        expect(res.status).toBe(429);
        expect(res.headers['retry-after']).toBe('60');
        expect(res.data.detail).toContain('already generating');
    });
});

describe('extractErrorMessage against a real wire response (AC6)', () => {
    it('renders page_span/max_page_span from the object-shaped 422, not the fallback', async () => {
        let caught: unknown;
        try {
            await api.post(
                generateUrl(READY_BOOK.book_id, TOO_LARGE_CHAPTER.chapter_id),
                { tier: 'T2' }
            );
        } catch (err) {
            caught = err;
        }

        const message = extractErrorMessage(caught, 'Could not start this lesson.');

        expect(message).not.toBe('Could not start this lesson.');
        expect(message).toContain('1,151');
        expect(message).toContain('200');
    });

    it('still reads the plain-string 422 the upload endpoint returns', async () => {
        const form = new FormData();
        form.append('file', pdf());
        form.append('tier', 'T3');

        let caught: unknown;
        try {
            await api.post('content/lessons', form);
        } catch (err) {
            caught = err;
        }

        expect(extractErrorMessage(caught, 'fallback')).toContain('a book has no tier');
    });
});

describe('per-test handler overrides (AC1)', () => {
    it('server.use() overrides for one test only and is reset afterwards', async () => {
        server.use(
            http.get(`${API_BASE}/content/books`, () =>
                HttpResponse.json({ detail: 'boom' }, { status: 500 })
            )
        );

        const overridden = await api.get('content/books', raw);
        expect(overridden.status).toBe(500);
    });

    it('sees the contract handler again in the next test', async () => {
        const { data } = await api.get('content/books');
        expect(data).toHaveLength(2);
    });
});
