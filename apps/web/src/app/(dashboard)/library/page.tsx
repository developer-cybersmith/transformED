import { libraryService } from "@/services/library.service";
import { LibraryView } from "@/components/library/LibraryView";
import { Suspense } from "react";

export default async function LibraryPage() {
    return (
        <div className="w-full max-w-[1400px] mx-auto pt-6 pb-24">
            <div className="mb-10">
                <h1 className="text-3xl font-semibold text-neutral-900 tracking-tight mb-2">Your Library</h1>
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

async function LibraryDataFetcher() {
    const response = await libraryService.getLibrary();
    return <LibraryView initialData={response.data!} />;
}
