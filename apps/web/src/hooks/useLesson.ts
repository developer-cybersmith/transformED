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
  );

  return {
    lesson: data ?? null,
    isLoading,
    error,
  };
}
