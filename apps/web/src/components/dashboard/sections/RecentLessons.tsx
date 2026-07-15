"use client";

import { motion } from "framer-motion";
import { Play, CheckCircle2, AlertCircle, RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { formatTimeAgo, formatLessonStatusLabel } from "@/lib/utils";
import type { LessonStatusResponse } from "@/services/upload.service";

interface RecentLessonsProps {
    lessons: LessonStatusResponse[];
    error: string | null;
}

function isGenerating(lesson: LessonStatusResponse): boolean {
    return lesson.status === 'queued' || lesson.status === 'running';
}

export function RecentLessons({ lessons, error }: RecentLessonsProps) {
    const router = useRouter();

    if ((!lessons || lessons.length === 0) && !error) return null;

    return (
        <div className="w-full">
            <div className="flex items-center justify-between mb-6">
                <h2 className="font-serif text-xl font-semibold tracking-tight text-neutral-900">
                    Recently Added Lessons
                </h2>
                <button
                    type="button"
                    onClick={() => router.push("/library")}
                    className="text-sm font-medium text-[var(--accent-primary)] hover:text-[var(--accent-primary-hover)] cursor-pointer transition-colors"
                >
                    View All
                </button>
            </div>

            {error ? (
                <p className="text-sm font-medium text-red-500">{error}</p>
            ) : (
                <div className="flex gap-6 overflow-x-auto pb-8 snap-x snap-mandatory scrollbar-hide -mx-4 px-4 sm:mx-0 sm:px-0">
                    {lessons.map((lesson, index) => {
                        const generating = isGenerating(lesson);
                        const isFailed = lesson.status === 'failed';
                        const isReady = lesson.status === 'ready';

                        return (
                            <motion.div
                                key={lesson.lesson_id}
                                onClick={isReady ? () => router.push(`/lesson/${lesson.lesson_id}`) : undefined}
                                role={isReady ? "button" : undefined}
                                tabIndex={isReady ? 0 : undefined}
                                onKeyDown={isReady ? (e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault();
                                        router.push(`/lesson/${lesson.lesson_id}`);
                                    }
                                } : undefined}
                                initial={{ opacity: 0, x: 20 }}
                                animate={{ opacity: 1, x: 0 }}
                                transition={{ duration: 0.5, delay: index * 0.1 }}
                                className={`group relative flex-shrink-0 w-[280px] sm:w-[320px] rounded-3xl bg-white border border-neutral-100 shadow-sm transition-all duration-500 snap-start h-full p-6 ${isReady ? 'cursor-pointer hover:shadow-xl focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--accent-primary)]/20' : 'opacity-90 cursor-default'
                                    }`}
                            >
                                <div className="flex items-center gap-2 mb-4">
                                    {generating && (
                                        <div className="px-3 py-1.5 rounded-full bg-[var(--accent-primary)]/90 text-white flex items-center gap-1.5 text-xs font-medium shadow-sm">
                                            <RefreshCw className="w-3.5 h-3.5 animate-spin" /> {formatLessonStatusLabel(lesson.status)}
                                        </div>
                                    )}
                                    {isReady && (
                                        <div className="px-3 py-1.5 rounded-full bg-emerald-500/90 text-white flex items-center gap-1.5 text-xs font-medium shadow-sm">
                                            <CheckCircle2 className="w-3.5 h-3.5" /> {formatLessonStatusLabel(lesson.status)}
                                        </div>
                                    )}
                                    {isFailed && (
                                        <div className="px-3 py-1.5 rounded-full bg-red-500/90 text-white flex items-center gap-1.5 text-xs font-medium shadow-sm">
                                            <AlertCircle className="w-3.5 h-3.5" /> {formatLessonStatusLabel(lesson.status)}
                                        </div>
                                    )}
                                    {isReady && (
                                        <span className="ml-auto opacity-0 group-hover:opacity-100 transition-opacity duration-300 text-[var(--accent-primary)]">
                                            <Play className="w-4 h-4 fill-current" />
                                        </span>
                                    )}
                                </div>

                                <h3 className="text-base font-semibold text-neutral-900 leading-snug line-clamp-2 min-h-[2.75rem] mb-4">
                                    {lesson.title ?? 'Untitled Lesson'}
                                </h3>

                                <div className="text-xs font-medium text-neutral-400">
                                    {lesson.created_at && <span>Created {formatTimeAgo(lesson.created_at)}</span>}
                                </div>
                            </motion.div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
