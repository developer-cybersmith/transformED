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
  );

  return {
    report: data ?? null,
    isLoading,
    error,
  };
}
