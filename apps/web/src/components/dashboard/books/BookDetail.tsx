"use client";

import Link from "next/link";
import { ArrowLeft, Loader2 } from "lucide-react";
import { useBook } from "@/hooks/useBooks";
import { useChapters } from "@/hooks/useChapters";
import { isNotFoundError } from "@/services/books.service";
import { ChapterRow } from "./ChapterRow";

export function BookDetail({ bookId }: { bookId: string }) {
    const { data: book, error: bookError, isLoading: bookLoading } = useBook(bookId);
    const {
        data: chapters,
        error: chaptersError,
        isLoading: chaptersLoading,
        revalidate: revalidateChapters,
    } = useChapters(bookId, book?.status);

    // The 404 body is byte-identical for absent / malformed-uuid / another
    // user's book -- never 403, because a 403 would confirm the id exists.
    const notFound = isNotFoundError(bookError) || isNotFoundError(chaptersError);

    if (notFound) {
        return (
            <div className="flex min-h-[40vh] w-full flex-col items-center justify-center gap-4 text-center">
                <p className="text-neutral-500">We couldn&apos;t find that book.</p>
                <Link href="/books" className="text-sm text-[var(--accent-primary)] underline">
                    Back to your books
                </Link>
            </div>
        );
    }

    if (bookLoading && book == null) {
        return (
            <div className="flex-1 flex items-center justify-center text-neutral-400">
                <div className="animate-pulse">Loading intelligence...</div>
            </div>
        );
    }

    const staleError = (bookError != null || chaptersError != null) && book != null;

    return (
        <div className="w-full">
            <Link
                href="/books"
                className="mb-6 inline-flex items-center gap-2 text-sm text-neutral-500 transition-colors hover:text-neutral-800"
            >
                <ArrowLeft className="h-4 w-4" />
                All books
            </Link>

            <div className="mb-8">
                <h1 className="font-serif text-3xl font-semibold tracking-tight text-neutral-900">
                    {book?.filename ?? "Book"}
                </h1>
                {book != null && (
                    <p className="mt-2 text-neutral-500">
                        {book.page_count != null ? `${book.page_count} pages · ` : ""}
                        {book.chapter_count} chapters
                    </p>
                )}
            </div>

            {/* A poll failure must not hide chapters the student can already see. */}
            {staleError && (
                <div className="mb-6 rounded-2xl border border-red-100 bg-red-50 px-5 py-3 text-sm text-red-600">
                    We couldn&apos;t refresh this book just now. Showing your last known results.
                </div>
            )}

            {book?.status === "processing" && (
                <div className="mb-6 flex items-center gap-2 rounded-2xl border border-neutral-100 bg-white/70 px-5 py-3 text-sm text-neutral-500">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    We&apos;re still detecting chapters in this book. This page updates on its own.
                </div>
            )}

            {book?.status === "failed" && (
                <div className="mb-6 rounded-2xl border border-red-100 bg-red-50 px-5 py-3 text-sm text-red-600">
                    We couldn&apos;t process this book. Try uploading it again.
                </div>
            )}

            {chaptersLoading && chapters == null && (
                <div className="text-neutral-400">
                    <div className="animate-pulse">Loading chapters...</div>
                </div>
            )}

            {chapters != null && chapters.length > 0 && (
                <ul className="flex flex-col gap-3 pb-24">
                    {chapters.map((chapter) => (
                        <ChapterRow
                            key={chapter.chapter_id}
                            chapter={chapter}
                            bookId={bookId}
                            // AC6: after a generation response, re-read the
                            // server rather than mutating the card locally.
                            onGenerated={revalidateChapters}
                        />
                    ))}
                </ul>
            )}

            {/* An empty chapter list while ingesting is the NORMAL state, not an error. */}
            {chapters != null && chapters.length === 0 && book?.status !== "processing" && (
                <p className="text-neutral-400">No chapters were detected in this book.</p>
            )}

            {chaptersError != null && chapters == null && !notFound && (
                <p className="text-neutral-400">We couldn&apos;t load the chapters for this book right now.</p>
            )}
        </div>
    );
}
