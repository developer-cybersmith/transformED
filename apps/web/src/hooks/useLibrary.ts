'use client';

import { useRef } from 'react';
import useSWR from 'swr';
import { libraryService, type LibraryData } from '@/services/library.service';
import { useAuth } from '@/contexts/AuthContext';
import { nextPollInterval } from '@/lib/lessonStatusPoll';

interface UseLibraryResult {
  data: LibraryData | null;
  isLoading: boolean;
  error: unknown;
}

// Client-side for the same reason as useDashboard -- api.ts's auth
// interceptor only works in the browser.
export function useLibrary(): UseLibraryResult {
  const { user } = useAuth();
  const pollingStartedAtRef = useRef<number | null>(null);
  // Keyed by user id -- see useDashboard.ts's comment for why a bare
  // literal key is unsafe (cross-account cache leak in a shared tab).
  const { data, error, isLoading } = useSWR<LibraryData>(
    user ? `library:${user.id}` : null,
    () => libraryService.getLibrary(),
    {
      // S2-27 review fix: SWR's refreshInterval loop skips revalidating on any
      // tick where the cache already holds an error, and only clears that
      // error via revalidateOnFocus/revalidateOnReconnect (or a manual
      // mutate()) -- with shouldRetryOnError: false (this hook's pre-S2-27
      // setting), a single transient poll failure would silently and
      // permanently pause auto-refresh until the user blurs/refocuses the tab
      // or the network reconnects, defeating this story's whole purpose.
      // Restored to SWR's own default (true) -- its exponential backoff
      // (capped growth, not a tight hammering loop) is exactly the self-healing
      // behavior long-lived polling needs; the original false was fine for a
      // one-shot fetch but actively harmful once polling was added on top.
      shouldRetryOnError: true,
      // Keep polling while at least one lesson is still queued/running --
      // otherwise a lesson that finishes generating while this page is just
      // sitting open never updates without a manual refresh/navigation (SWR
      // only refetches on remount/tab-refocus by default). Stops polling once
      // nothing is in flight, to avoid needless backend load. Also stops after
      // MAX_POLL_DURATION_MS regardless (review fix) -- a genuinely-stuck
      // backend job must not poll forever for as long as the tab stays open.
      refreshInterval: (libraryData) =>
        nextPollInterval(Boolean(libraryData && libraryData.processing.length > 0), pollingStartedAtRef),
    },
  );

  return {
    data: data ?? null,
    isLoading,
    error,
  };
}
