/**
 * End-to-end through the real hooks, the real SWR cache, the real axios client
 * and W0's MSW handlers — the only thing stubbed is the signed-in user, because
 * `@/lib/api`'s interceptor reads Supabase, not the API under test.
 *
 * The narrower page/component tests mock the hooks; this file exists so at
 * least one path proves the whole chain (relative path → baseURL → HTTP →
 * parsed contract shape → rendered DOM) actually joins up.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { SWRConfig } from 'swr';
import { server } from '@/test/server';
import { API_BASE } from '@/test/handlers';
import { UNKNOWN_BOOK_ID } from '@/test/fixtures';

const { useAuthMock } = vi.hoisted(() => ({ useAuthMock: vi.fn() }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: useAuthMock }));

import BooksPage from '@/app/(dashboard)/books/page';
import { BookDetail } from '@/components/dashboard/books/BookDetail';
import { BOOK_READY } from '../../fixtures/books.fixtures';

// A fresh SWR cache per test — otherwise one test's fetched books satisfy the
// next test's render and it passes without ever hitting MSW.
function renderIsolated(ui: React.ReactElement) {
    return render(
        <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{ui}</SWRConfig>,
    );
}

beforeEach(() => {
    useAuthMock.mockReset();
    useAuthMock.mockReturnValue({ user: { id: 'user_1', email: 'a@b.com' } });
});

describe('Books, end to end over MSW', () => {
    it('lists the real captured books fetched over HTTP', async () => {
        renderIsolated(<BooksPage />);

        await waitFor(() => expect(screen.getByText('21 chapters')).not.toBeNull());
        expect(screen.getByText('1151 pages')).not.toBeNull();
        expect(screen.getByText(/detecting chapters/i)).not.toBeNull();
    });

    it('renders the real chapters of the ready book, with the captured [69..120] range and the two-lesson chapter', async () => {
        renderIsolated(<BookDetail bookId={BOOK_READY.book_id} />);

        await waitFor(() => expect(screen.getByText('Preliminaries')).not.toBeNull());
        expect(screen.getByText(/PDF pages 69–120/)).not.toBeNull();
        expect(screen.getByText('2 lessons')).not.toBeNull();
        expect(screen.getByText('3 lessons')).not.toBeNull();
    });

    it('renders NO Watch button anywhere in the real capture — no chapter has a ready lesson', async () => {
        renderIsolated(<BookDetail bookId={BOOK_READY.book_id} />);

        await waitFor(() => expect(screen.getByText('Introduction')).not.toBeNull());
        // Chapter 0's latest lesson FAILED while has_lesson is true; chapter 1's
        // is running; chapter 2 has none. Watch must appear for none of them.
        expect(screen.queryByRole('link', { name: /watch/i })).toBeNull();
    });

    it('shows a Watch link once the server reports the latest lesson as ready', async () => {
        server.use(
            http.get(`${API_BASE}/content/books/:bookId/chapters`, () =>
                HttpResponse.json(
                    [
                        {
                            chapter_id: 'c-ready',
                            chapter_index: 0,
                            title: 'Preliminaries',
                            page_start: 69,
                            page_end: 120,
                            boundary_confidence: 'toc',
                            lesson_id: '6cbbe233-415f-4523-9541-0bde06d4c567',
                            has_lesson: true,
                            lesson_count: 2,
                            latest_lesson: {
                                lesson_id: '6cbbe233-415f-4523-9541-0bde06d4c567',
                                status: 'ready',
                                tier: 'T3',
                                created_at: '2026-08-04T11:12:51.946256+00:00',
                            },
                        },
                    ],
                    { status: 200 },
                ),
            ),
        );

        renderIsolated(<BookDetail bookId={BOOK_READY.book_id} />);

        await waitFor(() =>
            expect(screen.getByRole('link', { name: /watch/i }).getAttribute('href')).toBe(
                '/lesson/6cbbe233-415f-4523-9541-0bde06d4c567',
            ),
        );
    });

    it('renders a not-found state, not a crash, when the API returns the contract 404', async () => {
        renderIsolated(<BookDetail bookId={UNKNOWN_BOOK_ID} />);

        await waitFor(() => expect(screen.getByText(/couldn't find that book/i)).not.toBeNull());
        expect(screen.getByRole('link', { name: /back to your books/i })).not.toBeNull();
    });
});
