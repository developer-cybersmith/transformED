"use client";

import { useState } from "react";
import Link from "next/link";
import { Play, Loader2, AlertCircle, ChevronDown, ChevronUp } from "lucide-react";
import { watchableLessonId, type ChapterResponse, type LatestLesson } from "@/services/books.service";
import { ChapterGenerateControl } from "./ChapterGenerateControl";

// W2 shipped Generate DISABLED with a stated reason, because nothing behind it
// existed yet (W2 AC10: never enabled-and-inert). W3 is that "next release" --
// the button is now live, so the reason constant is gone rather than left behind
// as a string nothing renders.

// Page ranges are 0-BASED PDF page indices, not printed page numbers. Never
// show a bare "page 69" to a student without saying what the number is.
export const PAGE_RANGE_EXPLANATION =
    "0-based PDF page indices — these are positions in the PDF file, not the page numbers printed on the page.";

function lessonCountLabel(count: number): string {
    return count === 1 ? "1 lesson" : `${count} lessons`;
}

function otherLessonsLabel(count: number): string {
    return count === 1 ? "1 other lesson" : `${count} other lessons`;
}

/**
 * Story 2-47 (S4-06): the same Watch-gate rule `watchableLessonId` applies to
 * `latest_lesson`, generalized to EVERY entry in `lessons` -- a non-latest
 * lesson that failed or is still generating must never earn a Watch link
 * either.
 */
function isWatchable(lesson: LatestLesson): boolean {
    return lesson.status === "ready";
}

interface ChapterRowProps {
    chapter: ChapterResponse;
    /** Needed for the generate path -- the endpoint is nested under the book. */
    bookId: string;
    /** Re-read the chapter list after a generation response (AC6). */
    onGenerated?: () => void;
}

export function ChapterRow({ chapter, bookId, onGenerated }: ChapterRowProps) {
    // AC3: gated on latest_lesson.status, NEVER on has_lesson. A chapter whose
    // only lesson failed has has_lesson === true and a non-null lesson_id.
    const readyLessonId = watchableLessonId(chapter);
    const latest = chapter.latest_lesson;
    const isGenerating = latest?.status === "queued" || latest?.status === "running";
    const pageSpan = chapter.page_end - chapter.page_start + 1;

    // Story 2-47 (S4-06): `lessons[0]` is always the same lesson as
    // `latest_lesson` (both derived server-side by the same newest-first
    // sort) -- everything after it is the "other lessons" a standalone
    // Library page used to be the only way to reach.
    const otherLessons = chapter.lessons.slice(1);
    const [expanded, setExpanded] = useState(false);

    return (
        // flex-wrap + basis-full lets ChapterGenerateControl contribute a
        // full-width panel BELOW the row while its button stays inline in it.
        <li className="flex flex-col flex-wrap gap-3 rounded-2xl border border-neutral-100 bg-white/70 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
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

                    {otherLessons.length > 0 && (
                        <button
                            type="button"
                            onClick={() => setExpanded((prev) => !prev)}
                            className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium text-[var(--accent-primary)] hover:text-[var(--accent-primary-hover)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)]"
                            aria-expanded={expanded}
                        >
                            {otherLessonsLabel(otherLessons.length)}
                            {expanded ? (
                                <ChevronUp className="h-3.5 w-3.5" />
                            ) : (
                                <ChevronDown className="h-3.5 w-3.5" />
                            )}
                        </button>
                    )}
                </div>

                {expanded && otherLessons.length > 0 && (
                    <ul className="mt-2 flex flex-col gap-1.5 border-l-2 border-neutral-100 pl-3">
                        {otherLessons.map((lesson) => (
                            <li
                                key={lesson.lesson_id}
                                className="flex items-center justify-between gap-3 text-xs text-neutral-500"
                            >
                                <span>
                                    {lesson.tier} · {lesson.status}
                                </span>
                                {isWatchable(lesson) && (
                                    <Link
                                        href={`/lesson/${lesson.lesson_id}`}
                                        className="inline-flex items-center gap-1 rounded-full bg-neutral-100 px-2.5 py-1 text-xs font-medium text-neutral-700 transition-colors hover:bg-neutral-200"
                                    >
                                        <Play className="h-3 w-3" />
                                        Watch
                                    </Link>
                                )}
                            </li>
                        ))}
                        {/* Scale & Load Q2: the server caps `lessons` at 20 (a
                            safety ceiling, not a natural bound -- see
                            content/router.py's _MAX_LESSONS_EXPOSED) but
                            `lesson_count` still reports the true total. Never
                            let that discrepancy pass silently. */}
                        {chapter.lesson_count > chapter.lessons.length && (
                            <li className="text-xs italic text-neutral-400">
                                {chapter.lesson_count - chapter.lessons.length} more lesson
                                {chapter.lesson_count - chapter.lessons.length === 1 ? "" : "s"} not
                                shown.
                            </li>
                        )}
                    </ul>
                )}

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

            {readyLessonId != null ? (
                <div className="flex shrink-0 items-center gap-2">
                    <Link
                        href={`/lesson/${readyLessonId}`}
                        className="inline-flex items-center gap-2 rounded-full bg-[var(--accent-primary)] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[var(--accent-primary-hover)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)]"
                    >
                        <Play className="h-4 w-4" />
                        Watch
                    </Link>
                </div>
            ) : isGenerating ? (
                <div className="flex shrink-0 items-center gap-2">
                    <span className="inline-flex items-center gap-2 rounded-full bg-neutral-100 px-4 py-2 text-sm text-neutral-500">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Generating…
                    </span>
                </div>
            ) : (
                <ChapterGenerateControl
                    bookId={bookId}
                    chapter={chapter}
                    onGenerated={onGenerated}
                />
            )}
        </li>
    );
}
