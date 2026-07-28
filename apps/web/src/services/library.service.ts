import { api } from '@/lib/api';
import type { LessonStatusResponse } from './upload.service';

export interface LibraryData {
    // The raw, unfiltered list -- "All Lessons" renders this directly rather
    // than reconstructing it by concatenating the buckets below, so a lesson
    // whose status doesn't match any known bucket can never silently vanish
    // from the "All" tab if the backend ever adds a new status value.
    all: LessonStatusResponse[];
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
            all: lessons,
            ready: lessons.filter((l) => l.status === 'ready'),
            // The real backend has no "queued" state distinct from "running"
            // in the UI's terms -- both are "still generating" to the student.
            processing: lessons.filter((l) => l.status === 'queued' || l.status === 'running'),
            failed: lessons.filter((l) => l.status === 'failed'),
        };
    },
};
