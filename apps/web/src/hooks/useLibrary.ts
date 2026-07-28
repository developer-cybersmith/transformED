'use client';

import useSWR from 'swr';
import { libraryService, type LibraryData } from '@/services/library.service';
import { useAuth } from '@/contexts/AuthContext';
import { LESSON_STATUS_POLL_INTERVAL_MS } from '@/lib/lessonStatusPoll';

interface UseLibraryResult {
  data: LibraryData | null;
  isLoading: boolean;
  error: unknown;
}

// Client-side for the same reason as useDashboard -- api.ts's auth
// interceptor only works in the browser.
export function useLibrary(): UseLibraryResult {
  const { user } = useAuth();
  // Keyed by user id -- see useDashboard.ts's comment for why a bare
  // literal key is unsafe (cross-account cache leak in a shared tab).
  const { data, error, isLoading } = useSWR<LibraryData>(
    user ? `library:${user.id}` : null,
    () => libraryService.getLibrary(),
    {
      shouldRetryOnError: false,
      // S2-27: keep polling while at least one lesson is still queued/running
      // -- otherwise a lesson that finishes generating while this page is
      // just sitting open never updates without a manual refresh/navigation
      // (SWR only refetches on remount/tab-refocus by default). Stops polling
      // once nothing is in flight, to avoid needless backend load.
      refreshInterval: (libraryData) =>
        libraryData && libraryData.processing.length > 0 ? LESSON_STATUS_POLL_INTERVAL_MS : 0,
    },
  );

  return {
    data: data ?? null,
    isLoading,
    error,
  };
}
