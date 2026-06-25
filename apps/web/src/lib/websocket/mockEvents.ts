import type {
  GenerationProgressMessage,
  LessonReadyMessage,
  ErrorMessage,
} from '@hie/shared/types/ws';

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
    // Sprint 0 mock: real LessonPackage delivered by the pipeline in Sprint 1+
    lesson: null as any,
  },
});

export const createErrorMessage = (code: string, message: string): ErrorMessage => ({
  type: 'error',
  payload: { code, message },
});
