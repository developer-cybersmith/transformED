"use client";

import { motion } from "framer-motion";
import { Play } from "lucide-react";
import { MockLesson } from "@/mocks/data/lessons";
import { useRouter } from "next/navigation";

export function RecentLessons({ lessons }: { lessons: MockLesson[] }) {
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
                    onClick={() => router.push("/library")}
                    className="text-sm font-medium text-[var(--accent-primary)] hover:text-[var(--accent-primary-hover)] cursor-pointer transition-colors"
                >
                    View All
                </button>
            </div>

            <div className="flex gap-6 overflow-x-auto pb-8 snap-x snap-mandatory scrollbar-hide -mx-4 px-4 sm:mx-0 sm:px-0">
                {lessons.map((lesson, index) => {
                    // Assign deterministic fake thumbnails
                    const thumbnails = [
                        "https://images.unsplash.com/photo-1555949963-aa79dcee981c?auto=format&fit=crop&q=80&w=600&h=400",
                        "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&q=80&w=600&h=400",
                        "https://images.unsplash.com/photo-1605745341112-85968b19335b?auto=format&fit=crop&q=80&w=600&h=400"
                    ];
                    return (
                        <motion.div
                            key={lesson.id}
                            onClick={() => router.push(`/lesson/${lesson.id}`)}
                            initial={{ opacity: 0, x: 20 }}
                            animate={{ opacity: 1, x: 0 }}
                            transition={{ duration: 0.5, delay: index * 0.1 }}
                            className="group relative flex-shrink-0 w-[280px] sm:w-[320px] rounded-3xl overflow-hidden bg-white border border-neutral-100 shadow-sm hover:shadow-xl transition-all duration-500 cursor-pointer snap-start h-full"
                        >
                            {/* Thumbnail */}
                            <div className="relative w-full h-40 sm:h-44 overflow-hidden">
                                <div className="absolute inset-0 bg-neutral-900/10 group-hover:bg-neutral-900/0 transition-colors z-10 duration-500" />
                                <img
                                    src={thumbnails[index % thumbnails.length]}
                                    alt={lesson.title}
                                    className="w-full h-full object-cover transform group-hover:scale-105 transition-transform duration-700 ease-out"
                                />

                                {/* Play overlay on hover */}
                                <div className="absolute inset-0 z-20 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-300">
                                    <div className="w-12 h-12 rounded-full bg-white/30 backdrop-blur-md flex items-center justify-center text-white border border-white/40 shadow-lg">
                                        <Play className="w-5 h-5 fill-current ml-1" />
                                    </div>
                                </div>
                            </div>

                            {/* Content Segment */}
                            <div className="p-5">
                                <div className="text-xs font-medium text-[var(--accent-primary)] mb-1 uppercase tracking-wide">
                                    {lesson.chapterTitle}
                                </div>
                                <h3 className="text-base font-semibold text-neutral-900 leading-snug line-clamp-2 min-h-[2.75rem] mb-4">
                                    {lesson.title}
                                </h3>

                                {/* Progress track */}
                                <div className="relative w-full h-1.5 bg-neutral-100 rounded-full overflow-hidden">
                                    <motion.div
                                        initial={{ width: 0 }}
                                        animate={{ width: `${lesson.progressPercent}%` }}
                                        transition={{ duration: 1, delay: 0.5 + (index * 0.1) }}
                                        className={`absolute top-0 left-0 h-full rounded-full ${lesson.status === 'completed' ? 'bg-emerald-500' : 'bg-[var(--accent-primary)]'}`}
                                    />
                                </div>
                                <div className="flex justify-between items-center mt-2.5">
                                    <span className="text-[11px] font-medium text-neutral-400 uppercase">Progress</span>
                                    <span className="text-[11px] font-bold text-neutral-700">{lesson.progressPercent}%</span>
                                </div>
                            </div>
                        </motion.div>
                    );
                })}
            </div>
        </div>
    );
}
