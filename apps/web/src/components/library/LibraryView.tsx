"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { LessonStatusResponse } from "@/services/upload.service";
import type { LibraryData } from "@/services/library.service";
import { Play, CheckCircle2, AlertCircle, RefreshCw, LayoutGrid } from "lucide-react";
import { useRouter } from "next/navigation";

interface LibraryViewProps {
    initialData: LibraryData;
}

type TabKey = 'all' | 'ready' | 'processing' | 'failed';

export function LibraryView({ initialData }: LibraryViewProps) {
    const router = useRouter();
    const [activeTab, setActiveTab] = useState<TabKey>('all');

    // Aggregate all lessons
    const allLessons = [
        ...initialData.ready,
        ...initialData.processing,
        ...initialData.failed,
    ];

    // Filter Logic
    const getFilteredLessons = (): LessonStatusResponse[] => {
        if (activeTab === 'all') return allLessons;
        if (activeTab === 'ready') return initialData.ready;
        if (activeTab === 'processing') return initialData.processing;
        if (activeTab === 'failed') return initialData.failed;
        return [];
    };

    const lessons = getFilteredLessons();

    const tabs: { key: TabKey, label: string, count: number }[] = [
        { key: 'all', label: 'All Lessons', count: allLessons.length },
        { key: 'ready', label: 'Ready', count: initialData.ready.length },
        { key: 'processing', label: 'Processing', count: initialData.processing.length },
        { key: 'failed', label: 'Failed', count: initialData.failed.length },
    ];

    return (
        <div className="w-full">
            {/* Header / Tabs */}
            <div className="flex items-center gap-2 border-b border-neutral-100 pb-px mb-8">
                {tabs.map(tab => (
                    <button
                        key={tab.key}
                        onClick={() => setActiveTab(tab.key)}
                        className={`relative px-6 py-3 text-sm font-medium transition-colors ${activeTab === tab.key ? 'text-neutral-900' : 'text-neutral-400 hover:text-neutral-600'
                            }`}
                    >
                        {tab.label}
                        <span className={`ml-2 px-2 py-0.5 rounded-full text-xs ${activeTab === tab.key ? 'bg-neutral-100 text-neutral-600' : 'bg-neutral-50 text-neutral-400'
                            }`}>
                            {tab.count}
                        </span>

                        {activeTab === tab.key && (
                            <motion.div
                                layoutId="library-tab-indicator"
                                className="absolute bottom-[-1px] left-0 right-0 h-0.5 bg-[var(--accent-primary)] rounded-t-full"
                            />
                        )}
                    </button>
                ))}
            </div>

            {/* Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 pb-24">
                <AnimatePresence mode="popLayout">
                    {lessons.map((lesson, idx) => (
                        <motion.div
                            key={lesson.lesson_id}
                            layout
                            layoutId={lesson.lesson_id}
                            initial={{ opacity: 0, y: 20 }}
                            animate={{
                                opacity: 1,
                                y: 0,
                                transition: { duration: 0.4, ease: "easeOut", delay: idx * 0.05 }
                            }}
                            exit={{
                                opacity: 0,
                                scale: 0.95,
                                transition: { duration: 0.2, ease: "easeIn" }
                            }}
                            transition={{ layout: { type: "spring", stiffness: 350, damping: 30 } }}
                            className="w-full flex"
                        >
                            <LibraryCard
                                lesson={lesson}
                                onClick={() => router.push(`/lesson/${lesson.lesson_id}`)}
                            />
                        </motion.div>
                    ))}
                    {lessons.length === 0 && (
                        <motion.div
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            className="col-span-full h-64 flex flex-col items-center justify-center text-neutral-400 border-2 border-dashed border-neutral-200 rounded-3xl"
                        >
                            <LayoutGrid className="w-8 h-8 mb-4 text-neutral-300" />
                            <p>No lessons found in this category.</p>
                        </motion.div>
                    )}
                </AnimatePresence>
            </div>
        </div>
    );
}

function LibraryCard({ lesson, onClick }: { lesson: LessonStatusResponse, onClick: () => void }) {
    const isProcessing = lesson.status === 'queued' || lesson.status === 'running';
    const isFailed = lesson.status === 'failed';
    const isReady = lesson.status === 'ready';

    return (
        <div
            onClick={isReady ? onClick : undefined}
            className={`group relative w-full bg-white rounded-3xl border border-neutral-100 shadow-sm transition-[box-shadow,transform] duration-300 flex flex-col overflow-hidden ${isProcessing || isFailed ? 'opacity-80 cursor-default' : 'cursor-pointer hover:shadow-xl hover:-translate-y-1'
                }`}
        >
            {/* Status header — no thumbnail exists in the real pipeline, so this is a
                decorative status panel instead of a stock/broken image. */}
            <div className="relative w-full h-32 overflow-hidden bg-neutral-100 shrink-0 flex items-center justify-center">
                {isProcessing && <RefreshCw className="w-8 h-8 text-neutral-300 animate-spin" />}
                {isReady && (
                    <div className="w-14 h-14 rounded-full bg-white/60 backdrop-blur-md flex items-center justify-center text-neutral-400 border border-neutral-200 shadow-sm group-hover:bg-[var(--accent-primary)] group-hover:text-white group-hover:border-transparent transition-colors">
                        <Play className="w-6 h-6 fill-current ml-1" />
                    </div>
                )}
                {isFailed && <AlertCircle className="w-8 h-8 text-red-300" />}

                <div className="absolute top-4 right-4 flex items-center gap-2">
                    {isProcessing && (
                        <div className="px-3 py-1.5 rounded-full bg-[var(--accent-primary)]/90 text-white backdrop-blur flex items-center gap-1.5 text-xs font-medium shadow-sm">
                            <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Processing
                        </div>
                    )}
                    {isReady && (
                        <div className="px-3 py-1.5 rounded-full bg-emerald-500/90 text-white backdrop-blur flex items-center gap-1.5 text-xs font-medium shadow-sm">
                            <CheckCircle2 className="w-3.5 h-3.5" /> Ready
                        </div>
                    )}
                    {isFailed && (
                        <div className="px-3 py-1.5 rounded-full bg-red-500/90 text-white backdrop-blur flex items-center gap-1.5 text-xs font-medium shadow-sm">
                            <AlertCircle className="w-3.5 h-3.5" /> Failed
                        </div>
                    )}
                </div>
            </div>

            {/* Content Body */}
            <div className="p-6 flex flex-col flex-1">
                <h3 className="font-serif text-lg font-semibold text-neutral-900 leading-snug mb-4 line-clamp-2">
                    {lesson.title ?? "Untitled Lesson"}
                </h3>

                <div className="mt-auto">
                    {isReady && (
                        <div className="text-sm font-medium text-emerald-600">Ready to watch</div>
                    )}
                    {isProcessing && (
                        <div className="flex items-center gap-2 text-sm font-medium text-[var(--accent-primary)]">
                            <div className="w-1.5 h-1.5 rounded-full bg-[var(--accent-primary)] animate-pulse" />
                            Synthesizing content...
                        </div>
                    )}
                    {isFailed && (
                        <div className="text-sm font-medium text-red-500">
                            Generation failed. Try uploading again.
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
