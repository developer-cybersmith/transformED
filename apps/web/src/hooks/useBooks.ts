'use client';

import { useRef } from 'react';
import useSWR from 'swr';
import { booksService, type BookResponse } from '@/services/books.service';
import { useAuth } from '@/contexts/AuthContext';
import { nextPollInterval } from '@/lib/lessonStatusPoll';

interface UseBooksResult {
    data: BookResponse[] | null;
    isLoading: boolean;
    error: unknown;
}

interface UseBookResult {
    data: BookResponse | null;
    isLoading: boolean;
    error: unknown;
}

// Client-side for the same reason as useDashboard -- api.ts's auth interceptor
// only reads the Supabase session in the browser, so an RSC calling this would
// send no Authorization header and 401.
export function useBooks(): UseBooksResult {
    const { user } = useAuth();
    const pollingStartedAtRef = useRef<number | null>(null);

    // Keyed by user id so a cache entry can never leak across accounts in a
    // shared browser tab (same rule as useDashboard).
    const { data, error, isLoading } = useSWR<BookResponse[]>(
        user ? `books:${user.id}` : null,
        () => booksService.listBooks(),
        {
            shouldRetryOnError: true,
            // Ingestion status is REST-polled (never over ws.ts -- frozen
            // contract). Keep polling only while a book is still `processing`,
            // and only up to MAX_POLL_DURATION_MS, so a stuck ingestion can't
            // poll forever for as long as the tab stays open.
            // NB: nextPollInterval, not isLessonProcessing -- the latter tests
            // queued|running, the LESSON vocabulary, and is always false here.
            refreshInterval: (books) =>
                nextPollInterval(Boolean(books?.some((b) => b.status === 'processing')), pollingStartedAtRef),
        },
    );

    return { data: data ?? null, isLoading, error };
}

/** Single book, polled while it is still ingesting. */
export function useBook(bookId: string): UseBookResult {
    const { user } = useAuth();
    const pollingStartedAtRef = useRef<number | null>(null);

    const { data, error, isLoading } = useSWR<BookResponse>(
        user && bookId ? `book:${user.id}:${bookId}` : null,
        () => booksService.getBook(bookId),
        {
            shouldRetryOnError: true,
            refreshInterval: (book) =>
                nextPollInterval(book?.status === 'processing', pollingStartedAtRef),
        },
    );

    return { data: data ?? null, isLoading, error };
}
