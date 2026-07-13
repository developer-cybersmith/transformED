import { api } from '@/lib/api';

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
}

export const MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024;

export const uploadService = {
    uploadLesson: (file: File) => {
        const formData = new FormData();
        formData.append('file', file);
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
