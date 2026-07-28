'use client';

import { useRef } from 'react';
import useSWR from 'swr';
import { dashboardService, type DashboardData } from '@/services/dashboard.service';
import { useAuth } from '@/contexts/AuthContext';
import { isLessonProcessing, nextPollInterval } from '@/lib/lessonStatusPoll';

interface UseDashboardResult {
  data: DashboardData | null;
  isLoading: boolean;
  error: unknown;
}

// A Server Component cannot use this data -- api.ts's auth interceptor only
// reads the Supabase session via the browser client (`typeof window !==
// 'undefined'`), so a server-side call goes out with no Authorization header
// and 401s. Every real, authenticated fetch in this codebase is client-side
// for the same reason (useLesson, useSessionReport).
export function useDashboard(): UseDashboardResult {
  const { user } = useAuth();
  const pollingStartedAtRef = useRef<number | null>(null);
  // Keyed by user id, not a bare literal -- SWR's cache is a shared global
  // Map for the whole tab. A bare 'dashboard' key would let a second
  // account's data flash from cache on first render after switching users
  // in the same tab (review finding). `null` key = SWR does not fetch yet.
  const { data, error, isLoading } = useSWR<DashboardData>(
    user ? `dashboard:${user.id}` : null,
    () => dashboardService.getDashboard(),
    {
      // S2-27 review fix -- see useLibrary.ts's identical comment for the
      // full rationale: SWR's polling loop silently stops revalidating once
      // an error is cached, only recovering on tab refocus/network reconnect
      // unless shouldRetryOnError lets SWR's own backoff-retry clear it first.
      shouldRetryOnError: true,
      // Same rationale as useLibrary.ts -- DashboardData has no pre-computed
      // "processing" bucket, so check continueLearning and recentLessons
      // directly. Also stops after MAX_POLL_DURATION_MS regardless (review
      // fix) -- see useLibrary.ts's identical comment.
      refreshInterval: (dashboardData) =>
        nextPollInterval(
          Boolean(
            dashboardData &&
              (isLessonProcessing(dashboardData.continueLearning) ||
                dashboardData.recentLessons.some(isLessonProcessing)),
          ),
          pollingStartedAtRef,
        ),
    },
  );

  return {
    data: data ?? null,
    isLoading,
    error,
  };
}
