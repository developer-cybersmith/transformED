import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

const { useBookMock, useChaptersMock, bookContextFormMock } = vi.hoisted(() => ({
    useBookMock: vi.fn(),
    useChaptersMock: vi.fn(),
    bookContextFormMock: vi.fn(),
}));

vi.mock('@/hooks/useBooks', () => ({ useBook: useBookMock }));
vi.mock('@/hooks/useChapters', () => ({ useChapters: useChaptersMock }));
// S5-9: mock BookContextForm so we can assert mount/props without triggering
// its own getBookContext fetch. Default returns null (same as the real
// component's loading state) so existing tests are unaffected.
vi.mock('@/components/dashboard/books/BookContextForm', () => ({
    BookContextForm: bookContextFormMock,
}));

import { BookDetail } from '@/components/dashboard/books/BookDetail';
import {
    BOOK_READY,
    BOOK_PROCESSING,
    CHAPTERS_21,
    CHAPTERS_CAPTURED,
    bookNotFoundError,
} from '../../../fixtures/books.fixtures';

function ok<T>(data: T) {
    return { data, error: undefined, isLoading: false };
}

beforeEach(() => {
    useBookMock.mockReset();
    useChaptersMock.mockReset();
    // Reset call history AND set default return value so existing chapter/text
    // assertions are unaffected (same as real component's initial loading=true state).
    bookContextFormMock.mockReset();
    bookContextFormMock.mockReturnValue(null);
});

describe('BookDetail', () => {
    it('renders all 21 chapters of the real captured book, with the real page ranges', () => {
        useBookMock.mockReturnValue(ok(BOOK_READY));
        useChaptersMock.mockReturnValue(ok(CHAPTERS_21));

        render(<BookDetail bookId={BOOK_READY.book_id} />);

        expect(screen.getAllByRole('listitem')).toHaveLength(21);
        expect(screen.getByText(/PDF pages 69–120/)).not.toBeNull();
        expect(screen.getByText(/PDF pages 40–68/)).not.toBeNull();
        expect(screen.getByText('Preliminaries')).not.toBeNull();
    });

    it('shows the real filename, page count and chapter count', () => {
        useBookMock.mockReturnValue(ok(BOOK_READY));
        useChaptersMock.mockReturnValue(ok(CHAPTERS_CAPTURED));

        render(<BookDetail bookId={BOOK_READY.book_id} />);

        expect(screen.getByText('d2l.pdf')).not.toBeNull();
        expect(screen.getByText(/1151 pages · 21 chapters/)).not.toBeNull();
    });

    it('renders a not-found state rather than crashing when the API 404s', () => {
        useBookMock.mockReturnValue({ data: null, error: bookNotFoundError(), isLoading: false });
        useChaptersMock.mockReturnValue({ data: null, error: bookNotFoundError(), isLoading: false });

        render(<BookDetail bookId="does-not-exist" />);

        expect(screen.getByText(/couldn't find that book/i)).not.toBeNull();
        expect(screen.getByRole('link', { name: /back to your books/i })).not.toBeNull();
    });

    it("tells the student a still-'processing' book is mid-detection instead of showing an empty error", () => {
        useBookMock.mockReturnValue(ok(BOOK_PROCESSING));
        useChaptersMock.mockReturnValue(ok([]));

        render(<BookDetail bookId={BOOK_PROCESSING.book_id} />);

        expect(screen.getByText(/still detecting chapters/i)).not.toBeNull();
        expect(screen.queryByText(/no chapters were detected/i)).toBeNull();
    });

    it('passes the book status into useChapters so polling uses the BOOK vocabulary', () => {
        useBookMock.mockReturnValue(ok(BOOK_PROCESSING));
        useChaptersMock.mockReturnValue(ok([]));

        render(<BookDetail bookId={BOOK_PROCESSING.book_id} />);

        expect(useChaptersMock).toHaveBeenCalledWith(BOOK_PROCESSING.book_id, 'processing');
    });

    it('keeps showing the chapters it already has when a background poll fails', () => {
        useBookMock.mockReturnValue({ data: BOOK_READY, error: new Error('transient'), isLoading: false });
        useChaptersMock.mockReturnValue(ok(CHAPTERS_CAPTURED));

        render(<BookDetail bookId={BOOK_READY.book_id} />);

        expect(screen.getByText(/couldn't refresh this book/i)).not.toBeNull();
        expect(screen.getAllByRole('listitem')).toHaveLength(3);
    });

    it('shows a loading state while the first fetch is in flight', () => {
        useBookMock.mockReturnValue({ data: null, error: undefined, isLoading: true });
        useChaptersMock.mockReturnValue({ data: null, error: undefined, isLoading: true });

        render(<BookDetail bookId={BOOK_READY.book_id} />);

        expect(screen.getByText('Loading intelligence...')).not.toBeNull();
    });

    // ── S5-9: BookContextForm mount conditions ──────────────────────────────

    it('S5-9 AC2: mounts BookContextForm with isProcessing=true when book is processing', () => {
        useBookMock.mockReturnValue(ok(BOOK_PROCESSING));
        useChaptersMock.mockReturnValue(ok([]));

        render(<BookDetail bookId={BOOK_PROCESSING.book_id} />);

        expect(bookContextFormMock).toHaveBeenCalledWith(
            expect.objectContaining({ bookId: BOOK_PROCESSING.book_id, isProcessing: true }),
            undefined,
        );
    });

    it('S5-9 AC3/AC6: mounts BookContextForm with isProcessing=false when book is ready', () => {
        useBookMock.mockReturnValue(ok(BOOK_READY));
        useChaptersMock.mockReturnValue(ok(CHAPTERS_CAPTURED));

        render(<BookDetail bookId={BOOK_READY.book_id} />);

        expect(bookContextFormMock).toHaveBeenCalledWith(
            expect.objectContaining({ bookId: BOOK_READY.book_id, isProcessing: false }),
            undefined,
        );
    });

    it('S5-9 AC4: does NOT mount BookContextForm when book has failed', () => {
        const failedBook = { ...BOOK_READY, status: 'failed' as const };
        useBookMock.mockReturnValue(ok(failedBook));
        useChaptersMock.mockReturnValue(ok([]));

        render(<BookDetail bookId={failedBook.book_id} />);

        expect(bookContextFormMock).not.toHaveBeenCalled();
    });
});
