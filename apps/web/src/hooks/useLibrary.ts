'use client';

import useSWR from 'swr';
import { libraryService, type LibraryData } from '@/services/library.service';

interface UseLibraryResult {
  data: LibraryData | null;
  isLoading: boolean;
  error: unknown;
}

// Client-side for the same reason as useDashboard -- api.ts's auth
// interceptor only works in the browser.
export function useLibrary(): UseLibraryResult {
  const { data, error, isLoading } = useSWR<LibraryData>(
    'library',
    () => libraryService.getLibrary(),
    { shouldRetryOnError: false },
  );

  return {
    data: data ?? null,
    isLoading,
    error,
  };
}
