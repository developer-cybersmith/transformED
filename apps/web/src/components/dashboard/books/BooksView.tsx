"use client";

import Link from "next/link";
import { UploadCloud } from "lucide-react";
import type { BookResponse } from "@/services/books.service";
import { BookCard } from "./BookCard";

export function BooksView({ books }: { books: BookResponse[] }) {
    // Zero books is a first-run state with a real route out, not an error (AC11).
    if (books.length === 0) {
        return (
            <div className="flex min-h-[40vh] w-full flex-col items-center justify-center gap-4 text-center">
                <p className="text-neutral-500">You haven&apos;t uploaded a textbook yet.</p>
                <Link
                    href="/upload"
                    className="inline-flex items-center gap-2 rounded-full bg-[var(--accent-primary)] px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-[var(--accent-primary-hover)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)]"
                >
                    <UploadCloud className="h-4 w-4" />
                    Upload a book
                </Link>
            </div>
        );
    }

    return (
        <div className="grid grid-cols-1 gap-6 pb-24 md:grid-cols-2 lg:grid-cols-3">
            {books.map((book) => (
                <BookCard key={book.book_id} book={book} />
            ))}
        </div>
    );
}
