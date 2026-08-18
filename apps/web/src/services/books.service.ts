import { api } from '@/lib/api';
// W0 taught this the object-shaped `chapter_too_large` detail. There is exactly
// ONE parser for API error bodies in this app -- importing it is deliberate, and
// `upload.service.ts` is not otherwise touched by W3 (Story W3 dev note).
import { extractErrorMessage } from '@/services/upload.service';

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
    /**
     * Added in 1.3.0 (Story 2-47). EVERY lesson for this chapter (all tiers,
     * all states), newest-first. [] (never absent) when lesson_count is 0.
     * Capped at 20 entries server-side as a safety ceiling — lesson_count
     * keeps reporting the true total even past the cap, so `lesson_count >
     * lessons.length` is possible and means "more exist than shown", not an
     * inconsistency to paper over.
     */
    lessons: LatestLesson[];
}

/**
 * The single most important rule in this screen: a Watch button is earned by
 * `latest_lesson.status === 'ready'`, NEVER by `has_lesson`.
 *
 * A chapter whose only lesson FAILED still has `has_lesson: true` and a
 * non-null `lesson_id`; linking to it produces a button that 404s the player.
 * Returns the lesson id that is safe to open, or null.
 */
/**
 * Single source of truth for "is this lesson safe to link to" -- a lesson
 * that failed or is still generating must never earn a Watch link, whether
 * it is the chapter's `latest_lesson` or one of the non-latest entries in
 * `lessons` (Story 2-47 / S4-06). Extracted during that story's
 * `/bmad-code-review` after `ChapterRow.tsx` shipped a second, independent
 * copy of this exact rule -- if this gate is ever extended (e.g. an
 * entitlement check), a duplicate copy would silently keep the old, narrower
 * rule for every non-latest entry.
 */
export function isLessonWatchable(lesson: Pick<LatestLesson, 'status'> | null | undefined): boolean {
    return lesson != null && lesson.status === 'ready';
}

export function watchableLessonId(chapter: Pick<ChapterResponse, 'latest_lesson'>): string | null {
    const latest = chapter.latest_lesson;
    return latest != null && isLessonWatchable(latest) ? latest.lesson_id : null;
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

// ── Lesson generation (contract v1.1.0, POST .../chapters/{id}/lessons) ──────

/**
 * The body of POST content/books/{book_id}/chapters/{chapter_id}/lessons.
 *
 * `tier` is the ONLY field the client supplies: book_id and chapter_id come from
 * the path, and the page range / source PDF / owner are read from rows the caller
 * has already been proven to own. A client-supplied page range would bypass the
 * size gate outright, which is why one is not accepted and must not be added.
 *
 * This is a JSON body. S2-09 sent `FormData.append('tier', ...)` to
 * POST content/lessons; that endpoint now 422s on the mere presence of `tier`
 * ("a book has no tier"), which is the defect this whole phase removes.
 */
export interface GenerateLessonRequest {
    tier: LessonTier;
}

export interface LessonGenerationResponse {
    lesson_id: string;
    chapter_id: string;
    /** Echoed back, so the client never has to assume the server's default. */
    tier: LessonTier;
    /**
     * `'queued'` on the 202 create path. On the 200 idempotent path this is the
     * EXISTING lesson's own status (`'generating'` or `'ready'`) -- deliberately
     * not narrowed to a union here, because the two paths speak different
     * vocabularies and flattening them is how 200 gets mistaken for 202.
     */
    status: string;
    /** The ARQ job id on 202; ALWAYS null on the 200 idempotent path. */
    job_id: string | null;
    /**
     * true when the chapter spans more than ~40 pages, i.e. more than the
     * LLM-visible ~90,000-character window. A QUALITY warning, not a failure:
     * the request was accepted and will run (DEFECT-REGISTER D46).
     */
    truncation_expected: boolean;
}

/**
 * 202 and 200 are NOT the same event, and the shared body shape cannot tell them
 * apart on its own -- `status` is `'generating'` on the 200 path for a lesson
 * that really is generating, which reads exactly like success.
 *
 * `created` carries the HTTP status distinction the body loses:
 *   - `true`  (202) -- a lesson row was created and a job was enqueued.
 *   - `false` (200) -- an equivalent lesson already existed. Nothing was created,
 *                      nothing was enqueued, and `job_id` is null.
 */
export interface GenerateLessonResult {
    created: boolean;
    lesson: LessonGenerationResponse;
}

// ── Failure messages (AC4: every documented failure is distinct and honest) ──

/**
 * 404. The contract returns a byte-identical body for a book that does not
 * exist, a malformed uuid and another user's book -- and "Chapter not found" for
 * a chapter of a different book of the caller's own. Distinguishing them is
 * deliberately impossible from here, so the message does not try.
 */
export const GENERATE_NOT_FOUND_MESSAGE =
    "We couldn't find this chapter any more. Go back to your books and open it again.";

/** 409. The book exists and is yours; chapter detection just hasn't finished. */
export const GENERATE_BOOK_NOT_READY_MESSAGE =
    "We're still detecting chapters in this book, so there's nothing to build a lesson from yet. " +
    'It finishes on its own — try again in a minute.';

/**
 * 422 on `tier`. Unreachable through this UI, which only ever sends a value from
 * `LEARNER_TIER_TO_BACKEND`. Reaching it means a client bug, so it is logged.
 */
export const GENERATE_INVALID_TIER_MESSAGE =
    "Something went wrong on our side with the depth you picked, so we didn't start the lesson. " +
    'Please try again.';

/**
 * 429. TWO distinct causes share this status: the per-user concurrency cap
 * (3 lessons generating, carries `Retry-After`) and the rate limit (3/minute,
 * 20/hour). Both mean "wait", and this message deliberately does NOT guess which
 * one fired -- naming the wrong one is worse than naming neither.
 */
export const GENERATE_RATE_LIMITED_MESSAGE =
    "You've started several lessons in a short space of time, so this one wasn't started. " +
    'Wait a moment and try again.';

export const GENERATE_FALLBACK_MESSAGE =
    "We couldn't start this lesson. Please try again.";

function httpStatusOf(error: unknown): number | null {
    const status = (error as { response?: { status?: unknown } })?.response?.status;
    return typeof status === 'number' ? status : null;
}

/** `Retry-After` is seconds. Present on the concurrency-cap 429, absent otherwise. */
function retryAfterSeconds(error: unknown): number | null {
    const headers = (error as { response?: { headers?: unknown } })?.response?.headers;
    if (headers == null || typeof headers !== 'object') return null;
    const raw =
        (headers as Record<string, unknown>)['retry-after'] ??
        (headers as Record<string, unknown>)['Retry-After'];
    const seconds = Number(raw);
    return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

/**
 * Turns a rejected `generateLesson` into one displayable sentence.
 *
 * Everything that is NOT status-specific is delegated to `extractErrorMessage`,
 * the single parser for API `detail` bodies -- including the object-shaped
 * `chapter_too_large` 422, whose real `page_span`/`max_page_span` numbers are
 * the only information that explains the refusal. A second parser here would
 * drift from that one, so there isn't one.
 */
export function generateLessonErrorMessage(error: unknown): string {
    const status = httpStatusOf(error);

    if (status === 404) return GENERATE_NOT_FOUND_MESSAGE;
    if (status === 409) return GENERATE_BOOK_NOT_READY_MESSAGE;

    if (status === 429) {
        const seconds = retryAfterSeconds(error);
        // Stating the server's own wait hint is not the same as guessing the
        // cause -- it is only present on one of the two, but it is a fact either
        // way, so it is appended rather than used to pick a story.
        return seconds != null
            ? `${GENERATE_RATE_LIMITED_MESSAGE} You can try again in ${seconds} seconds.`
            : GENERATE_RATE_LIMITED_MESSAGE;
    }

    if (status === 422) {
        const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data
            ?.detail;
        // FastAPI's validation array === the tier was rejected during request
        // parsing, before any database call. The UI can only produce this by
        // sending something outside T1|T2|T3, which is a bug in this client.
        if (Array.isArray(detail)) {
            console.error(
                'POST .../chapters/{id}/lessons rejected the tier. The UI must only ever send ' +
                    'LEARNER_TIER_TO_BACKEND values (T1|T2|T3) — this is a client bug.',
                detail
            );
            return GENERATE_INVALID_TIER_MESSAGE;
        }
        // Everything else at 422 is the structured `chapter_too_large` object.
        return extractErrorMessage(error, GENERATE_FALLBACK_MESSAGE);
    }

    return extractErrorMessage(error, GENERATE_FALLBACK_MESSAGE);
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

    /**
     * Starts (or re-finds) a lesson for one chapter at one tier.
     *
     * Restores Sprint 2's S2-09 at its new home: the tier is supplied per
     * CHAPTER at generation time, as a JSON body, not per BOOK at upload time as
     * multipart. `axios` sets `application/json` for a plain object body itself.
     *
     * Never retries on its own. The endpoint is rate-limited 3/minute and
     * 20/hour per user with a 3-concurrent-generation cap, so an automatic retry
     * spends the student's budget and locks them out; every retry is a click.
     */
    generateLesson: async (
        bookId: string,
        chapterId: string,
        tier: LessonTier
    ): Promise<GenerateLessonResult> => {
        const body: GenerateLessonRequest = { tier };
        const response = await api.post<LessonGenerationResponse>(
            `content/books/${bookId}/chapters/${chapterId}/lessons`,
            body
        );
        // The ONLY place the 202/200 distinction is still visible. Read it here
        // or lose it: the two bodies are the same shape.
        return { created: response.status === 202, lesson: response.data };
    },
};
