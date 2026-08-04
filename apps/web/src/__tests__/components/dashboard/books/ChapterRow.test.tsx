import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ChapterRow } from '@/components/dashboard/books/ChapterRow';
import {
    BOOK_READY,
    CHAPTER_LATEST_FAILED,
    CHAPTER_LESSON_COUNT_2,
    CHAPTER_LESSON_READY,
    CHAPTER_NO_LESSON,
    CHAPTER_FALLBACK_BOUNDARY,
} from '../../../fixtures/books.fixtures';

function renderRow(chapter: Parameters<typeof ChapterRow>[0]['chapter']) {
    return render(
        <ul>
            <ChapterRow chapter={chapter} bookId={BOOK_READY.book_id} />
        </ul>,
    );
}

describe('ChapterRow — AC3, the Watch gate', () => {
    it('renders NO Watch link for a chapter whose only lesson failed, despite has_lesson: true', () => {
        renderRow(CHAPTER_LATEST_FAILED);

        expect(CHAPTER_LATEST_FAILED.has_lesson).toBe(true);
        expect(screen.queryByRole('link', { name: /watch/i })).toBeNull();
    });

    it('renders no Watch link while the latest lesson is still running', () => {
        renderRow(CHAPTER_LESSON_COUNT_2);

        expect(screen.queryByRole('link', { name: /watch/i })).toBeNull();
        expect(screen.getByText(/generating/i)).not.toBeNull();
    });

    it('renders a Watch link to the latest lesson only when its status is ready', () => {
        renderRow(CHAPTER_LESSON_READY);

        const link = screen.getByRole('link', { name: /watch/i });
        expect(link.getAttribute('href')).toBe('/lesson/6cbbe233-415f-4523-9541-0bde06d4c567');
    });

    it('renders no Watch link for a chapter with no lessons at all', () => {
        renderRow(CHAPTER_NO_LESSON);

        expect(screen.queryByRole('link', { name: /watch/i })).toBeNull();
    });
});

/**
 * W2 asserted these two buttons were DISABLED with a "next release" reason,
 * because nothing behind them existed (W2 AC10: never enabled-and-inert). W3 IS
 * that next release — `POST .../chapters/{id}/lessons` is now wired — so the
 * same two cases are re-pointed at the live behaviour rather than deleted. The
 * invariant W2 was protecting ("a CTA is never enabled unless it does something")
 * is unchanged; only which side of it is true has changed.
 */
describe('ChapterRow — AC10, no dead-end CTAs (W3: the CTA is now live)', () => {
    it('offers an ENABLED Generate button for a chapter with no lessons', () => {
        renderRow(CHAPTER_NO_LESSON);

        const button = screen.getByRole('button', { name: /generate/i });
        expect((button as HTMLButtonElement).disabled).toBe(false);
        // The W2 placeholder reason is gone, not left behind on a live control.
        expect(button.getAttribute('title')).toBeNull();
    });

    it('offers Retry — enabled — when the latest lesson failed', () => {
        renderRow(CHAPTER_LATEST_FAILED);

        const button = screen.getByRole('button', { name: /retry/i });
        expect((button as HTMLButtonElement).disabled).toBe(false);
    });

    it('offers no Generate control at all while a lesson is already generating', () => {
        renderRow(CHAPTER_LESSON_COUNT_2);

        expect(screen.queryByRole('button', { name: /generate/i })).toBeNull();
        expect(screen.getByText(/generating/i)).not.toBeNull();
    });
});

describe('ChapterRow — lesson_count and page ranges', () => {
    it('shows lesson_count > 1 — one chapter legitimately carries lessons at several tiers', () => {
        renderRow(CHAPTER_LESSON_COUNT_2);

        expect(screen.getByText('2 lessons')).not.toBeNull();
    });

    it('shows the real captured lesson_count of 3', () => {
        renderRow(CHAPTER_LATEST_FAILED);

        expect(screen.getByText('3 lessons')).not.toBeNull();
    });

    it('shows no lesson-count badge when the chapter has none', () => {
        renderRow(CHAPTER_NO_LESSON);

        expect(screen.queryByText(/lessons?$/)).toBeNull();
    });

    it('labels the page range as 0-based PDF indices, never as a bare printed page number', () => {
        renderRow(CHAPTER_LESSON_COUNT_2);

        const range = screen.getByText(/69/);
        expect(range.textContent).toContain('120');
        expect(range.textContent).toMatch(/0-based/i);
        expect(range.getAttribute('title')).toMatch(/not the page numbers printed/i);
    });
});

describe('ChapterRow — boundary_confidence is a detection method, not a quality score', () => {
    it('does not render "toc" as a score or confidence rating', () => {
        renderRow(CHAPTER_LESSON_COUNT_2);

        expect(screen.queryByText(/toc/i)).toBeNull();
        expect(screen.queryByText(/confidence/i)).toBeNull();
    });

    it('quietly surfaces only the fallback case, which means no structure was detected', () => {
        renderRow(CHAPTER_FALLBACK_BOUNDARY);

        expect(screen.getByText(/no chapter structure was detected/i)).not.toBeNull();
        expect(screen.queryByText(/fallback confidence/i)).toBeNull();
    });
});
