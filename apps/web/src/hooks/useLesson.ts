'use client';

import useSWR from 'swr';
import { lessonService } from '@/services/lesson.service';
import type { LessonStatus, LessonStatusResponse } from '@/services/upload.service';
import type { LessonPackage } from '@hie/shared/types/lesson';

interface UseLessonResult {
  lesson: LessonPackage | null;
  isLoading: boolean;
  // SWR-level fetch failure (network error, 404, unowned lesson) -- distinct
  // from serverError below, which is a successfully-fetched "failed" status.
  error: unknown;
  status: LessonStatus | undefined;
  serverError: string | null;
}

// A "still in progress" wire status polls until it reaches a terminal one
// (ready/failed) -- matches upload.service.ts's/UploadFlow.tsx's existing
// !== 'queued' && !== 'running' convention (the DB column value is
// "generating", but content/router.py's _map_status() translates that to the
// wire value "running" -- there is no "generating" on the wire).
// Matches UploadFlow.tsx's existing, already-shipped real polling-interval
// convention exactly (review fix) -- was 3000ms, an inconsistent one-off.
const POLL_INTERVAL_MS = 5000;

function refreshIntervalFor(data: LessonStatusResponse | null | undefined): number {
  if (!data) return 0;
  return data.status === 'queued' || data.status === 'running' ? POLL_INTERVAL_MS : 0;
}

export function useLesson(lessonId: string): UseLessonResult {
  const { data, error, isLoading } = useSWR<LessonStatusResponse | null>(
    lessonId ? `lesson:${lessonId}` : null,
    async () => {
      const response = await lessonService.getLessonPackage(lessonId);
      return response.data;
    },
    {
      // Refocusing the browser tab must NOT refetch mid-lesson: the player treats
      // any new object reference from this hook as a new lesson and resets its
      // entire state machine (segment index, audio position, quizFiredForSegment).
      revalidateOnFocus: false,
      refreshInterval: refreshIntervalFor,
    },
  );

  return {
    lesson: data?.content ?? null,
    isLoading,
    error,
    status: data?.status,
    serverError: data?.error ?? null,
  };
}
