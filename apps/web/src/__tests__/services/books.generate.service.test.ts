/**
 * Story W3 — `booksService.generateLesson` and its failure vocabulary.
 *
 * Exercised through W0's MSW harness, which intercepts real HTTP: these calls go
 * through the real axios instance in `@/lib/api`, its interceptors, and its real
 * relative-path-plus-baseURL resolution. `onUnhandledRequest: 'error'` means a
 * wrong URL FAILS here rather than passing quietly against a module mock —
 * DEFECT-REGISTER binding rule 2.
 *
 * Kept in its own file rather than appended to `books.service.test.ts` so W2's
 * file is not edited by a second author (Story W3 ownership note).
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { API_BASE, lessonStoreSize } from '@/test/handlers';
import { UNKNOWN_BOOK_ID, UNKNOWN_CHAPTER_ID } from '@/test/fixtures';
import { LEARNER_TIER_TO_BACKEND } from '@/types/learnerMode';

import {
    booksService,
    generateLessonErrorMessage,
    GENERATE_BOOK_NOT_READY_MESSAGE,
    GENERATE_FALLBACK_MESSAGE,
    GENERATE_INVALID_TIER_MESSAGE,
    GENERATE_NOT_FOUND_MESSAGE,
    GENERATE_RATE_LIMITED_MESSAGE,
    type LessonTier,
} from '@/services/books.service';
import {
    BOOK_PROCESSING,
    BOOK_READY,
    CHAPTER_NO_LESSON,
    CHAPTER_NO_TRUNCATION,
    CHAPTER_RATE_LIMITED,
    CHAPTER_TOO_LARGE,
    CHAPTER_TRUNCATING,
} from '../fixtures/books.fixtures';

afterEach(() => {
    vi.restoreAllMocks();
});

/** Rejection helper: the service throws on every non-2xx, so this is the shape. */
async function rejection(promise: Promise<unknown>): Promise<unknown> {
    try {
        await promise;
    } catch (error) {
        return error;
    }
    throw new Error('expected generateLesson to reject, but it resolved');
}

describe('generateLesson — the request itself (S2-09, re-pointed)', () => {
    it('POSTs a JSON body carrying the tier — the S2-09 assertion, at the new endpoint', async () => {
        // S2-09 asserted `expect(body.get('tier')).toBe('T3')` against a
        // FormData body on POST content/lessons. That endpoint now 422s on the
        // mere presence of `tier`. Same guarantee, new home and new encoding.
        let seenBody: unknown = null;
        let seenContentType: string | null = null;
        let seenUrl: string | null = null;

        server.use(
            http.post(
                `${API_BASE}/content/books/:bookId/chapters/:chapterId/lessons`,
                async ({ request }) => {
                    seenUrl = request.url;
                    seenContentType = request.headers.get('content-type');
                    seenBody = await request.json();
                    return HttpResponse.json(
                        {
                            lesson_id: 'l-1',
                            chapter_id: CHAPTER_NO_LESSON.chapter_id,
                            tier: 'T3',
                            status: 'queued',
                            job_id: 'arq:content_pipeline:l-1',
                            truncation_expected: false,
                        },
                        { status: 202 }
                    );
                }
            )
        );

        await booksService.generateLesson(
            BOOK_READY.book_id,
            CHAPTER_NO_LESSON.chapter_id,
            LEARNER_TIER_TO_BACKEND.refresher
        );

        expect(seenBody).toEqual({ tier: 'T3' });
        expect(seenContentType).toMatch(/application\/json/);
        expect(seenUrl).toBe(
            `${API_BASE}/content/books/${BOOK_READY.book_id}/chapters/${CHAPTER_NO_LESSON.chapter_id}/lessons`
        );
    });

    it('never sends a page range — a client-supplied one would bypass the size gate', async () => {
        let seenBody: Record<string, unknown> = {};
        server.use(
            http.post(
                `${API_BASE}/content/books/:bookId/chapters/:chapterId/lessons`,
                async ({ request }) => {
                    seenBody = (await request.json()) as Record<string, unknown>;
                    return HttpResponse.json(
                        {
                            lesson_id: 'l-1',
                            chapter_id: CHAPTER_NO_LESSON.chapter_id,
                            tier: 'T2',
                            status: 'queued',
                            job_id: 'j',
                            truncation_expected: false,
                        },
                        { status: 202 }
                    );
                }
            )
        );

        await booksService.generateLesson(BOOK_READY.book_id, CHAPTER_NO_LESSON.chapter_id, 'T2');

        expect(Object.keys(seenBody)).toEqual(['tier']);
    });

    it.each(Object.entries(LEARNER_TIER_TO_BACKEND))(
        'maps the "%s" learner tier to %s and the server accepts it',
        async (_learnerTier, backendTier) => {
            const { lesson } = await booksService.generateLesson(
                BOOK_READY.book_id,
                CHAPTER_NO_LESSON.chapter_id,
                backendTier as LessonTier
            );

            // Echoed back by the server, so this is the SERVER's view of the
            // tier, not the value we just sent read back out of our own object.
            expect(lesson.tier).toBe(backendTier);
        }
    );
});

describe('generateLesson — 202 and 200 are different events (AC3)', () => {
    it('reports created: true with a real job_id on the 202 create path', async () => {
        const { created, lesson } = await booksService.generateLesson(
            BOOK_READY.book_id,
            CHAPTER_NO_LESSON.chapter_id,
            'T2'
        );

        expect(created).toBe(true);
        expect(lesson.status).toBe('queued');
        expect(lesson.job_id).not.toBeNull();
    });

    it('reports created: false with job_id null when an equivalent lesson already exists', async () => {
        const first = await booksService.generateLesson(
            BOOK_READY.book_id,
            CHAPTER_NO_LESSON.chapter_id,
            'T2'
        );
        const second = await booksService.generateLesson(
            BOOK_READY.book_id,
            CHAPTER_NO_LESSON.chapter_id,
            'T2'
        );

        expect(second.created).toBe(false);
        // Same lesson, nothing enqueued, no second row created.
        expect(second.lesson.lesson_id).toBe(first.lesson.lesson_id);
        expect(second.lesson.job_id).toBeNull();
        expect(lessonStoreSize()).toBe(1);
    });

    it('treats the SAME chapter at a DIFFERENT tier as a genuinely new lesson', async () => {
        const t2 = await booksService.generateLesson(
            BOOK_READY.book_id,
            CHAPTER_NO_LESSON.chapter_id,
            'T2'
        );
        const t1 = await booksService.generateLesson(
            BOOK_READY.book_id,
            CHAPTER_NO_LESSON.chapter_id,
            'T1'
        );

        expect(t1.created).toBe(true);
        expect(t1.lesson.lesson_id).not.toBe(t2.lesson.lesson_id);
        expect(lessonStoreSize()).toBe(2);
    });
});

describe('generateLesson — truncation_expected (AC5)', () => {
    it('is true for a chapter wider than the ~40-page LLM window, and is not an error', async () => {
        expect(CHAPTER_TRUNCATING.page_end - CHAPTER_TRUNCATING.page_start + 1).toBeGreaterThan(40);

        const { created, lesson } = await booksService.generateLesson(
            BOOK_READY.book_id,
            CHAPTER_TRUNCATING.chapter_id,
            'T2'
        );

        expect(lesson.truncation_expected).toBe(true);
        // The request was ACCEPTED. A truncation warning never blocks it.
        expect(created).toBe(true);
    });

    it('is false for a chapter that fits inside the window', async () => {
        expect(
            CHAPTER_NO_TRUNCATION.page_end - CHAPTER_NO_TRUNCATION.page_start + 1
        ).toBeLessThanOrEqual(40);

        const { lesson } = await booksService.generateLesson(
            BOOK_READY.book_id,
            CHAPTER_NO_TRUNCATION.chapter_id,
            'T2'
        );

        expect(lesson.truncation_expected).toBe(false);
    });
});

describe('generateLessonErrorMessage — every documented failure is distinct (AC4)', () => {
    it('409: says the book is still ingesting and that waiting fixes it', async () => {
        const error = await rejection(
            booksService.generateLesson(BOOK_PROCESSING.book_id, CHAPTER_NO_LESSON.chapter_id, 'T2')
        );

        expect(generateLessonErrorMessage(error)).toBe(GENERATE_BOOK_NOT_READY_MESSAGE);
        expect(GENERATE_BOOK_NOT_READY_MESSAGE).toMatch(/try again/i);
    });

    it('404 on an unknown book: one message, making no attempt to distinguish the causes', async () => {
        const error = await rejection(
            booksService.generateLesson(UNKNOWN_BOOK_ID, CHAPTER_NO_LESSON.chapter_id, 'T2')
        );

        expect(generateLessonErrorMessage(error)).toBe(GENERATE_NOT_FOUND_MESSAGE);
    });

    it('404 on an unknown chapter: the SAME message as the unknown-book 404', async () => {
        const error = await rejection(
            booksService.generateLesson(BOOK_READY.book_id, UNKNOWN_CHAPTER_ID, 'T2')
        );

        // The identical body is deliberate, so the identical message is too.
        expect(generateLessonErrorMessage(error)).toBe(GENERATE_NOT_FOUND_MESSAGE);
    });

    it('422 chapter_too_large: shows the REAL page numbers from the object detail', async () => {
        const error = await rejection(
            booksService.generateLesson(BOOK_READY.book_id, CHAPTER_TOO_LARGE.chapter_id, 'T2')
        );

        const message = generateLessonErrorMessage(error);

        // The whole point: the numbers survive. The generic fallback throws away
        // the only information that explains the refusal.
        expect(message).toContain('1,151');
        expect(message).toContain('200');
        expect(message).not.toBe(GENERATE_FALLBACK_MESSAGE);
        // `boundary_confidence: 'fallback'` means detection found nothing at all,
        // which is a different user action from "this chapter is enormous".
        expect(message).toMatch(/couldn't find chapter boundaries/i);
    });

    it('422 chapter_too_large with a real boundary: names the span, not a detection failure', () => {
        const error = {
            response: {
                status: 422,
                data: {
                    detail: {
                        code: 'chapter_too_large',
                        page_span: 412,
                        max_page_span: 200,
                        boundary_confidence: 'toc',
                    },
                },
            },
        };

        const message = generateLessonErrorMessage(error);

        expect(message).toContain('412');
        expect(message).toContain('200');
        expect(message).not.toMatch(/couldn't find chapter boundaries/i);
    });

    it('422 tier: is treated as a client bug — distinct message, and logged', async () => {
        const logged = vi.spyOn(console, 'error').mockImplementation(() => {});

        const error = await rejection(
            booksService.generateLesson(
                BOOK_READY.book_id,
                CHAPTER_NO_LESSON.chapter_id,
                'T9' as LessonTier
            )
        );

        expect(generateLessonErrorMessage(error)).toBe(GENERATE_INVALID_TIER_MESSAGE);
        expect(logged).toHaveBeenCalled();
        expect(String(logged.mock.calls[0][0])).toMatch(/client bug/i);
    });

    it('429: one message for both causes, plus the server-supplied wait', async () => {
        const error = await rejection(
            booksService.generateLesson(BOOK_READY.book_id, CHAPTER_RATE_LIMITED.chapter_id, 'T2')
        );

        const message = generateLessonErrorMessage(error);

        expect(message).toContain(GENERATE_RATE_LIMITED_MESSAGE);
        expect(message).toContain('60 seconds');
        // It must NOT claim to know which of the two 429 causes fired.
        expect(message).not.toMatch(/rate limit|concurren/i);
    });

    it('429 without a Retry-After (the rate-limit variant): same message, no invented wait', () => {
        const message = generateLessonErrorMessage({
            response: { status: 429, headers: {}, data: { detail: 'Rate limit exceeded' } },
        });

        expect(message).toBe(GENERATE_RATE_LIMITED_MESSAGE);
        expect(message).not.toMatch(/seconds/);
    });

    it('falls back honestly on an undocumented failure rather than inventing a cause', () => {
        expect(generateLessonErrorMessage({ response: { status: 500, data: {} } })).toBe(
            GENERATE_FALLBACK_MESSAGE
        );
        expect(generateLessonErrorMessage(new Error('Network Error'))).toBe(
            GENERATE_FALLBACK_MESSAGE
        );
    });

    it('produces a DIFFERENT message for every documented status (AC4, as one assertion)', async () => {
        const messages = [
            GENERATE_NOT_FOUND_MESSAGE,
            GENERATE_BOOK_NOT_READY_MESSAGE,
            GENERATE_INVALID_TIER_MESSAGE,
            GENERATE_RATE_LIMITED_MESSAGE,
            GENERATE_FALLBACK_MESSAGE,
        ];

        expect(new Set(messages).size).toBe(messages.length);
    });
});

describe('generateLesson — never retries on its own (rate-limit budget)', () => {
    it('issues exactly ONE request when the server 429s', async () => {
        let calls = 0;
        server.use(
            http.post(`${API_BASE}/content/books/:bookId/chapters/:chapterId/lessons`, () => {
                calls += 1;
                return HttpResponse.json(
                    { detail: 'Too many lessons are already generating' },
                    { status: 429, headers: { 'Retry-After': '60' } }
                );
            })
        );

        await rejection(
            booksService.generateLesson(BOOK_READY.book_id, CHAPTER_NO_LESSON.chapter_id, 'T2')
        );

        // 3/minute and 20/hour, per user. An automatic retry spends the
        // student's budget and locks them out of their own book.
        expect(calls).toBe(1);
    });

    it('issues exactly ONE request when the server 500s', async () => {
        let calls = 0;
        server.use(
            http.post(`${API_BASE}/content/books/:bookId/chapters/:chapterId/lessons`, () => {
                calls += 1;
                return HttpResponse.json({ detail: 'boom' }, { status: 500 });
            })
        );

        await rejection(
            booksService.generateLesson(BOOK_READY.book_id, CHAPTER_NO_LESSON.chapter_id, 'T2')
        );

        expect(calls).toBe(1);
    });
});

describe('watchableLessonId is untouched by W3 (AC7)', () => {
    it('a chapter whose only lesson failed still offers Generate, not Watch', async () => {
        // Regression sentinel: the real captured chapter 0 has has_lesson: true
        // and a non-null lesson_id, and its latest lesson FAILED. Weakening the
        // gate to has_lesson would hand the player a lesson that 404s.
        expect(CHAPTER_NO_TRUNCATION.has_lesson).toBe(true);
        expect(CHAPTER_NO_TRUNCATION.lesson_id).not.toBeNull();
        expect(CHAPTER_NO_TRUNCATION.latest_lesson?.status).toBe('failed');

        const { created } = await booksService.generateLesson(
            BOOK_READY.book_id,
            CHAPTER_NO_TRUNCATION.chapter_id,
            'T2'
        );

        // A 'failed' lesson does not match the idempotency pre-check: retrying
        // after a failure generates fresh and returns 202.
        expect(created).toBe(true);
    });
});
