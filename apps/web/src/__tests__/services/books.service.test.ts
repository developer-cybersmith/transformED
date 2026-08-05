/**
 * Exercised through W0's MSW harness, not a module mock: these calls go through
 * the real axios instance in `@/lib/api`, its interceptors and its real URL
 * resolution (`baseURL` + relative, leading-slash-free path). A `vi.mock('@/lib/api')`
 * could not disconfirm any of that — DEFECT-REGISTER binding rule 2.
 */
import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { API_BASE } from '@/test/handlers';
import { UNKNOWN_BOOK_ID } from '@/test/fixtures';

import { booksService, watchableLessonId, isNotFoundError } from '@/services/books.service';
import {
    BOOKS,
    BOOK_PROCESSING,
    BOOK_READY,
    CHAPTER_LATEST_FAILED,
    CHAPTER_LESSON_COUNT_2,
    CHAPTER_LESSON_READY,
    CHAPTER_NO_LESSON,
    bookNotFoundError,
} from '../fixtures/books.fixtures';

describe('booksService — against the real HTTP contract', () => {
    it('resolves content/books to the right absolute URL and returns the real captured list', async () => {
        // If the relative path or the baseURL were wrong, MSW's
        // onUnhandledRequest: 'error' would fail this rather than pass.
        const books = await booksService.listBooks();

        expect(books).toEqual(BOOKS);
        expect(books.map((b) => b.status)).toEqual(['processing', 'ready']);
    });

    it('sends the limit as a query parameter the server actually receives', async () => {
        let seenLimit: string | null = null;
        server.use(
            http.get(`${API_BASE}/content/books`, ({ request }) => {
                seenLimit = new URL(request.url).searchParams.get('limit');
                return HttpResponse.json([], { status: 200 });
            }),
        );

        await booksService.listBooks(200);

        expect(seenLimit).toBe('200');
    });

    it('GETs one book and returns the real 1,151-page / 21-chapter capture', async () => {
        const book = await booksService.getBook(BOOK_READY.book_id);

        expect(book.filename).toBe('d2l.pdf');
        expect(book.page_count).toBe(1151);
        expect(book.chapter_count).toBe(21);
    });

    it('leaves page_count null and chapter_count 0 for a book that is still ingesting', async () => {
        const book = await booksService.getBook(BOOK_PROCESSING.book_id);

        expect(book.status).toBe('processing');
        expect(book.page_count).toBeNull();
        expect(book.chapter_count).toBe(0);
    });

    it('surfaces the contract 404 as an error isNotFoundError recognises', async () => {
        const error = await booksService.getBook(UNKNOWN_BOOK_ID).catch((e: unknown) => e);

        expect(isNotFoundError(error)).toBe(true);
    });

    it('GETs the chapters with the real captured page ranges, including [69..120]', async () => {
        const chapters = await booksService.listChapters(BOOK_READY.book_id);

        expect(chapters.map((c) => [c.page_start, c.page_end])).toEqual([
            [40, 68],
            [69, 120],
            [121, 163],
        ]);
        expect(chapters.map((c) => c.title)).toEqual([
            'Introduction',
            'Preliminaries',
            'Linear Neural Networks for Regression',
        ]);
    });

    it('returns an empty chapter list — not an error — for a book still ingesting', async () => {
        await expect(booksService.listChapters(BOOK_PROCESSING.book_id)).resolves.toEqual([]);
    });

    it('404s the chapter list for an unknown book with the same identical body', async () => {
        const error = await booksService.listChapters(UNKNOWN_BOOK_ID).catch((e: unknown) => e);

        expect(isNotFoundError(error)).toBe(true);
    });
});

describe('watchableLessonId — AC3, the Watch gate', () => {
    it('returns null for a chapter whose only lesson FAILED, even though has_lesson is true and lesson_id is non-null', () => {
        expect(CHAPTER_LATEST_FAILED.has_lesson).toBe(true);
        expect(CHAPTER_LATEST_FAILED.lesson_id).not.toBeNull();
        expect(CHAPTER_LATEST_FAILED.latest_lesson?.status).toBe('failed');

        expect(watchableLessonId(CHAPTER_LATEST_FAILED)).toBeNull();
    });

    it('returns null while the latest lesson is still running', () => {
        expect(CHAPTER_LESSON_COUNT_2.latest_lesson?.status).toBe('running');
        expect(watchableLessonId(CHAPTER_LESSON_COUNT_2)).toBeNull();
    });

    it('returns null while the latest lesson is queued', () => {
        expect(
            watchableLessonId({
                latest_lesson: { lesson_id: 'l1', status: 'queued', tier: 'T2', created_at: null },
            }),
        ).toBeNull();
    });

    it('returns null when the chapter has no lessons at all', () => {
        expect(watchableLessonId(CHAPTER_NO_LESSON)).toBeNull();
    });

    it('returns the latest lesson id only when its status is ready', () => {
        expect(watchableLessonId(CHAPTER_LESSON_READY)).toBe(CHAPTER_LESSON_READY.latest_lesson!.lesson_id);
    });
});

describe('isNotFoundError', () => {
    it('recognises the contract 404 shape', () => {
        expect(isNotFoundError(bookNotFoundError())).toBe(true);
    });

    it('does not treat a 500, a plain Error, or a nullish value as not-found', () => {
        expect(isNotFoundError({ response: { status: 500 } })).toBe(false);
        expect(isNotFoundError(new Error('network down'))).toBe(false);
        expect(isNotFoundError(null)).toBe(false);
        expect(isNotFoundError(undefined)).toBe(false);
    });
});
