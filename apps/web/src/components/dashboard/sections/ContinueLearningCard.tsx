"use client";

import { motion } from "framer-motion";
import { Play, Clock, LayoutGrid } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MockLesson } from "@/mocks/data/lessons";
import { useRouter } from "next/navigation";

export function ContinueLearningCard({ lesson }: { lesson: MockLesson | null }) {
    const router = useRouter();

    if (!lesson) {
        return null;
    }

    const completionPercentage = lesson.progressPercent;
    const radius = 32;
    const circumference = 2 * Math.PI * radius;
    const strokeDashoffset = circumference - (completionPercentage / 100) * circumference;

    return (
        <div className="mb-0">
            <div className="flex items-center justify-between mb-4">
                <h2 className="font-serif text-xl font-semibold tracking-tight text-neutral-900">
                    Continue Learning
                </h2>
                <span className="text-sm font-medium text-[var(--accent-primary)] hover:text-[var(--accent-primary-hover)] cursor-pointer transition-colors">
                    View Path
                </span>
            </div>

            <motion.div
                onClick={() => router.push(`/lesson/${lesson.id}`)}
                whileHover={{ y: -4, transition: { duration: 0.2 } }}
                className="group relative w-full bg-white rounded-3xl p-6 md:p-8 shadow-[0_8px_30px_rgb(0,0,0,0.04)] border border-neutral-100 flex flex-col md:flex-row md:items-center justify-between gap-8 transition-shadow hover:shadow-[0_20px_40px_-12px_rgba(0,0,0,0.1)] cursor-pointer overflow-hidden"
            >
                {/* Soft Background Highlight */}
                <div className="absolute top-0 right-0 w-1/3 h-full bg-gradient-to-l from-[var(--accent-primary)]/5 to-transparent pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-500" />

                <div className="flex items-start md:items-center gap-6 relative z-10 w-full md:w-auto">

                    {/* Circular Progress Ring */}
                    <div className="relative w-24 h-24 shrink-0 flex items-center justify-center">
                        <svg className="w-full h-full -rotate-90" viewBox="0 0 80 80">
                            <circle
                                className="text-neutral-100"
                                strokeWidth="6"
                                stroke="currentColor"
                                fill="transparent"
                                r={radius}
                                cx="40"
                                cy="40"
                            />
                            <circle
                                className="text-[var(--accent-primary)] transition-all duration-1000 ease-out"
                                strokeWidth="6"
                                strokeDasharray={circumference}
                                strokeDashoffset={strokeDashoffset}
                                strokeLinecap="round"
                                stroke="currentColor"
                                fill="transparent"
                                r={radius}
                                cx="40"
                                cy="40"
                            />
                        </svg>
                        <div className="absolute inset-0 flex flex-col items-center justify-center">
                            <span className="text-xl font-bold text-neutral-800">{completionPercentage}%</span>
                        </div>
                    </div>

                    <div>
                        <div className="text-xs font-semibold text-[var(--accent-primary)] uppercase tracking-wider mb-2">
                            {lesson.chapterTitle}
                        </div>
                        <h3 className="text-2xl font-semibold text-neutral-900 mb-1">
                            {lesson.title}
                        </h3>
                        <div className="flex items-center gap-4 text-sm text-neutral-500 mt-2">
                            <span className="flex items-center gap-1.5">
                                <Clock className="w-4 h-4" /> {Math.ceil(lesson.durationSeconds / 60)} mins total
                            </span>
                            <span className="w-1 h-1 rounded-full bg-neutral-300" />
                            <span className="flex items-center gap-1.5">
                                <LayoutGrid className="w-4 h-4" /> Actively Learning
                            </span>
                        </div>
                    </div>
                </div>

                <div className="flex items-center gap-6 relative z-10 w-full md:w-auto justify-between md:justify-end border-t md:border-t-0 border-neutral-100 pt-6 md:pt-0 mt-2 md:mt-0">
                    <div className="text-sm text-neutral-400">
                        Last opened 2 hours ago
                    </div>
                    <div className="inline-flex items-center justify-center whitespace-nowrap text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 bg-[var(--accent-primary)] text-white shadow hover:bg-[var(--accent-primary)]/90 h-10 px-8 py-2 rounded-2xl shrink-0">
                        <Play className="w-4 h-4 mr-2 fill-current" /> Resume
                    </div>
                </div>

            </motion.div>
        </div>
    );
}
