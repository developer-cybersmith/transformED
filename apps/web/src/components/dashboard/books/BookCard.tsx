"use client";

import Link from "next/link";
import { BookOpen, Loader2, AlertCircle } from "lucide-react";
import type { BookResponse } from "@/services/books.service";

function statusLabel(book: BookResponse): string {
    if (book.status === "processing") return "Detecting chapters…";
    if (book.status === "failed") return "Ingestion failed";
    return `${book.chapter_count} chapters`;
}

export function BookCard({ book }: { book: BookResponse }) {
    // page_count is null while ingesting -- never render "null pages".
    const pages = book.page_count == null ? null : `${book.page_count} pages`;

    return (
        <Link
            href={`/books/${book.book_id}`}
            className="group flex flex-col gap-3 rounded-3xl border border-neutral-100 bg-white/70 p-6 transition-shadow hover:shadow-[0_8px_30px_rgb(0,0,0,0.06)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)]"
        >
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--accent-secondary)]">
                <BookOpen className="h-5 w-5 text-[var(--accent-primary)]" />
            </div>

            <h2 className="truncate text-base font-medium text-neutral-900">{book.filename}</h2>

            <div className="flex items-center gap-2 text-sm text-neutral-500">
                {book.status === "processing" && <Loader2 className="h-4 w-4 animate-spin" />}
                {book.status === "failed" && <AlertCircle className="h-4 w-4 text-red-400" />}
                <span>{statusLabel(book)}</span>
                {pages != null && <span className="text-neutral-300">·</span>}
                {pages != null && <span>{pages}</span>}
            </div>
        </Link>
    );
}
