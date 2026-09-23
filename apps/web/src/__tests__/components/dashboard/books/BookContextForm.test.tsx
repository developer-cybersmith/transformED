/**
 * Unit tests for BookContextForm.
 *
 * These tests render the REAL component (not mocked) so the subtitle text for
 * AC5 and AC6 (Story S5-9) is actually asserted. booksService.getBookContext
 * is mocked so no real API calls are made.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

// Mock booksService before importing the component so the useEffect fetch
// never fires a real HTTP call. getBookContext resolves to null (no saved
// context) — this mirrors the component's "first visit" loading path and
// ensures the form renders immediately without blocking on the promise.
vi.mock('@/services/books.service', () => ({
    booksService: {
        getBookContext: vi.fn().mockResolvedValue(null),
        upsertBookContext: vi.fn(),
    },
}));

import { BookContextForm } from '@/components/dashboard/books/BookContextForm';

beforeEach(() => {
    vi.clearAllMocks();
});

describe('BookContextForm', () => {
    it('S5-9 AC5: shows processing subtitle when isProcessing=true', async () => {
        render(<BookContextForm bookId="book-abc" isProcessing={true} />);

        // The component fetches on mount; wait for it to resolve (null → not dismissed → renders).
        // Use a partial text match to avoid apostrophe encoding issues (’ vs ').
        const subtitle = await screen.findByText(/While your book is being analysed/i);
        expect(subtitle).not.toBeNull();
        // Confirm the second half is also present in the same element.
        expect(subtitle.textContent).toMatch(/tell us how you.*ll use it/i);
    });

    it('S5-9 AC6: shows default subtitle when isProcessing=false (book is ready)', async () => {
        render(<BookContextForm bookId="book-def" isProcessing={false} />);

        const subtitle = await screen.findByText(
            /Optional.*helps personalise every lesson we generate from it/i,
        );
        expect(subtitle).not.toBeNull();
    });

    it('S5-9 AC6 default: shows default subtitle when isProcessing prop is omitted', async () => {
        render(<BookContextForm bookId="book-ghi" />);

        const subtitle = await screen.findByText(
            /Optional.*helps personalise every lesson we generate from it/i,
        );
        expect(subtitle).not.toBeNull();
    });

    it('S5-9 AC8: dismiss button hides the form in the current render session', async () => {
        const { container } = render(<BookContextForm bookId="book-jkl" />);

        // Form should be visible after the fetch resolves.
        await screen.findByText(/Optional.*helps personalise/i);
        expect(container.querySelector('h2')).not.toBeNull();

        const skipButton = screen.getByRole('button', { name: /skip book context form/i });
        fireEvent.click(skipButton);

        // After dismissal the form disappears from the DOM.
        expect(container.querySelector('h2')).toBeNull();
    });
});
