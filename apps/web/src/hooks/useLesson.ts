'use client';

import { useRef, useState } from 'react';
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
  // S4-11: true once automatic polling has given up (MAX_POLL_DURATION_MS
  // elapsed while still queued/running) -- the lesson may still finish
  // generating server-side, but this hook will not find out on its own
  // anymore. The caller must show an explicit "taking longer than
  // expected" state with a manual refetch() action, not a silent forever-
  // spinner (review finding, S4-11 -- mirrors UploadFlow.tsx's giveUpSlow()).
  pollTimedOut: boolean;
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
  // Relies on apps/web/src/app/lesson/[id]/page.tsx keying <PlayerLoader> by
  // lessonId (review finding, S4-11) -- without that key, this hook instance
  // would not be guaranteed to unmount on a lessonId change (only the
  // downstream <Player> was previously keyed, once ready), and a still-
  // generating lesson A's elapsed poll window/pollTimedOut would carry over
  // to a freshly-navigated-to lesson B. A fresh mount per lessonId, rather
  // than an in-hook reset, also avoids reading/writing a ref during render
  // (banned by this repo's react-hooks/refs lint rule).
  const pollingStartedAtRef = useRef<number | null>(null);
  const [pollTimedOut, setPollTimedOut] = useState(false);

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
      refreshInterval: (latestData) => {
        const stillProcessing = isLessonProcessing(latestData);
        const interval = nextPollInterval(stillProcessing, pollingStartedAtRef);
        // The ceiling was reached while still queued/running -- SWR will not
        // call this again on its own past this point, so this is the only
        // moment this hook can ever learn polling has given up.
        if (stillProcessing && interval === 0) setPollTimedOut(true);
        return interval;
      },
    },
  );

  return {
    lesson: data?.content ?? null,
    isLoading,
    error,
    status: data?.status,
    serverError: data?.error ?? null,
    pollTimedOut,
    refetch: () => {
      // A manual refetch is the student's only way forward once polling has
      // given up -- if it's still processing, let the next automatic check
      // start a fresh window rather than immediately re-hitting the ceiling
      // from the old startedAtRef.
      pollingStartedAtRef.current = null;
      setPollTimedOut(false);
      return mutate();
    },
  };
}
