"use client";

import { BooksView } from "@/components/dashboard/books/BooksView";
import { useBooks } from "@/hooks/useBooks";

export default function BooksPage() {
    // Client-side fetch (not a server-side call) -- api.ts's auth interceptor
    // only reads the Supabase session in the browser, so an RSC would 401.
    const { data, error, isLoading } = useBooks();

    return (
        <div className="w-full max-w-[1400px] mx-auto pt-6 pb-24">
            <div className="mb-10">
                <h1 className="font-serif text-3xl font-semibold text-neutral-900 tracking-tight mb-2">Your Books</h1>
                <p className="text-neutral-500 text-lg">
                    Browse the textbooks you&apos;ve uploaded and pick a chapter to study.
                </p>
            </div>

            {isLoading && (
                <div className="flex-1 flex items-center justify-center text-neutral-400">
                    <div className="animate-pulse">Loading intelligence...</div>
                </div>
            )}

            {/* A background poll failure must not hide books the student can
                already see -- SWR keeps the last good `data` alongside a
                transient `error`. Same banner-plus-stale-data pattern as
                library/page.tsx. */}
            {!isLoading && error != null && data && (
                <div className="rounded-2xl border border-red-100 bg-red-50 px-5 py-3 text-sm text-red-600 mb-6">
                    We couldn&apos;t refresh your books just now. Showing your last known results.
                </div>
            )}

            {!isLoading && data && <BooksView books={data} />}

            {!isLoading && error != null && !data && (
                <div className="flex min-h-[40vh] w-full flex-col items-center justify-center gap-2 text-center text-neutral-400">
                    <p>We couldn&apos;t load your books right now.</p>
                </div>
            )}
        </div>
    );
}
