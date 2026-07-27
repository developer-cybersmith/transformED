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

            {!isLoading && error != null && (
                <div className="flex min-h-[40vh] w-full flex-col items-center justify-center gap-2 text-center text-neutral-400">
                    <p>We couldn&apos;t load your library right now.</p>
                </div>
            )}

            {!isLoading && error == null && data && <LibraryView initialData={data} />}
        </div>
    );
}
