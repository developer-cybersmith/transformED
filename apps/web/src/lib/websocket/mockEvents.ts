import type {
  GenerationProgressMessage,
  LessonReadyMessage,
  ErrorMessage,
} from '@hie/shared/types/ws';
import type { LessonPackage } from '@hie/shared/types/lesson';

export const createGenerationProgressMessage = (
  lessonId: string,
  node: string,
  progress: number,
  message: string,
): GenerationProgressMessage => ({
  type: 'generation_progress',
  payload: { lesson_id: lessonId, node, progress, message },
});

export const createLessonReadyMessage = (lessonId: string): LessonReadyMessage => ({
  type: 'lesson_ready',
  payload: {
    lesson_id: lessonId,
    // Sprint 0 mock: real LessonPackage delivered by the pipeline in Sprint 1+.
    // Nothing downstream reads payload.lesson today (only lesson_id is used
    // to redirect) — cast rather than fabricate a fake LessonPackage shape.
    lesson: null as unknown as LessonPackage,
  },
});

export const createErrorMessage = (code: string, message: string): ErrorMessage => ({
  type: 'error',
  payload: { code, message },
});
