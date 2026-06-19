import { lessonApi } from '../mocks/api';

export const lessonService = {
    getLesson: (id: string) => lessonApi.getLessonById(id),
    updateProgress: (id: string, percent: number) => lessonApi.updateLessonProgress(id, percent),
};
