'use client';

import { useRef } from 'react';
import useSWR from 'swr';
import { booksService, type BookStatus, type ChapterResponse } from '@/services/books.service';
import { useAuth } from '@/contexts/AuthContext';
import { isLessonProcessing, nextPollInterval } from '@/lib/lessonStatusPoll';

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
 * `bookStatus` drives polling for the ingestion phase: a book still
 * `processing` has no chapters yet (the endpoint returns `[]`, which is the
 * NORMAL state, not an error), so we re-poll until ingestion finishes and the
 * rows appear. Once the book is `ready`, polling used to stop dead -- even
 * while a chapter's own lesson generation (triggered by "Generate", tracked
 * per-chapter in `latest_lesson.status`) was still `queued`/`running`. That
 * left a "Generating..." card frozen until a manual page refresh, because
 * nothing was left polling to notice the transition to `ready`/`failed`.
 * Polling now also continues while ANY loaded chapter has a lesson actively
 * generating, using the same `isLessonProcessing` vocabulary other pages
 * already poll lessons with.
 */
export function useChapters(bookId: string, bookStatus?: BookStatus): UseChaptersResult {
    const { user } = useAuth();
    const pollingStartedAtRef = useRef<number | null>(null);

    const { data, error, isLoading, mutate } = useSWR<ChapterResponse[]>(
        user && bookId ? `chapters:${user.id}:${bookId}` : null,
        () => booksService.listChapters(bookId),
        {
            shouldRetryOnError: true,
            // SWR calls this with the latest fetched data, not a closure over
            // the hook's own `data` -- using the parameter (not the outer
            // `data`) is what lets a poll tick started BEFORE this render's
            // data landed still see it.
            refreshInterval: (latestData) => {
                const aLessonIsGenerating = (latestData ?? []).some((chapter) =>
                    isLessonProcessing(chapter.latest_lesson),
                );
                return nextPollInterval(
                    bookStatus === 'processing' || aLessonIsGenerating,
                    pollingStartedAtRef,
                );
            },
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
