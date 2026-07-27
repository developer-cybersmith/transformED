import { api } from '@/lib/api';
import type { LessonStatusResponse } from './upload.service';

export interface LibraryData {
    ready: LessonStatusResponse[];
    processing: LessonStatusResponse[];
    failed: LessonStatusResponse[];
}

export const libraryService = {
    getLibrary: async (): Promise<LibraryData> => {
        const { data: lessons } = await api.get<LessonStatusResponse[]>('content/lessons', {
            params: { limit: 100 },
        });

        return {
            ready: lessons.filter((l) => l.status === 'ready'),
            // The real backend has no "queued" state distinct from "running"
            // in the UI's terms -- both are "still generating" to the student.
            processing: lessons.filter((l) => l.status === 'queued' || l.status === 'running'),
            failed: lessons.filter((l) => l.status === 'failed'),
        };
    },
};
