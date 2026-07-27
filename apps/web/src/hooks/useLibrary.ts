'use client';

import useSWR from 'swr';
import { libraryService, type LibraryData } from '@/services/library.service';
import { useAuth } from '@/contexts/AuthContext';

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
    { shouldRetryOnError: false },
  );

  return {
    data: data ?? null,
    isLoading,
    error,
  };
}
