'use client';

import useSWR from 'swr';
import { dashboardService, type DashboardData } from '@/services/dashboard.service';
import { useAuth } from '@/contexts/AuthContext';

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
  // Keyed by user id, not a bare literal -- SWR's cache is a shared global
  // Map for the whole tab. A bare 'dashboard' key would let a second
  // account's data flash from cache on first render after switching users
  // in the same tab (review finding). `null` key = SWR does not fetch yet.
  const { data, error, isLoading } = useSWR<DashboardData>(
    user ? `dashboard:${user.id}` : null,
    () => dashboardService.getDashboard(),
    { shouldRetryOnError: false },
  );

  return {
    data: data ?? null,
    isLoading,
    error,
  };
}
