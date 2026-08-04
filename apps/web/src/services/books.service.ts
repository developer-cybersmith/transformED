import { api } from '@/lib/api';

// Types hand-written from docs/contracts/book-api.v1.json v1.1.0, matching the
// repo convention of declaring response shapes next to the service that fetches
// them (see library.service.ts / upload.service.ts).

/** Ingestion status of an uploaded book. */
export type BookStatus = 'processing' | 'ready' | 'failed';

export interface BookResponse {
    book_id: string;
    filename: string;
    status: BookStatus;
    /** null while ingesting -- the page count isn't known until the PDF is parsed. */
    page_count: number | null;
    /** 0 while ingesting, never null (PostgREST embedded aggregate). */
    chapter_count: number;
    created_at: string | null;
}

/**
 * The CLIENT vocabulary for a lesson's state -- `queued | running | ready | failed`,
 * mapped server-side from the DB's `generating | ready | failed`. Only `ready`
 * corresponds to a lesson the player can actually open.
 */
export type LatestLessonStatus = 'queued' | 'running' | 'ready' | 'failed';

export type LessonTier = 'T1' | 'T2' | 'T3';

/** Added in contract 1.1.0. The newest lesson for a chapter, by created_at. */
export interface LatestLesson {
    lesson_id: string;
    status: LatestLessonStatus;
    tier: LessonTier;
    created_at: string | null;
}

/**
 * How the chapter boundary was DETECTED -- not a quality score, and never to be
 * rendered as one. `fallback` alone is meaningful to a student: it means
 * detection found no structure at all.
 */
export type BoundaryConfidence = 'toc' | 'contents' | 'heading' | 'font' | 'fallback';

export interface ChapterResponse {
    chapter_id: string;
    /** 0-based, sequential, gap-free over kept chapters. */
    chapter_index: number;
    title: string;
    /** 0-based PDF page INDEX, inclusive -- not a printed page number. */
    page_start: number;
    /** 0-based PDF page INDEX, inclusive -- not a printed page number. */
    page_end: number;
    boundary_confidence: BoundaryConfidence;
    /**
     * The MOST RECENT lesson generated from this chapter, by created_at.
     * Derived from the embedded `lessons` relation, not the dead
     * `chapters.lesson_id` column (DEFECT-REGISTER D44). null is normal.
     */
    lesson_id: string | null;
    /**
     * true when AT LEAST ONE lesson exists for this chapter in ANY state,
     * including 'failed'. Never gate a Watch button on this alone -- see
     * `watchableLessonId` below.
     */
    has_lesson: boolean;
    /** Added in 1.1.0. Lessons across all tiers and all states. 0, never null. */
    lesson_count: number;
    /** Added in 1.1.0. null exactly when lesson_count is 0. */
    latest_lesson: LatestLesson | null;
}

/**
 * The single most important rule in this screen: a Watch button is earned by
 * `latest_lesson.status === 'ready'`, NEVER by `has_lesson`.
 *
 * A chapter whose only lesson FAILED still has `has_lesson: true` and a
 * non-null `lesson_id`; linking to it produces a button that 404s the player.
 * Returns the lesson id that is safe to open, or null.
 */
export function watchableLessonId(chapter: Pick<ChapterResponse, 'latest_lesson'>): string | null {
    const latest = chapter.latest_lesson;
    return latest != null && latest.status === 'ready' ? latest.lesson_id : null;
}

/**
 * True when the book/chapter fetch failed with the contract's 404
 * ("Book not found"). The body is deliberately IDENTICAL for absent,
 * malformed-uuid and another user's book, so there is nothing else to read.
 * Typed structurally rather than via axios.isAxiosError so this stays honest
 * about what it actually inspects.
 */
export function isNotFoundError(error: unknown): boolean {
    return (
        typeof error === 'object' &&
        error !== null &&
        (error as { response?: { status?: number } }).response?.status === 404
    );
}

// Relative paths, no leading slash: lib/api.ts's baseURL already ends in /api.
export const booksService = {
    listBooks: async (limit = 50): Promise<BookResponse[]> => {
        const { data } = await api.get<BookResponse[]>('content/books', { params: { limit } });
        return data;
    },

    getBook: async (bookId: string): Promise<BookResponse> => {
        const { data } = await api.get<BookResponse>(`content/books/${bookId}`);
        return data;
    },

    listChapters: async (bookId: string): Promise<ChapterResponse[]> => {
        const { data } = await api.get<ChapterResponse[]>(`content/books/${bookId}/chapters`);
        return data;
    },
};
