'use client';

import useSWR from 'swr';
import { getSessionReport } from '@/lib/assessment';
import type { SessionReport } from '@/types/assessment';

interface UseSessionReportResult {
  report: SessionReport | null;
  isLoading: boolean;
  error: unknown;
}

export function useSessionReport(sessionId: string): UseSessionReportResult {
  const { data, error, isLoading } = useSWR<SessionReport | null>(
    sessionId ? `session-report:${sessionId}` : null,
    async () => getSessionReport(sessionId),
    // A session that 404s (nonexistent or not owned by the caller, per SEC-006)
    // will 404 forever — retrying on a growing backoff just hammers the backend
    // for as long as the tab stays open, for no chance of a different outcome.
    { shouldRetryOnError: false },
  );

  return {
    report: data ?? null,
    isLoading,
    error,
  };
}
