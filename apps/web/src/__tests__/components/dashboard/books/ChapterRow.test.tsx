import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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

/**
 * Story 2-47 (S4-06): folding My Library's one unique capability (reaching a
 * non-latest lesson) into Books. `lessons` carries every lesson for the
 * chapter, newest-first; `latest_lesson` is always `lessons[0]`.
 */
describe('ChapterRow — AC-6, expandable non-latest lessons (Story 2-47)', () => {
    it('renders no "other lessons" affordance for a chapter with zero lessons (no regression)', () => {
        renderRow(CHAPTER_NO_LESSON);
        expect(screen.queryByRole('button', { name: /other lesson/i })).toBeNull();
    });

    it('renders no "other lessons" affordance when there is exactly one lesson', () => {
        const oneLesson = {
            ...CHAPTER_LESSON_READY,
            lesson_count: 1,
            lessons: [CHAPTER_LESSON_READY.lessons[0]],
        };
        renderRow(oneLesson);
        expect(screen.queryByRole('button', { name: /other lesson/i })).toBeNull();
    });

    it('shows an "N other lessons" affordance when the chapter has more than one', () => {
        renderRow(CHAPTER_LESSON_COUNT_2);
        // 2 total, 1 is the latest already shown at the top -> "1 other lesson".
        expect(screen.getByRole('button', { name: /1 other lesson/i })).not.toBeNull();
    });

    it('pluralizes correctly for more than one other lesson', () => {
        renderRow(CHAPTER_LATEST_FAILED);
        // 3 total, 1 is latest -> "2 other lessons".
        expect(screen.getByRole('button', { name: /2 other lessons/i })).not.toBeNull();
    });

    it('expanding reveals a working Watch link for a non-latest READY lesson, even though the latest one failed', async () => {
        const user = userEvent.setup();
        renderRow(CHAPTER_LATEST_FAILED);

        // Top-level Watch is absent -- the chapter's latest lesson failed.
        expect(screen.queryByRole('link', { name: /^watch$/i })).toBeNull();

        await user.click(screen.getByRole('button', { name: /2 other lessons/i }));

        // Both non-latest entries in the real capture are 'ready' (T2, T1).
        const links = screen.getAllByRole('link', { name: /watch/i });
        expect(links.length).toBe(2);
        expect(links.map((l) => l.getAttribute('href'))).toEqual([
            '/lesson/1a1a1a1a-1a1a-4a1a-8a1a-1a1a1a1a1a01',
            '/lesson/1a1a1a1a-1a1a-4a1a-8a1a-1a1a1a1a1a02',
        ]);
    });

    it('never renders a Watch link for a non-latest lesson that is not ready', async () => {
        // The gate applies PER-ENTRY, not just to the latest -- flip the one
        // real non-latest entry (normally 'ready') to prove it, matching
        // watchableLessonId's existing safety rule generalized to every row.
        const notReadyChapter = {
            ...CHAPTER_LESSON_COUNT_2,
            lessons: [
                CHAPTER_LESSON_COUNT_2.lessons[0],
                { ...CHAPTER_LESSON_COUNT_2.lessons[1], status: 'queued' as const },
            ],
        };
        const user = userEvent.setup();
        renderRow(notReadyChapter);

        await user.click(screen.getByRole('button', { name: /1 other lesson/i }));

        expect(screen.queryAllByRole('link', { name: /watch/i }).length).toBe(0);
    });

    it('surfaces the 20-entry cap explicitly rather than silently truncating (Scale & Load Q2)', async () => {
        // A REAL 20-item `lessons` array (the server's actual cap), with
        // `lesson_count` past it -- not a bare `lesson_count` override on a
        // 2-item array, which would let the review-fixed undercount bug pass
        // silently (see the dedicated undercount test below for that case).
        const twentyLessons = Array.from({ length: 20 }, (_, i) => ({
            ...CHAPTER_LESSON_COUNT_2.lessons[0],
            lesson_id: `lesson-${i}`,
        }));
        const cappedChapter = {
            ...CHAPTER_LESSON_COUNT_2,
            lesson_count: 23, // more lessons exist than the 20 the server ever exposes
            lessons: twentyLessons,
        };
        const user = userEvent.setup();
        renderRow(cappedChapter);

        await user.click(screen.getByRole('button', { name: /22 other lessons/i }));

        expect(screen.getByText(/3 more lessons not shown/i)).not.toBeNull();
        // All 19 rendered non-latest rows (20 lessons minus the latest) are
        // present, not silently dropped in favor of just the note.
        expect(screen.getAllByRole('listitem').length).toBeGreaterThanOrEqual(19);
    });

    it('does not show the cap note when lesson_count matches the exposed lessons exactly', async () => {
        const user = userEvent.setup();
        renderRow(CHAPTER_LESSON_COUNT_2);

        await user.click(screen.getByRole('button', { name: /1 other lesson/i }));

        expect(screen.queryByText(/more lesson.*not shown/i)).toBeNull();
    });

    it('review fix: the affordance label counts from the TRUE lesson_count, not the capped lessons array (previously undercounted)', () => {
        // Bug this test catches: deriving the button label from
        // `otherLessons.length` (max 19, since `lessons` is capped at 20)
        // instead of `lesson_count - 1` silently undercounts -- e.g. reading
        // "19 other lessons" when 22 actually exist. Reproduces with a small
        // `lessons` array and a `lesson_count` far past the cap, which is
        // exactly the shape a capped server response can produce.
        const chapter = {
            ...CHAPTER_LESSON_COUNT_2,
            lesson_count: 23,
            lessons: [CHAPTER_LESSON_COUNT_2.lessons[0]], // only 1 entry shipped
        };
        renderRow(chapter);

        expect(screen.getByRole('button', { name: /22 other lessons/i })).not.toBeNull();
        expect(screen.queryByRole('button', { name: /^0 other lessons$/i })).toBeNull();
    });
});
