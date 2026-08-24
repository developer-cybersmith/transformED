'use client';

import { useRef } from 'react';
import useSWR from 'swr';
import { lessonService } from '@/services/lesson.service';
import type { LessonStatus, LessonStatusResponse } from '@/services/upload.service';
import type { LessonPackage } from '@hie/shared/types/lesson';
import { isLessonProcessing, nextPollInterval } from '@/lib/lessonStatusPoll';

interface UseLessonResult {
  lesson: LessonPackage | null;
  isLoading: boolean;
  // SWR-level fetch failure (network error, 404, unowned lesson) -- distinct
  // from serverError below, which is a successfully-fetched "failed" status.
  error: unknown;
  status: LessonStatus | undefined;
  serverError: string | null;
  /** Force a revalidation (e.g. to get freshly re-signed media URLs after a
   *  retry-triggered refetch, S2-33) and return the resolved response. */
  refetch: () => Promise<LessonStatusResponse | null | undefined>;
}

// A "still in progress" wire status polls until it reaches a terminal one
// (ready/failed) -- matches upload.service.ts's/UploadFlow.tsx's existing
// !== 'queued' && !== 'running' convention (the DB column value is
// "generating", but content/router.py's _map_status() translates that to the
// wire value "running" -- there is no "generating" on the wire).

export function useLesson(lessonId: string): UseLessonResult {
  // S4-11: was a standalone interval with no ceiling -- the one outlier among
  // this app's 5 other polling loops (UploadFlow, useChapters, useBooks x2,
  // useDashboard), all of which already use this same shared
  // nextPollInterval/isLessonProcessing pair and its ~20-minute cap. A
  // genuinely-stuck lesson_jobs row would otherwise poll forever.
  const pollingStartedAtRef = useRef<number | null>(null);
  const { data, error, isLoading, mutate } = useSWR<LessonStatusResponse | null>(
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
      refreshInterval: (latestData) => nextPollInterval(isLessonProcessing(latestData), pollingStartedAtRef),
    },
  );

  return {
    lesson: data?.content ?? null,
    isLoading,
    error,
    status: data?.status,
    serverError: data?.error ?? null,
    refetch: () => mutate(),
  };
}
