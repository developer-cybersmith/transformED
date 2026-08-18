"use client";

import { motion } from "framer-motion";
import { useRouter } from "next/navigation";
import type { LessonStatusResponse } from "@/services/upload.service";

const STATUS_LABEL: Record<string, string> = {
    ready: "Ready",
    running: "Processing",
    queued: "Processing",
    failed: "Failed",
};

const STATUS_STYLE: Record<string, string> = {
    ready: "bg-emerald-50 text-emerald-600",
    running: "bg-[var(--accent-primary)]/10 text-[var(--accent-primary)]",
    queued: "bg-[var(--accent-primary)]/10 text-[var(--accent-primary)]",
    failed: "bg-red-50 text-red-500",
};

export function RecentLessons({ lessons }: { lessons: LessonStatusResponse[] }) {
    const router = useRouter();

    if (!lessons || lessons.length === 0) return null;

    return (
        <div className="w-full">
            <div className="flex items-center justify-between mb-6">
                <h2 className="font-serif text-xl font-semibold tracking-tight text-neutral-900">
                    Recently Added Lessons
                </h2>
                <button
                    type="button"
                    // Story 2-47 (S4-06): the Library route was removed and folded into Books.
                    onClick={() => router.push("/books")}
                    className="text-sm font-medium text-[var(--accent-primary)] hover:text-[var(--accent-primary-hover)] cursor-pointer transition-colors"
                >
                    View All
                </button>
            </div>

            <div className="flex gap-6 overflow-x-auto pb-8 snap-x snap-mandatory scrollbar-hide -mx-4 px-4 sm:mx-0 sm:px-0">
                {lessons.map((lesson, index) => (
                    <motion.div
                        key={lesson.lesson_id}
                        onClick={lesson.status === 'ready' ? () => router.push(`/lesson/${lesson.lesson_id}`) : undefined}
                        initial={{ opacity: 0, x: 20 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ duration: 0.5, delay: index * 0.1 }}
                        className={`group relative flex-shrink-0 w-[280px] sm:w-[320px] rounded-3xl overflow-hidden bg-white border border-neutral-100 shadow-sm transition-all duration-500 snap-start ${lesson.status === 'ready' ? 'hover:shadow-xl cursor-pointer' : 'cursor-default opacity-80'}`}
                    >
                        <div className="p-5">
                            <span
                                className={`inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-semibold uppercase tracking-wide mb-3 ${STATUS_STYLE[lesson.status] ?? "bg-neutral-100 text-neutral-500"}`}
                            >
                                {STATUS_LABEL[lesson.status] ?? lesson.status}
                            </span>
                            <h3 className="text-base font-semibold text-neutral-900 leading-snug line-clamp-2">
                                {lesson.title ?? "Untitled Lesson"}
                            </h3>
                        </div>
                    </motion.div>
                ))}
            </div>
        </div>
    );
}
