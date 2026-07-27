import { libraryService, type LibraryData } from "@/services/library.service";
import { LibraryView } from "@/components/library/LibraryView";
import { Suspense } from "react";

export default async function LibraryPage() {
    return (
        <div className="w-full max-w-[1400px] mx-auto pt-6 pb-24">
            <div className="mb-10">
                <h1 className="font-serif text-3xl font-semibold text-neutral-900 tracking-tight mb-2">Your Library</h1>
                <p className="text-neutral-500 text-lg">Access your generated lessons, review past modules, and track your learning progress.</p>
            </div>

            <Suspense fallback={
                <div className="flex-1 flex items-center justify-center text-neutral-400">
                    <div className="animate-pulse">Loading intelligence...</div>
                </div>
            }>
                <LibraryDataFetcher />
            </Suspense>
        </div>
    );
}

export async function LibraryDataFetcher() {
    let data: LibraryData | null = null;
    try {
        data = await libraryService.getLibrary();
    } catch (error) {
        // Real API unavailable -- fall through to the graceful empty-state below.
        console.error("LibraryDataFetcher: failed to load library data", error);
    }

    if (!data) {
        return (
            <div className="flex min-h-[40vh] w-full flex-col items-center justify-center gap-2 text-center text-neutral-400">
                <p>We couldn&apos;t load your library right now.</p>
            </div>
        );
    }

    return <LibraryView initialData={data} />;
}
