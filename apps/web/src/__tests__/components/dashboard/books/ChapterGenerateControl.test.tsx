/**
 * Story W3 — the chapter card's Generate control, end to end through W0's MSW
 * harness. No `vi.mock('@/services/books.service')` anywhere: the component
 * makes real HTTP through the real axios instance, so these tests can actually
 * disconfirm the URL, the body encoding and the 202/200 distinction.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { API_BASE, lessonStoreSize } from '@/test/handlers';
import { UNKNOWN_BOOK_ID } from '@/test/fixtures';

import { ChapterRow } from '@/components/dashboard/books/ChapterRow';
import {
    ALREADY_GENERATING_MESSAGE,
    TRUNCATION_WARNING,
} from '@/components/dashboard/books/ChapterGenerateControl';
import {
    GENERATE_BOOK_NOT_READY_MESSAGE,
    GENERATE_INVALID_TIER_MESSAGE,
    GENERATE_NOT_FOUND_MESSAGE,
    GENERATE_RATE_LIMITED_MESSAGE,
    type ChapterResponse,
} from '@/services/books.service';
import {
    BOOK_PROCESSING,
    BOOK_READY,
    CHAPTER_NO_LESSON,
    CHAPTER_NO_TRUNCATION,
    CHAPTER_RATE_LIMITED,
    CHAPTER_TOO_LARGE,
    CHAPTER_TRUNCATING,
} from '../../../fixtures/books.fixtures';

afterEach(() => {
    vi.restoreAllMocks();
});

function renderRow(
    chapter: ChapterResponse,
    { bookId = BOOK_READY.book_id, onGenerated = vi.fn() } = {}
) {
    render(
        <ul>
            <ChapterRow chapter={chapter} bookId={bookId} onGenerated={onGenerated} />
        </ul>
    );
    return { onGenerated, user: userEvent.setup() };
}

/** Open the tier picker and choose one of S2-07's three cards. */
async function chooseTier(
    user: ReturnType<typeof userEvent.setup>,
    label: 'Deep' | 'Balanced' | 'Refresher'
) {
    await user.click(screen.getByRole('button', { name: /generate|retry|try again/i }));
    await user.click(screen.getByRole('button', { name: new RegExp(label, 'i') }));
}

describe('ChapterGenerateControl — ModeSelection is reused, not rebuilt (AC2)', () => {
    it('shows S2-07s three tier cards, disclaimers and all, when Generate is clicked', async () => {
        const { user } = renderRow(CHAPTER_NO_LESSON);

        await user.click(screen.getByRole('button', { name: /generate/i }));

        expect(screen.getByRole('button', { name: /Deep/i })).not.toBeNull();
        expect(screen.getByRole('button', { name: /Balanced/i })).not.toBeNull();
        expect(screen.getByRole('button', { name: /Refresher/i })).not.toBeNull();
        // S2-08's disclaimers ride along unchanged — proof this is the real
        // component and not a re-implementation of it.
        expect(screen.getAllByTestId('tier-disclaimer')).toHaveLength(2);
    });

    it('does not fire any request until a tier is actually chosen', async () => {
        let calls = 0;
        server.use(
            http.post(`${API_BASE}/content/books/:bookId/chapters/:chapterId/lessons`, () => {
                calls += 1;
                return HttpResponse.json({}, { status: 500 });
            })
        );
        const { user } = renderRow(CHAPTER_NO_LESSON);

        await user.click(screen.getByRole('button', { name: /generate/i }));

        expect(calls).toBe(0);
    });

    it('Cancel closes the picker without ever calling the API', async () => {
        let calls = 0;
        server.use(
            http.post(`${API_BASE}/content/books/:bookId/chapters/:chapterId/lessons`, () => {
                calls += 1;
                return HttpResponse.json({}, { status: 500 });
            })
        );
        const { user } = renderRow(CHAPTER_NO_LESSON);

        await user.click(screen.getByRole('button', { name: /generate/i }));
        await user.click(screen.getByRole('button', { name: /cancel/i }));

        expect(calls).toBe(0);
        expect(screen.queryByRole('button', { name: /^Deep/i })).toBeNull();
        expect(screen.getByRole('button', { name: /generate/i })).not.toBeNull();
    });
});

describe('ChapterGenerateControl — the tier reaches the body, mapped (S2-09, restored)', () => {
    it.each([
        ['Deep', 'T1'],
        ['Balanced', 'T2'],
        ['Refresher', 'T3'],
    ] as const)('sends %s as %s in a JSON body', async (label, expected) => {
        let seenBody: unknown = null;
        server.use(
            http.post(
                `${API_BASE}/content/books/:bookId/chapters/:chapterId/lessons`,
                async ({ request }) => {
                    seenBody = await request.json();
                    return HttpResponse.json(
                        {
                            lesson_id: 'l-1',
                            chapter_id: CHAPTER_NO_LESSON.chapter_id,
                            tier: expected,
                            status: 'queued',
                            job_id: 'j-1',
                            truncation_expected: false,
                        },
                        { status: 202 }
                    );
                }
            )
        );
        const { user } = renderRow(CHAPTER_NO_LESSON);

        await chooseTier(user, label);

        await waitFor(() => expect(seenBody).toEqual({ tier: expected }));
    });
});

describe('ChapterGenerateControl — 202 vs 200 (AC3, AC6)', () => {
    it('on 202, says generation started and revalidates the chapter list', async () => {
        const { user, onGenerated } = renderRow(CHAPTER_NO_LESSON);

        await chooseTier(user, 'Balanced');

        await waitFor(() => expect(screen.getByText(/we've started building/i)).not.toBeNull());
        expect(onGenerated).toHaveBeenCalledTimes(1);
        // AC6: the card's status comes from the server, never from local state.
        expect(screen.queryByText(ALREADY_GENERATING_MESSAGE)).toBeNull();
    });

    it('on a double-tap, says "already generating" instead of a second spinner claiming new work', async () => {
        const { user } = renderRow(CHAPTER_NO_LESSON);

        await chooseTier(user, 'Balanced');
        await waitFor(() => expect(screen.getByText(/we've started building/i)).not.toBeNull());

        // Same chapter, same tier, again — the 200 idempotent path.
        await chooseTier(user, 'Balanced');

        await waitFor(() =>
            expect(screen.getByText(ALREADY_GENERATING_MESSAGE)).not.toBeNull()
        );
        expect(screen.queryByText(/we've started building/i)).toBeNull();
        // Nothing was created the second time. Not double-counted.
        expect(lessonStoreSize()).toBe(1);
    });

    it('does not describe a 200 as new work even though its body looks like success', async () => {
        server.use(
            http.post(`${API_BASE}/content/books/:bookId/chapters/:chapterId/lessons`, () =>
                HttpResponse.json(
                    {
                        lesson_id: 'existing-1',
                        chapter_id: CHAPTER_NO_LESSON.chapter_id,
                        tier: 'T2',
                        // The 200 path echoes the EXISTING lesson's own status,
                        // which reads exactly like a fresh accept if you only
                        // look at the body.
                        status: 'generating',
                        job_id: null,
                        truncation_expected: false,
                    },
                    { status: 200 }
                )
            )
        );
        const { user } = renderRow(CHAPTER_NO_LESSON);

        await chooseTier(user, 'Balanced');

        await waitFor(() =>
            expect(screen.getByText(ALREADY_GENERATING_MESSAGE)).not.toBeNull()
        );
        expect(screen.queryByText(/we've started building/i)).toBeNull();
    });

    it('tells the student a 200 whose lesson is already READY is watchable', async () => {
        server.use(
            http.post(`${API_BASE}/content/books/:bookId/chapters/:chapterId/lessons`, () =>
                HttpResponse.json(
                    {
                        lesson_id: 'existing-1',
                        chapter_id: CHAPTER_NO_LESSON.chapter_id,
                        tier: 'T2',
                        status: 'ready',
                        job_id: null,
                        truncation_expected: false,
                    },
                    { status: 200 }
                )
            )
        );
        const { user } = renderRow(CHAPTER_NO_LESSON);

        await chooseTier(user, 'Balanced');

        await waitFor(() => expect(screen.getByText(/ready to watch/i)).not.toBeNull());
    });
});

describe('ChapterGenerateControl — truncation_expected is surfaced, not buried (AC5)', () => {
    it('warns before the wait that a wide chapter will only be partly covered', async () => {
        const { user } = renderRow(CHAPTER_TRUNCATING);

        await chooseTier(user, 'Balanced');

        await waitFor(() => expect(screen.getByText(TRUNCATION_WARNING)).not.toBeNull());
        // A warning, not an error: the lesson IS being generated.
        expect(screen.getByText(/we've started building/i)).not.toBeNull();
        expect(screen.queryByRole('alert')).toBeNull();
    });

    it('says nothing about truncation for a chapter that fits in the window', async () => {
        const { user } = renderRow(CHAPTER_NO_TRUNCATION);

        await chooseTier(user, 'Balanced');

        await waitFor(() => expect(screen.getByText(/we've started building/i)).not.toBeNull());
        expect(screen.queryByText(TRUNCATION_WARNING)).toBeNull();
    });
});

describe('ChapterGenerateControl — each documented failure gets its own message (AC4)', () => {
    it('409: the book is still ingesting', async () => {
        const { user } = renderRow(CHAPTER_NO_LESSON, { bookId: BOOK_PROCESSING.book_id });

        await chooseTier(user, 'Balanced');

        await waitFor(() =>
            expect(screen.getByText(GENERATE_BOOK_NOT_READY_MESSAGE)).not.toBeNull()
        );
        expect(screen.getByRole('alert')).not.toBeNull();
    });

    it('404: book or chapter gone', async () => {
        const { user } = renderRow(CHAPTER_NO_LESSON, { bookId: UNKNOWN_BOOK_ID });

        await chooseTier(user, 'Balanced');

        await waitFor(() => expect(screen.getByText(GENERATE_NOT_FOUND_MESSAGE)).not.toBeNull());
    });

    it('422 chapter_too_large: shows the real page numbers from the OBJECT detail', async () => {
        const { user } = renderRow(CHAPTER_TOO_LARGE);

        await chooseTier(user, 'Balanced');

        const alert = await screen.findByRole('alert');
        expect(alert.textContent).toContain('1,151');
        expect(alert.textContent).toContain('200');
    });

    it('422 tier: shows a distinct message and logs the client bug', async () => {
        const logged = vi.spyOn(console, 'error').mockImplementation(() => {});
        server.use(
            http.post(`${API_BASE}/content/books/:bookId/chapters/:chapterId/lessons`, () =>
                HttpResponse.json(
                    {
                        detail: [
                            {
                                type: 'literal_error',
                                loc: ['body', 'tier'],
                                msg: "Input should be 'T1', 'T2' or 'T3'",
                            },
                        ],
                    },
                    { status: 422 }
                )
            )
        );
        const { user } = renderRow(CHAPTER_NO_LESSON);

        await chooseTier(user, 'Balanced');

        await waitFor(() =>
            expect(screen.getByText(GENERATE_INVALID_TIER_MESSAGE)).not.toBeNull()
        );
        expect(logged).toHaveBeenCalled();
    });

    it('429: one message covering both causes, with the server-supplied wait', async () => {
        const { user } = renderRow(CHAPTER_RATE_LIMITED);

        await chooseTier(user, 'Balanced');

        const alert = await screen.findByRole('alert');
        expect(alert.textContent).toContain(GENERATE_RATE_LIMITED_MESSAGE);
        expect(alert.textContent).toContain('60 seconds');
    });

    it('never retries a failure on its own — the next attempt takes a click', async () => {
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
        const { user } = renderRow(CHAPTER_NO_LESSON);

        await chooseTier(user, 'Balanced');
        await screen.findByRole('alert');

        // Settle: an auto-retry would show up as a second call here.
        await new Promise((resolve) => setTimeout(resolve, 50));
        expect(calls).toBe(1);

        // And the recovery affordance is user-initiated, not automatic.
        await chooseTier(user, 'Balanced');
        await waitFor(() => expect(calls).toBe(2));
    });
});

describe('ChapterGenerateControl — a failed-only chapter offers Generate (AC7)', () => {
    it('offers Retry rather than Watch for the real captured failed chapter, and it works', async () => {
        expect(CHAPTER_NO_TRUNCATION.has_lesson).toBe(true);
        const { user, onGenerated } = renderRow(CHAPTER_NO_TRUNCATION);

        expect(screen.queryByRole('link', { name: /watch/i })).toBeNull();
        await chooseTier(user, 'Deep');

        await waitFor(() => expect(screen.getByText(/we've started building/i)).not.toBeNull());
        expect(onGenerated).toHaveBeenCalledTimes(1);
    });
});
