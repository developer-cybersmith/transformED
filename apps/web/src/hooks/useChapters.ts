'use client';

import { useRef } from 'react';
import useSWR from 'swr';
import { booksService, type BookStatus, type ChapterResponse } from '@/services/books.service';
import { useAuth } from '@/contexts/AuthContext';
import { nextPollInterval } from '@/lib/lessonStatusPoll';

interface UseChaptersResult {
    data: ChapterResponse[] | null;
    isLoading: boolean;
    error: unknown;
    /**
     * Re-fetch the chapter list (W3 AC6). After a 202 the card must move to
     * "Generating…" without a page reload, and the honest way to do that is to
     * ask the server again -- the card's state comes from `latest_lesson.status`,
     * so local optimistic state would be a second source of truth that can
     * disagree with it.
     */
    revalidate: () => void;
}

/**
 * Chapters for one book. Client-side only (api.ts's auth interceptor is
 * browser-only). Keyed by user id AND book id so a cache entry cannot leak
 * across accounts.
 *
 * `bookStatus` drives polling: a book still `processing` has no chapters yet
 * (the endpoint returns `[]`, which is the NORMAL state, not an error), so we
 * re-poll until ingestion finishes and the rows appear.
 */
export function useChapters(bookId: string, bookStatus?: BookStatus): UseChaptersResult {
    const { user } = useAuth();
    const pollingStartedAtRef = useRef<number | null>(null);

    const { data, error, isLoading, mutate } = useSWR<ChapterResponse[]>(
        user && bookId ? `chapters:${user.id}:${bookId}` : null,
        () => booksService.listChapters(bookId),
        {
            shouldRetryOnError: true,
            // Book vocabulary ('processing'), not the lesson vocabulary --
            // isLessonProcessing would be permanently false here.
            refreshInterval: () => nextPollInterval(bookStatus === 'processing', pollingStartedAtRef),
        },
    );

    return {
        data: data ?? null,
        isLoading,
        error,
        // Fire-and-forget: a failed revalidation surfaces through `error` and the
        // stale-data banner, exactly like a failed poll. Returning the promise
        // would invite a caller to await it and block the UI on a GET.
        revalidate: () => {
            void mutate();
        },
    };
}
