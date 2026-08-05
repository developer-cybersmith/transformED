import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';

const { useSWRMock } = vi.hoisted(() => ({ useSWRMock: vi.fn() }));

vi.mock('swr', () => ({ default: useSWRMock }));

const { listBooksMock, getBookMock, useAuthMock } = vi.hoisted(() => ({
    listBooksMock: vi.fn(),
    getBookMock: vi.fn(),
    useAuthMock: vi.fn(),
}));

vi.mock('@/services/books.service', () => ({
    booksService: { listBooks: listBooksMock, getBook: getBookMock },
}));

vi.mock('@/contexts/AuthContext', () => ({ useAuth: useAuthMock }));

import { useBooks, useBook } from '@/hooks/useBooks';
import { BOOKS, BOOK_PROCESSING, BOOK_READY } from '../fixtures/books.fixtures';

beforeEach(() => {
    useSWRMock.mockReset();
    listBooksMock.mockReset();
    getBookMock.mockReset();
    useAuthMock.mockReset();
    useAuthMock.mockReturnValue({ user: { id: 'user_1', email: 'a@b.com' } });
    useSWRMock.mockReturnValue({ data: undefined, error: undefined, isLoading: true });
});

describe('useBooks', () => {
    it("scopes the SWR cache key by user id — a shared tab must not leak one account's books into another's", () => {
        renderHook(() => useBooks());

        expect(useSWRMock).toHaveBeenCalledWith('books:user_1', expect.any(Function), expect.anything());
    });

    it('uses a different cache key for a different user', () => {
        useAuthMock.mockReturnValue({ user: { id: 'user_2' } });

        renderHook(() => useBooks());

        expect(useSWRMock).toHaveBeenCalledWith('books:user_2', expect.any(Function), expect.anything());
    });

    it('does not fetch at all before there is an authenticated user', () => {
        useAuthMock.mockReturnValue({ user: null });

        renderHook(() => useBooks());

        expect(useSWRMock).toHaveBeenCalledWith(null, expect.any(Function), expect.anything());
    });

    it('retries on error so a transient failure cannot permanently pause polling', () => {
        renderHook(() => useBooks());

        expect(useSWRMock).toHaveBeenCalledWith(
            expect.anything(),
            expect.any(Function),
            expect.objectContaining({ shouldRetryOnError: true }),
        );
    });

    it('returns the fetched books and normalises undefined to null', () => {
        useSWRMock.mockReturnValue({ data: BOOKS, error: undefined, isLoading: false });
        expect(renderHook(() => useBooks()).result.current.data).toEqual(BOOKS);

        useSWRMock.mockReturnValue({ data: undefined, error: undefined, isLoading: false });
        expect(renderHook(() => useBooks()).result.current.data).toBeNull();
    });
});

function refreshIntervalOf(hook: () => unknown): (data: unknown) => number {
    renderHook(hook);
    return useSWRMock.mock.calls[useSWRMock.mock.calls.length - 1][2].refreshInterval;
}

describe('useBooks — polling on the BOOK vocabulary', () => {
    it("polls while at least one book is still 'processing'", () => {
        const refreshInterval = refreshIntervalOf(() => useBooks());

        expect(refreshInterval([BOOK_PROCESSING, BOOK_READY])).toBeGreaterThan(0);
    });

    it('does not poll once every book is ready — note "ready" is NOT in the lesson vocabulary isLessonProcessing checks', () => {
        const refreshInterval = refreshIntervalOf(() => useBooks());

        expect(refreshInterval([BOOK_READY])).toBe(0);
    });

    it('does not poll before any data has arrived', () => {
        const refreshInterval = refreshIntervalOf(() => useBooks());

        expect(refreshInterval(undefined)).toBe(0);
    });

    it('stops polling after the 20-minute ceiling even if the book is still processing', () => {
        vi.useFakeTimers();
        vi.setSystemTime(0);
        const refreshInterval = refreshIntervalOf(() => useBooks());

        expect(refreshInterval([BOOK_PROCESSING])).toBeGreaterThan(0);
        vi.setSystemTime(20 * 60 * 1000 + 1);
        expect(refreshInterval([BOOK_PROCESSING])).toBe(0);

        vi.useRealTimers();
    });
});

describe('useBook', () => {
    it('keys by user id AND book id', () => {
        renderHook(() => useBook(BOOK_READY.book_id));

        expect(useSWRMock).toHaveBeenCalledWith(
            `book:user_1:${BOOK_READY.book_id}`,
            expect.any(Function),
            expect.anything(),
        );
    });

    it('does not fetch without a book id', () => {
        renderHook(() => useBook(''));

        expect(useSWRMock).toHaveBeenCalledWith(null, expect.any(Function), expect.anything());
    });

    it("polls while the book is 'processing' and stops once it is ready", () => {
        const refreshInterval = refreshIntervalOf(() => useBook(BOOK_READY.book_id));

        expect(refreshInterval(BOOK_PROCESSING)).toBeGreaterThan(0);
        expect(refreshInterval(BOOK_READY)).toBe(0);
    });
});
