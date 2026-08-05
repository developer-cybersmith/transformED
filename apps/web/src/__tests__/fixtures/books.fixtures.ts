/**
 * W2's view of W0's contract fixtures.
 *
 * Everything here is DERIVED from `@/test/fixtures`, which reads
 * `docs/contracts/book-api.v1.json`'s `real_example` block directly and asserts
 * it still matches the frozen schema at import time. Nothing is re-typed by
 * hand: if the capture changes, this file changes with it (and W0's provenance
 * guard reddens first).
 *
 * The only job this file does is narrow W0's deliberately-loose `Contract*`
 * types (all `string`) to the service's own unions, so the components under
 * test receive exactly the shape they declare.
 */
import {
    BOOKS as CONTRACT_BOOKS,
    CHAPTERS as CONTRACT_CHAPTERS,
    PROCESSING_BOOK as CONTRACT_PROCESSING_BOOK,
    RATE_LIMITED_CHAPTER as CONTRACT_RATE_LIMITED_CHAPTER,
    READY_BOOK as CONTRACT_READY_BOOK,
    TOO_LARGE_CHAPTER as CONTRACT_TOO_LARGE_CHAPTER,
} from '@/test/fixtures';
import type { BookResponse, ChapterResponse } from '@/services/books.service';

const asBook = (b: (typeof CONTRACT_BOOKS)[number]): BookResponse => b as BookResponse;
const asChapter = (c: (typeof CONTRACT_CHAPTERS)[number]): ChapterResponse => c as ChapterResponse;

/** d2l.pdf, still ingesting: page_count null, chapter_count 0. */
export const BOOK_PROCESSING: BookResponse = asBook(CONTRACT_PROCESSING_BOOK);
/** d2l.pdf, 1,151 pages, 21 detected chapters. */
export const BOOK_READY: BookResponse = asBook(CONTRACT_READY_BOOK);
export const BOOKS: BookResponse[] = CONTRACT_BOOKS.map(asBook);

export const CHAPTERS_CAPTURED: ChapterResponse[] = CONTRACT_CHAPTERS.map(asChapter);

/**
 * Chapter 0, "Introduction", pages [40..68]: lesson_count 3 and a latest lesson
 * that FAILED. has_lesson is true — the exact trap AC3 exists to defuse.
 */
export const CHAPTER_LATEST_FAILED: ChapterResponse = CHAPTERS_CAPTURED[0];
/** Chapter 1, "Preliminaries", pages [69..120]: TWO lessons on one chapter. */
export const CHAPTER_LESSON_COUNT_2: ChapterResponse = CHAPTERS_CAPTURED[1];
/** Chapter 2: the NORMAL zero-lesson state — lesson_id null, has_lesson false. */
export const CHAPTER_NO_LESSON: ChapterResponse = CHAPTERS_CAPTURED[2];

/** The one case that earns a Watch button: latest_lesson.status === 'ready'. */
export const CHAPTER_LESSON_READY: ChapterResponse = {
    ...CHAPTER_LESSON_COUNT_2,
    latest_lesson: { ...CHAPTER_LESSON_COUNT_2.latest_lesson!, status: 'ready' },
};

/** Detection found no structure at all — the only boundary_confidence worth surfacing. */
export const CHAPTER_FALLBACK_BOUNDARY: ChapterResponse = {
    ...CHAPTER_NO_LESSON,
    boundary_confidence: 'fallback',
};

/**
 * The real book has 21 chapters; the contract captured the first three verbatim
 * and those three are used as-is above. The remaining 18 are extrapolated from
 * the captured shape (contiguous 0-based page indices continuing past 163) so
 * the "a book with 21 chapters renders 21 rows" assertion has 21 rows to count.
 */
export const CHAPTERS_21: ChapterResponse[] = [
    ...CHAPTERS_CAPTURED,
    ...Array.from({ length: BOOK_READY.chapter_count - CHAPTERS_CAPTURED.length }, (_, i) => {
        const index = CHAPTERS_CAPTURED.length + i;
        const pageStart = CHAPTERS_CAPTURED[CHAPTERS_CAPTURED.length - 1].page_end + 1 + i * 50;
        return {
            chapter_id: `chapter-${index}`,
            chapter_index: index,
            title: `Chapter ${index}`,
            page_start: pageStart,
            page_end: pageStart + 49,
            boundary_confidence: 'toc',
            lesson_id: null,
            has_lesson: false,
            lesson_count: 0,
            latest_lesson: null,
        } satisfies ChapterResponse;
    }),
];

// ── W3 additions: the generate-path chapters, still derived from W0 ──────────

/**
 * The rung-5 chapter the 200-page gate exists to refuse: detection found no
 * signal and made the whole 1,151-page book one chapter. Drives the OBJECT-shaped
 * `chapter_too_large` 422.
 */
export const CHAPTER_TOO_LARGE: ChapterResponse = asChapter(CONTRACT_TOO_LARGE_CHAPTER);

/** A chapter whose owner already has 3 lessons generating → 429 + Retry-After. */
export const CHAPTER_RATE_LIMITED: ChapterResponse = asChapter(CONTRACT_RATE_LIMITED_CHAPTER);

/**
 * Chapter 2 spans pages [121..163] = 43 pages, over the ~40-page LLM-visible
 * window, so the server returns `truncation_expected: true` — and it has no
 * lessons, so the Generate control is the thing the card renders for it.
 */
export const CHAPTER_TRUNCATING: ChapterResponse = CHAPTER_NO_LESSON;
/** Chapter 0, pages [40..68] = 29 pages: below the truncation threshold. */
export const CHAPTER_NO_TRUNCATION: ChapterResponse = CHAPTER_LATEST_FAILED;

/** Shaped like the axios rejection for the contract's identical-body 404. */
export function bookNotFoundError(): unknown {
    return { response: { status: 404, data: { detail: 'Book not found' } } };
}
