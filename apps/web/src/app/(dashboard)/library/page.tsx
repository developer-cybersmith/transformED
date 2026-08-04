"use client";

import { LibraryView } from "@/components/library/LibraryView";
import { useLibrary } from "@/hooks/useLibrary";

export default function LibraryPage() {
    // Client-side fetch (not a server-side call) -- api.ts's auth interceptor
    // only reads the Supabase session in the browser, so this must run here.
    const { data, error, isLoading } = useLibrary();

    return (
        <div className="w-full max-w-[1400px] mx-auto pt-6 pb-24">
            <div className="mb-10">
                <h1 className="font-serif text-3xl font-semibold text-neutral-900 tracking-tight mb-2">Your Library</h1>
                <p className="text-neutral-500 text-lg">Access your generated lessons, review past modules, and track your learning progress.</p>
            </div>

            {isLoading && (
                <div className="flex-1 flex items-center justify-center text-neutral-400">
                    <div className="animate-pulse">Loading intelligence...</div>
                </div>
            )}

            {/* S2-27 review fix: a poll failure must not hide a library the
                student can already see -- SWR keeps the last good `data`
                alongside a transient `error`, so gate the empty-state message
                on "no data at all", not merely "an error exists". Matches
                dashboard/page.tsx's existing banner-plus-stale-data pattern. */}
            {!isLoading && error != null && (
                <div className="rounded-2xl border border-red-100 bg-red-50 px-5 py-3 text-sm text-red-600 mb-6">
                    We couldn&apos;t refresh your library just now. Showing your last known results.
                </div>
            )}

            {!isLoading && data && <LibraryView initialData={data} />}

            {!isLoading && error != null && !data && (
                <div className="flex min-h-[40vh] w-full flex-col items-center justify-center gap-2 text-center text-neutral-400">
                    <p>We couldn&apos;t load your library right now.</p>
                </div>
            )}
        </div>
    );
}
