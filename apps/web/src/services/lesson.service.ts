import { lessonApi } from '../mocks/api';

// [DEV1-SPRINT2-PENDING] This depends on the real LessonPackage from Dev 1's
// package_builder (Story S2-11, not yet built). Do not build a parallel
// real-content path here -- this will be reconciled when Sprint 2 lands.
// Ping Dev 1 (developer1-cybersmith) before changing this shape.
export const lessonService = {
    getLesson: (id: string) => lessonApi.getLessonById(id),
    getLessonPackage: (id: string) => lessonApi.getLessonPackageById(id),
    updateProgress: (id: string, percent: number) => lessonApi.updateLessonProgress(id, percent),
};
