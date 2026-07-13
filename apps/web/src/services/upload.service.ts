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
        return api
            .post<LessonUploadResponse>('content/lessons', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            })
            .then((r) => r.data);
    },

    getLessonStatus: (lessonId: string) =>
        api.get<LessonStatusResponse>(`content/lessons/${lessonId}`).then((r) => r.data),
};
