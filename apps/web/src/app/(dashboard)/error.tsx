"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";

export default function DashboardError({
    error,
    reset,
}: {
    error: Error & { digest?: string };
    reset: () => void;
}) {
    useEffect(() => {
        console.error("Dashboard route error:", error);
    }, [error]);

    return (
        <div className="flex min-h-[60vh] w-full flex-col items-center justify-center gap-4 text-center">
            <h2 className="font-serif text-xl font-semibold text-neutral-900">Something went wrong</h2>
            <p className="max-w-md text-neutral-500">
                We couldn&apos;t load this page. Please try again.
            </p>
            <Button variant="primary" size="md" className="rounded-2xl" onClick={reset}>
                Try again
            </Button>
        </div>
    );
}
