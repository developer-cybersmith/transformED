/**
 * Fixtures for the book-scale API, derived from the frozen contract's
 * `real_example` block — captured 2026-08-04 from the real 1,151-page
 * "Dive into Deep Learning" run against a real Supabase project and a real API.
 *
 * Nothing here is invented. Every value is either read straight out of
 * `docs/contracts/book-api.v1.json` or computed from it by the same rule the
 * backend uses (page span, truncation threshold). The two exceptions are called
 * out inline and both are *derived* from real data rather than made up:
 *   - `TOO_LARGE_CHAPTER`, the rung-5 whole-document chapter, uses the real
 *     book's real page count (1,151) with the contract's documented
 *     `boundary_confidence: "fallback"`.
 *   - `UNKNOWN_BOOK_ID` / `UNKNOWN_CHAPTER_ID`, which must by definition not
 *     exist in the capture.
 */
import { assertExampleMatchesSchema, contract, MAX_PAGE_SPAN, TRUNCATION_WARN_PAGES } from './contract';

export interface ContractBook {
    book_id: string;
    filename: string;
    status: string;
    page_count: number | null;
    chapter_count: number;
    created_at: string | null;
}

export interface ContractLatestLesson {
    lesson_id: string;
    status: string;
    tier: string;
    created_at: string | null;
}

export interface ContractChapter {
    chapter_id: string;
    chapter_index: number;
    title: string;
    page_start: number;
    page_end: number;
    boundary_confidence: string;
    lesson_id: string | null;
    has_lesson: boolean;
    lesson_count: number;
    latest_lesson: ContractLatestLesson | null;
}

const example = contract.real_example as unknown as {
    'GET /books': ContractBook[];
    'GET /books/{book_id}': ContractBook;
    'GET /books/{book_id}/chapters': ContractChapter[];
};

// ── Provenance guard (AC4's mutation-check mechanism) ────────────────────────
// Runs at module import, i.e. before any test body. A field renamed in either
// `real_example` or `schemas` throws here and reddens every test that imports
// the harness.
example['GET /books'].forEach((b, i) =>
    assertExampleMatchesSchema('BookResponse', b, `real_example["GET /books"][${i}]`)
);
assertExampleMatchesSchema(
    'BookResponse',
    example['GET /books/{book_id}'],
    'real_example["GET /books/{book_id}"]'
);
example['GET /books/{book_id}/chapters'].forEach((c, i) => {
    assertExampleMatchesSchema('ChapterResponse', c, `real_example["GET /books/{book_id}/chapters"][${i}]`);
    if (c.latest_lesson !== null) {
        assertExampleMatchesSchema(
            'LatestLesson',
            c.latest_lesson,
            `real_example["GET /books/{book_id}/chapters"][${i}].latest_lesson`
        );
    }
});

export const BOOKS: ContractBook[] = example['GET /books'];
export const READY_BOOK: ContractBook = example['GET /books/{book_id}'];
export const PROCESSING_BOOK: ContractBook = (() => {
    const b = BOOKS.find((x) => x.status === 'processing');
    if (!b) throw new Error('real_example["GET /books"] no longer contains a book in "processing"');
    return b;
})();
export const CHAPTERS: ContractChapter[] = example['GET /books/{book_id}/chapters'];

/** Chapter 0 — 29 pages, below the 40-page truncation threshold, has lessons. */
export const SMALL_CHAPTER: ContractChapter = CHAPTERS[0];
/** Chapter 1 — 52 pages, above the truncation threshold, still under the 200-page gate. */
export const TRUNCATING_CHAPTER: ContractChapter = CHAPTERS[1];
/** Chapter 2 — the normal zero-lesson state: lesson_id null, has_lesson false. */
export const UNLESSONED_CHAPTER: ContractChapter = CHAPTERS[2];

/**
 * The rung-5 failure the 200-page gate exists to refuse: detection found no
 * signal and made the whole 1,151-page document one chapter. Page count and
 * book are real; `boundary_confidence: "fallback"` is the contract's own
 * enumeration for exactly this case.
 */
export const TOO_LARGE_CHAPTER: ContractChapter = {
    chapter_id: '00000000-0000-4000-8000-00000000fa11',
    chapter_index: 0,
    title: 'Dive into Deep Learning',
    page_start: 0,
    page_end: (READY_BOOK.page_count as number) - 1,
    boundary_confidence: 'fallback',
    lesson_id: null,
    has_lesson: false,
    lesson_count: 0,
    latest_lesson: null,
};

/** A chapter whose owning user already has 3 lessons generating → 429 + Retry-After. */
export const RATE_LIMITED_CHAPTER: ContractChapter = {
    ...UNLESSONED_CHAPTER,
    chapter_id: '00000000-0000-4000-8000-000000000429',
};

export const ALL_CHAPTERS: ContractChapter[] = [
    ...CHAPTERS,
    TOO_LARGE_CHAPTER,
    RATE_LIMITED_CHAPTER,
];

/** Must not exist in the capture — the 404 paths need an id the server has never seen. */
export const UNKNOWN_BOOK_ID = '00000000-0000-4000-8000-0000000000404';
export const UNKNOWN_CHAPTER_ID = '00000000-0000-4000-8000-0000000004040';

export const VALID_TIERS = ['T1', 'T2', 'T3'] as const;
export const DEFAULT_TIER = 'T2';

export function pageSpan(chapter: ContractChapter): number {
    return chapter.page_end - chapter.page_start + 1;
}

export function isTooLarge(chapter: ContractChapter): boolean {
    return pageSpan(chapter) > MAX_PAGE_SPAN;
}

export function truncationExpected(chapter: ContractChapter): boolean {
    return pageSpan(chapter) > TRUNCATION_WARN_PAGES;
}

/**
 * Verbatim from `apps/api/app/modules/content/router.py::upload_lesson`. A book
 * has no tier; supplying one on upload is a 422, which is how 100 % of uploads
 * failed while the frontend suite stayed green.
 */
export const TIER_ON_UPLOAD_DETAIL =
    'tier is no longer accepted on upload — a book has no tier. Choose it per chapter ' +
    'when generating a lesson (POST /books/{book_id}/chapters/{chapter_id}/lessons).';

export const BOOK_NOT_FOUND_DETAIL = 'Book not found';
export const CHAPTER_NOT_FOUND_DETAIL = 'Chapter not found';
export const BOOK_NOT_READY_DETAIL =
    'Book is not ready — chapter detection has not finished';
export const CONCURRENCY_CAP_DETAIL =
    'Too many lessons are already generating — wait for one to finish before starting another';
