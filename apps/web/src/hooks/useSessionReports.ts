'use client';

import useSWR from 'swr';
import { listSessions } from '@/lib/assessment';
import type { SessionSummary } from '@/types/assessment';

interface UseSessionReportsResult {
  sessions: SessionSummary[];
  isLoading: boolean;
  error: unknown;
}

// Story 2-58 (BR-7). Mirrors useSessionReport.ts's own SWR pattern.
export function useSessionReports(): UseSessionReportsResult {
  const { data, error, isLoading } = useSWR<SessionSummary[]>(
    'session-reports:list',
    listSessions,
    // A transient failure here just means the index page can't load right
    // now -- no per-id 404 ambiguity like useSessionReport's own retry
    // opt-out, but retrying on a growing backoff still just hammers the
    // backend for a page the student can simply revisit later.
    { shouldRetryOnError: false }
  );

  return {
    sessions: data ?? [],
    isLoading,
    error,
  };
}
