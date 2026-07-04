'use client';

import useSWR from 'swr';
import { lessonService } from '@/services/lesson.service';
import type { LessonPackage } from '@hie/shared/types/lesson';

interface UseLessonResult {
  lesson: LessonPackage | null;
  isLoading: boolean;
  error: unknown;
}

export function useLesson(lessonId: string): UseLessonResult {
  const { data, error, isLoading } = useSWR<LessonPackage | null>(
    lessonId ? `lesson:${lessonId}` : null,
    async () => {
      const response = await lessonService.getLessonPackage(lessonId);
      return response.data;
    },
    // Refocusing the browser tab must NOT refetch mid-lesson: the player treats
    // any new object reference from this hook as a new lesson and resets its
    // entire state machine (segment index, audio position, quizFiredForSegment).
    { revalidateOnFocus: false },
  );

  return {
    lesson: data ?? null,
    isLoading,
    error,
  };
}
