"use client";

import Link from "next/link";
import { Play, Loader2, AlertCircle, Sparkles } from "lucide-react";
import { watchableLessonId, type ChapterResponse } from "@/services/books.service";

// W3 wires the real POST .../lessons call. Until then the button ships
// DISABLED with a stated reason -- never enabled-and-inert (AC10).
export const GENERATE_DISABLED_REASON =
    "Lesson generation from a chapter isn't available yet — it arrives in the next release.";

// Page ranges are 0-BASED PDF page indices, not printed page numbers. Never
// show a bare "page 69" to a student without saying what the number is.
export const PAGE_RANGE_EXPLANATION =
    "0-based PDF page indices — these are positions in the PDF file, not the page numbers printed on the page.";

function lessonCountLabel(count: number): string {
    return count === 1 ? "1 lesson" : `${count} lessons`;
}

export function ChapterRow({ chapter }: { chapter: ChapterResponse }) {
    // AC3: gated on latest_lesson.status, NEVER on has_lesson. A chapter whose
    // only lesson failed has has_lesson === true and a non-null lesson_id.
    const readyLessonId = watchableLessonId(chapter);
    const latest = chapter.latest_lesson;
    const isGenerating = latest?.status === "queued" || latest?.status === "running";
    const pageSpan = chapter.page_end - chapter.page_start + 1;

    return (
        <li className="flex flex-col gap-3 rounded-2xl border border-neutral-100 bg-white/70 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-medium text-neutral-400 tabular-nums">
                        {String(chapter.chapter_index + 1).padStart(2, "0")}
                    </span>
                    <h3 className="truncate text-[15px] font-medium text-neutral-900">{chapter.title}</h3>

                    {chapter.lesson_count > 0 && (
                        <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs text-neutral-600">
                            {lessonCountLabel(chapter.lesson_count)}
                        </span>
                    )}

                    {latest != null && (
                        <span className="rounded-full bg-neutral-50 px-2 py-0.5 text-xs text-neutral-500">
                            latest: {latest.status} · {latest.tier}
                        </span>
                    )}
                </div>

                <p className="mt-1 text-xs text-neutral-500" title={PAGE_RANGE_EXPLANATION}>
                    PDF pages {chapter.page_start}–{chapter.page_end} (0-based index) · {pageSpan} pages
                </p>

                {/* boundary_confidence describes HOW the chapter was detected -- it is
                    not a quality score. Only `fallback` is worth surfacing, quietly:
                    it means detection found no structure at all. */}
                {chapter.boundary_confidence === "fallback" && (
                    <p className="mt-1 flex items-center gap-1.5 text-xs text-neutral-400">
                        <AlertCircle className="h-3.5 w-3.5" />
                        No chapter structure was detected in this PDF — these boundaries are a fallback.
                    </p>
                )}
            </div>

            <div className="flex shrink-0 items-center gap-2">
                {readyLessonId != null ? (
                    <Link
                        href={`/lesson/${readyLessonId}`}
                        className="inline-flex items-center gap-2 rounded-full bg-[var(--accent-primary)] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[var(--accent-primary-hover)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)]"
                    >
                        <Play className="h-4 w-4" />
                        Watch
                    </Link>
                ) : isGenerating ? (
                    <span className="inline-flex items-center gap-2 rounded-full bg-neutral-100 px-4 py-2 text-sm text-neutral-500">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Generating…
                    </span>
                ) : (
                    <button
                        type="button"
                        disabled
                        aria-disabled="true"
                        title={GENERATE_DISABLED_REASON}
                        className="inline-flex cursor-not-allowed items-center gap-2 rounded-full border border-neutral-200 px-4 py-2 text-sm text-neutral-400"
                    >
                        <Sparkles className="h-4 w-4" />
                        {latest?.status === "failed" ? "Retry" : "Generate"}
                    </button>
                )}
            </div>
        </li>
    );
}
