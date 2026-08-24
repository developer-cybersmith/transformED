"use client";

import { useEffect } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function LessonError({
    error,
    reset,
}: {
    error: Error & { digest?: string };
    reset: () => void;
}) {
    useEffect(() => {
        console.error("Lesson route error:", error);
    }, [error]);

    return (
        <div className="flex-1 w-full flex items-center justify-center p-6 relative z-10">
            <div className="flex flex-col items-center gap-4 max-w-md rounded-3xl bg-white p-8 text-center shadow-xl">
                <h2 className="font-serif text-xl font-semibold text-neutral-900">Something went wrong</h2>
                <p className="text-neutral-500">
                    We couldn&apos;t load this lesson. Please try again.
                </p>
                <div className="flex items-center gap-3 mt-2">
                    <Button variant="primary" size="md" className="rounded-2xl" onClick={reset}>
                        Try again
                    </Button>
                    <Link
                        href="/dashboard"
                        className="flex items-center gap-2 px-5 py-2.5 rounded-full text-sm font-medium text-neutral-700 hover:bg-neutral-100 transition-colors"
                    >
                        <ArrowLeft className="w-4 h-4" />
                        Return to Dashboard
                    </Link>
                </div>
            </div>
        </div>
    );
}
