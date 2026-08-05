import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';

const { useSWRMock } = vi.hoisted(() => ({ useSWRMock: vi.fn() }));

vi.mock('swr', () => ({ default: useSWRMock }));

const { listChaptersMock, useAuthMock } = vi.hoisted(() => ({
    listChaptersMock: vi.fn(),
    useAuthMock: vi.fn(),
}));

vi.mock('@/services/books.service', () => ({
    booksService: { listChapters: listChaptersMock },
}));

vi.mock('@/contexts/AuthContext', () => ({ useAuth: useAuthMock }));

import { useChapters } from '@/hooks/useChapters';
import { BOOK_READY, CHAPTERS_CAPTURED } from '../fixtures/books.fixtures';

const BOOK_ID = BOOK_READY.book_id;

beforeEach(() => {
    useSWRMock.mockReset();
    listChaptersMock.mockReset();
    useAuthMock.mockReset();
    useAuthMock.mockReturnValue({ user: { id: 'user_1' } });
    useSWRMock.mockReturnValue({ data: undefined, error: undefined, isLoading: true });
});

describe('useChapters', () => {
    it('keys the SWR cache by user id AND book id', () => {
        renderHook(() => useChapters(BOOK_ID, 'ready'));

        expect(useSWRMock).toHaveBeenCalledWith(
            `chapters:user_1:${BOOK_ID}`,
            expect.any(Function),
            expect.anything(),
        );
    });

    it('uses a different key for a different user, so chapters cannot leak across accounts', () => {
        useAuthMock.mockReturnValue({ user: { id: 'user_2' } });

        renderHook(() => useChapters(BOOK_ID, 'ready'));

        expect(useSWRMock).toHaveBeenCalledWith(
            `chapters:user_2:${BOOK_ID}`,
            expect.any(Function),
            expect.anything(),
        );
    });

    it('does not fetch without an authenticated user', () => {
        useAuthMock.mockReturnValue({ user: null });

        renderHook(() => useChapters(BOOK_ID, 'ready'));

        expect(useSWRMock).toHaveBeenCalledWith(null, expect.any(Function), expect.anything());
    });

    it('returns the fetched chapters', () => {
        useSWRMock.mockReturnValue({ data: CHAPTERS_CAPTURED, error: undefined, isLoading: false });

        expect(renderHook(() => useChapters(BOOK_ID, 'ready')).result.current.data).toEqual(CHAPTERS_CAPTURED);
    });

    it("polls while the parent book is still 'processing' — chapter rows do not exist yet", () => {
        renderHook(() => useChapters(BOOK_ID, 'processing'));
        const refreshInterval = useSWRMock.mock.calls[0][2].refreshInterval;

        expect(refreshInterval([])).toBeGreaterThan(0);
    });

    it('does not poll once the book is ready', () => {
        renderHook(() => useChapters(BOOK_ID, 'ready'));
        const refreshInterval = useSWRMock.mock.calls[0][2].refreshInterval;

        expect(refreshInterval(CHAPTERS_CAPTURED)).toBe(0);
    });

    it('does not poll while the book status is still unknown', () => {
        renderHook(() => useChapters(BOOK_ID, undefined));
        const refreshInterval = useSWRMock.mock.calls[0][2].refreshInterval;

        expect(refreshInterval(undefined)).toBe(0);
    });
});

/**
 * Story W3 AC6 — after a generation response the chapter card must reflect the
 * SERVER, not a locally-invented status that can disagree with it.
 */
describe('useChapters — revalidate (W3 AC6)', () => {
    it('re-fetches the same SWR key rather than mutating anything locally', () => {
        const mutate = vi.fn();
        useSWRMock.mockReturnValue({
            data: CHAPTERS_CAPTURED,
            error: undefined,
            isLoading: false,
            mutate,
        });

        const { result } = renderHook(() => useChapters(BOOK_ID, 'ready'));
        result.current.revalidate();

        // No argument: a bare re-fetch. Passing data here would be the optimistic
        // local state AC6 exists to forbid.
        expect(mutate).toHaveBeenCalledTimes(1);
        expect(mutate).toHaveBeenCalledWith();
    });
});
