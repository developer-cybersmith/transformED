import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

const { useBooksMock } = vi.hoisted(() => ({ useBooksMock: vi.fn() }));

vi.mock('@/hooks/useBooks', () => ({ useBooks: useBooksMock }));

import BooksPage from '@/app/(dashboard)/books/page';
import { BOOKS, BOOK_READY } from '../../fixtures/books.fixtures';

beforeEach(() => {
    useBooksMock.mockReset();
});

describe('BooksPage', () => {
    it('renders the real captured books, each linking to its detail route', () => {
        useBooksMock.mockReturnValue({ data: BOOKS, error: undefined, isLoading: false });

        render(<BooksPage />);

        const links = screen.getAllByRole('link');
        expect(links.map((l) => l.getAttribute('href'))).toEqual([
            '/books/9c66fab7-817c-4b8e-bd59-d1ded445bf65',
            `/books/${BOOK_READY.book_id}`,
        ]);
        expect(screen.getByText('21 chapters')).not.toBeNull();
        expect(screen.getByText('1151 pages')).not.toBeNull();
    });

    it("shows a book that is still ingesting as 'detecting chapters', never as '0 chapters' or 'null pages'", () => {
        useBooksMock.mockReturnValue({ data: [BOOKS[0]], error: undefined, isLoading: false });

        render(<BooksPage />);

        expect(screen.getByText(/detecting chapters/i)).not.toBeNull();
        expect(screen.queryByText(/null/i)).toBeNull();
        expect(screen.queryByText('0 chapters')).toBeNull();
    });

    it('treats zero books as a first-run state with a route to /upload, not an error', () => {
        useBooksMock.mockReturnValue({ data: [], error: undefined, isLoading: false });

        render(<BooksPage />);

        expect(screen.getByText(/haven't uploaded a textbook yet/i)).not.toBeNull();
        expect(screen.getByRole('link', { name: /upload a book/i }).getAttribute('href')).toBe('/upload');
        expect(screen.queryByText(/couldn't load your books/i)).toBeNull();
    });

    it('shows a loading state while the fetch is in flight', () => {
        useBooksMock.mockReturnValue({ data: null, error: undefined, isLoading: true });

        render(<BooksPage />);

        expect(screen.getByText('Loading intelligence...')).not.toBeNull();
    });

    it('shows a fallback message instead of crashing when the fetch fails outright', () => {
        useBooksMock.mockReturnValue({ data: null, error: new Error('boom'), isLoading: false });

        render(<BooksPage />);

        expect(screen.getByText(/couldn't load your books right now/i)).not.toBeNull();
    });

    it('keeps the last known books alongside a warning banner when a background poll fails', () => {
        useBooksMock.mockReturnValue({ data: BOOKS, error: new Error('transient'), isLoading: false });

        render(<BooksPage />);

        expect(screen.getByText(/couldn't refresh your books/i)).not.toBeNull();
        expect(screen.getByText('21 chapters')).not.toBeNull();
        expect(screen.queryByText(/couldn't load your books right now/i)).toBeNull();
    });
});
