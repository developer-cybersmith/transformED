import { api } from '@/lib/api';
import type { LessonPackage } from '@hie/shared/types/lesson';

/**
 * POST content/lessons ingests a BOOK, not a lesson (book-scale Phase 3,
 * decision D-B / Story 1-10). There is no `lesson_id` to return any more —
 * lessons are generated per chapter afterwards, from the book detail page.
 * Shape frozen in `docs/contracts/book-api.v1.json` (BookUploadResponse).
 */
export interface BookUploadResponse {
    book_id: string;
    job_id: string;
    /** "queued" on the accept path — the ARQ enqueue status, not the book's own. */
    status: string;
}

/**
 * Book ingestion vocabulary. Deliberately NOT `LessonStatus` — a book never
 * reports `queued`/`running`, and a lesson never reports `processing`. Mixing
 * the two unions is the bug this story exists to fix, so they stay separate.
 */
export type BookStatus = 'processing' | 'ready' | 'failed';

/** GET content/books/{book_id} — see book-api.v1.json § schemas.BookResponse. */
export interface BookResponse {
    book_id: string;
    filename: string;
    status: BookStatus;
    /** null while ingesting — the page count is only known once the PDF is opened. */
    page_count: number | null;
    /** 0 while ingesting, never null. This is the honest progress signal. */
    chapter_count: number;
    created_at: string | null;
}

export type LessonStatus = 'queued' | 'running' | 'ready' | 'failed';

export interface LessonStatusResponse {
    lesson_id: string;
    status: LessonStatus;
    title: string | null;
    error: string | null;
    created_at: string | null;
    completed_at: string | null;
    // Populated by GET /lessons/{id} only when status=="ready" (Story 1-6);
    // always null for "queued"/"running"/"failed". Media URLs inside are
    // already server-resolved signed URLs -- never bare storage paths.
    content: LessonPackage | null;
}

export const MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024;

// Mirrors apps/api/app/schemas/lesson.py's LessonTier — declared locally
// (not imported from @/types/learnerMode) so this service stays agnostic of
// Learner Mode's frontend vocabulary; this is the backend's own closed
// contract, not that module's. Catches a typo'd/unmapped tier value at
// compile time instead of only as a runtime 422 (review fix). No longer used by
// upload — kept because tier moved to POST /books/{id}/chapters/{id}/lessons (W3).
export type BackendTier = 'T1' | 'T2' | 'T3';

export const uploadService = {
    /**
     * Uploads the book PDF. `tier` is NOT sent and must never be re-added: the
     * endpoint 422s on its mere presence ("a book has no tier"), which made
     * 100 % of uploads fail. The tier is chosen per chapter at generation time
     * (W3), not per book at upload time.
     */
    uploadLesson: (file: File) => {
        const formData = new FormData();
        formData.append('file', file);
        // No explicit Content-Type here — axios/the browser must generate the
        // multipart boundary themselves; forcing the header strips it and the
        // backend fails to parse the body.
        return api.post<BookUploadResponse>('content/lessons', formData).then((r) => r.data);
    },

    /** Ingestion progress. `status` walks processing → ready | failed. */
    getBookStatus: (bookId: string) =>
        api.get<BookResponse>(`content/books/${bookId}`).then((r) => r.data),

    /**
     * Retained for lesson generation polling (W3) — the upload flow no longer
     * calls it, because an upload no longer produces a lesson.
     */
    getLessonStatus: (lessonId: string) =>
        api.get<LessonStatusResponse>(`content/lessons/${lessonId}`).then((r) => r.data),
};

/**
 * A `detail` the API returns as a structured object rather than prose.
 * Currently only `chapter_too_large`, from
 * POST /books/{book_id}/chapters/{chapter_id}/lessons — see
 * `docs/contracts/book-api.v1.json` § endpoints ... responses.422.
 */
interface StructuredErrorDetail {
    code?: unknown;
    page_span?: unknown;
    max_page_span?: unknown;
    boundary_confidence?: unknown;
}

const n = (v: number) => v.toLocaleString('en-US');

/**
 * Renders the object-shaped `detail` bodies (Story W0 AC6).
 *
 * Returns `null` — not the fallback — when the object is not one this function
 * recognises, so the caller can keep walking the remaining shapes.
 */
function messageFromStructuredDetail(detail: StructuredErrorDetail): string | null {
    if (detail.code === 'chapter_too_large') {
        const span = detail.page_span;
        const max = detail.max_page_span;
        if (typeof span === 'number' && typeof max === 'number') {
            // `boundary_confidence: "fallback"` means chapter detection found no
            // signal at all and made the whole document one chapter. That is a
            // completely different user action ("this PDF has no detectable
            // chapters") from a genuinely enormous chapter, so it is worth the
            // extra sentence rather than being flattened into one message.
            const detectionFailed = detail.boundary_confidence === 'fallback';
            return detectionFailed
                ? `We couldn't find chapter boundaries in this book, so the whole ${n(span)}-page ` +
                  `document was treated as one chapter — well over the ${n(max)}-page limit for a ` +
                  `single lesson. Try a PDF with a table of contents.`
                : `This chapter is ${n(span)} pages, over the ${n(max)}-page limit for a single ` +
                  `lesson. Pick a shorter chapter.`;
        }
    }
    if (typeof detail.code === 'string') return detail.code;
    return null;
}

/**
 * Normalizes every `detail` shape the API can return into a displayable message:
 *  - a plain string (most `HTTPException`s);
 *  - FastAPI's automatic validation array of `{msg, loc, type}`;
 *  - an OBJECT, e.g. `chapter_too_large` (added Story W0 AC6). Before that branch
 *    existed both other checks missed and this returned the fallback, throwing
 *    away `page_span`/`max_page_span` — the only information telling the user
 *    why their chapter was refused.
 */
export function extractErrorMessage(err: unknown, fallback: string): string {
    const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail.length > 0) {
        const first = detail[0] as { msg?: unknown } | undefined;
        if (first && typeof first.msg === 'string') return first.msg;
    }
    if (detail !== null && typeof detail === 'object' && !Array.isArray(detail)) {
        const message = messageFromStructuredDetail(detail as StructuredErrorDetail);
        if (message !== null) return message;
    }
    return fallback;
}
