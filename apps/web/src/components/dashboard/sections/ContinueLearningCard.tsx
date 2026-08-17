"use client";

import { motion } from "framer-motion";
import { Play, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { LessonStatusResponse } from "@/services/upload.service";
import { useRouter } from "next/navigation";

export function ContinueLearningCard({ lesson }: { lesson: LessonStatusResponse | null }) {
    const router = useRouter();

    if (!lesson) {
        return null;
    }

    return (
        <div className="mb-0">
            <div className="flex items-center justify-between mb-4">
                <h2 className="font-serif text-xl font-semibold tracking-tight text-neutral-900">
                    Continue Learning
                </h2>
                <button
                    type="button"
                    // Story 2-47 (S4-06): "/library" removed, folded into Books.
                    onClick={() => router.push("/books")}
                    className="text-sm font-medium text-[var(--accent-primary)] hover:text-[var(--accent-primary-hover)] cursor-pointer transition-colors"
                >
                    View Path
                </button>
            </div>

            <motion.div
                onClick={() => router.push(`/lesson/${lesson.lesson_id}`)}
                whileHover={{ y: -4, transition: { duration: 0.2 } }}
                className="group relative w-full bg-white rounded-3xl p-6 md:p-8 shadow-[0_8px_30px_rgb(0,0,0,0.04)] border border-neutral-100 flex flex-col md:flex-row md:items-center justify-between gap-8 transition-shadow hover:shadow-[0_20px_40px_-12px_rgba(0,0,0,0.1)] cursor-pointer overflow-hidden"
            >
                {/* Soft Background Highlight */}
                <div className="absolute top-0 right-0 w-1/3 h-full bg-gradient-to-l from-[var(--accent-primary)]/5 to-transparent pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-500" />

                <div className="flex items-start md:items-center gap-6 relative z-10 w-full md:w-auto">
                    <div className="relative w-24 h-24 shrink-0 flex items-center justify-center rounded-full bg-[var(--accent-primary)]/10">
                        <Sparkles className="w-9 h-9 text-[var(--accent-primary)]" />
                    </div>

                    <div>
                        <div className="text-xs font-semibold text-[var(--accent-primary)] uppercase tracking-wider mb-2">
                            Ready to continue
                        </div>
                        <h3 className="text-2xl font-semibold text-neutral-900 mb-1">
                            {lesson.title ?? "Untitled Lesson"}
                        </h3>
                    </div>
                </div>

                <div className="flex items-center gap-6 relative z-10 w-full md:w-auto justify-end border-t md:border-t-0 border-neutral-100 pt-6 md:pt-0 mt-2 md:mt-0">
                    <Button
                        variant="primary"
                        size="md"
                        className="rounded-2xl shrink-0"
                        onClick={(e) => {
                            e.stopPropagation();
                            router.push(`/lesson/${lesson.lesson_id}`);
                        }}
                    >
                        <Play className="w-4 h-4 mr-2 fill-current" /> Resume
                    </Button>
                </div>

            </motion.div>
        </div>
    );
}
