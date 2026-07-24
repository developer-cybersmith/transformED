import { api } from '@/lib/api';
import type { LessonPackage } from '@hie/shared/types/lesson';

export interface LessonUploadResponse {
    lesson_id: string;
    job_id: string;
    status: string;
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
// compile time instead of only as a runtime 422 (review fix).
export type BackendTier = 'T1' | 'T2' | 'T3';

export const uploadService = {
    uploadLesson: (file: File, tier?: BackendTier) => {
        const formData = new FormData();
        formData.append('file', file);
        // Omitted entirely when unset — the backend's own Form(DEFAULT_TIER, ...)
        // default applies server-side (apps/api/app/modules/content/router.py).
        // Definedness check, not truthiness — a defined-but-falsy value should
        // still be sent (and fail loudly as a 422) rather than being silently
        // treated as "not provided" (review fix).
        if (tier !== undefined) formData.append('tier', tier);
        // No explicit Content-Type here — axios/the browser must generate the
        // multipart boundary themselves; forcing the header strips it and the
        // backend fails to parse the body.
        return api.post<LessonUploadResponse>('content/lessons', formData).then((r) => r.data);
    },

    getLessonStatus: (lessonId: string) =>
        api.get<LessonStatusResponse>(`content/lessons/${lessonId}`).then((r) => r.data),
};

/**
 * FastAPI's automatic 422 validation errors return `detail` as an array of
 * `{msg, loc, type}` objects rather than a string. Normalize either shape to
 * a displayable message.
 */
export function extractErrorMessage(err: unknown, fallback: string): string {
    const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail.length > 0) {
        const first = detail[0] as { msg?: unknown } | undefined;
        if (first && typeof first.msg === 'string') return first.msg;
    }
    return fallback;
}
