import { lessonApi } from '../mocks/api';
import { api } from '@/lib/api';
import type { LessonStatusResponse } from './upload.service';

// getLesson (dashboard-card shape) and updateProgress (progress tracking) have
// no real backend endpoint yet -- stay on mocks until their own future stories.
export const lessonService = {
    getLesson: (id: string) => lessonApi.getLessonById(id),
    getLessonPackage: (id: string) =>
        api.get<LessonStatusResponse>(`content/lessons/${id}`),
    updateProgress: (id: string, percent: number) => lessonApi.updateLessonProgress(id, percent),
};
