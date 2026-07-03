"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { MockLesson } from "@/mocks/data/lessons";
import { LibraryData } from "@/mocks/api/library";
import { Play, CheckCircle2, Clock, AlertCircle, RefreshCw, LayoutGrid } from "lucide-react";
import { useRouter } from "next/navigation";

interface LibraryViewProps {
    initialData: LibraryData;
}

type TabKey = 'all' | 'in_progress' | 'completed' | 'processing';

export function LibraryView({ initialData }: LibraryViewProps) {
    const router = useRouter();
    const [activeTab, setActiveTab] = useState<TabKey>('all');

    // Aggregate all lessons
    const allLessons = [
        ...initialData.inProgress,
        ...initialData.completed,
        ...initialData.processing,
        ...initialData.failed
    ];

    // Filter Logic
    const getFilteredLessons = (): MockLesson[] => {
        if (activeTab === 'all') return allLessons;
        if (activeTab === 'in_progress') return initialData.inProgress;
        if (activeTab === 'completed') return initialData.completed;
        if (activeTab === 'processing') return initialData.processing;
        return [];
    };

    const lessons = getFilteredLessons();

    const tabs: { key: TabKey, label: string, count: number }[] = [
        { key: 'all', label: 'All Lessons', count: allLessons.length },
        { key: 'in_progress', label: 'In Progress', count: initialData.inProgress.length },
        { key: 'completed', label: 'Completed', count: initialData.completed.length },
        { key: 'processing', label: 'Processing', count: initialData.processing.length }
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
                        <LibraryCard
                            key={lesson.id}
                            lesson={lesson}
                            onClick={() => router.push(`/lesson/${lesson.id}`)}
                            index={idx}
                        />
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

function LibraryCard({ lesson, onClick, index }: { lesson: MockLesson, onClick: () => void, index: number }) {
    // Generate deterministic placeholder
    const thumbnails = [
        "https://images.unsplash.com/photo-1555949963-aa79dcee981c?auto=format&fit=crop&q=80&w=600&h=400",
        "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&q=80&w=600&h=400",
        "https://images.unsplash.com/photo-1605745341112-85968b19335b?auto=format&fit=crop&q=80&w=600&h=400",
        "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?auto=format&fit=crop&q=80&w=600&h=400"
    ];
    const image = thumbnails[parseInt(lesson.id.replace(/\D/g, '') || '0') % thumbnails.length];

    const isProcessing = lesson.status === 'processing';
    const isFailed = lesson.status === 'failed';
    const isCompleted = lesson.status === 'completed';

    return (
        <motion.div
            layout
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.4, ease: "easeOut", delay: index * 0.05 }}
            onClick={!isProcessing && !isFailed ? onClick : undefined}
            className={`group relative w-full bg-white rounded-3xl border border-neutral-100 shadow-sm transition-all duration-300 flex flex-col overflow-hidden ${isProcessing || isFailed ? 'opacity-80 cursor-default' : 'cursor-pointer hover:shadow-xl hover:-translate-y-1'
                }`}
        >
            {/* Thumbnail Header */}
            <div className="relative w-full h-44 overflow-hidden bg-neutral-100 shrink-0">
                {!isProcessing && !isFailed && (
                    <img
                        src={image}
                        alt={lesson.title}
                        className="w-full h-full object-cover transform group-hover:scale-105 transition-transform duration-700 ease-out"
                    />
                )}

                {/* Status Overlays */}
                <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/0 to-black/0 pointer-events-none" />

                <div className="absolute top-4 right-4 flex items-center gap-2">
                    {isProcessing && (
                        <div className="px-3 py-1.5 rounded-full bg-[var(--accent-primary)]/90 text-white backdrop-blur flex items-center gap-1.5 text-xs font-medium shadow-sm">
                            <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Processing
                        </div>
                    )}
                    {isCompleted && (
                        <div className="px-3 py-1.5 rounded-full bg-emerald-500/90 text-white backdrop-blur flex items-center gap-1.5 text-xs font-medium shadow-sm">
                            <CheckCircle2 className="w-3.5 h-3.5" /> Completed
                        </div>
                    )}
                    {isFailed && (
                        <div className="px-3 py-1.5 rounded-full bg-red-500/90 text-white backdrop-blur flex items-center gap-1.5 text-xs font-medium shadow-sm">
                            <AlertCircle className="w-3.5 h-3.5" /> Failed
                        </div>
                    )}
                </div>

                {!isProcessing && !isFailed && (
                    <div className="absolute inset-0 z-20 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-300">
                        <div className="w-14 h-14 rounded-full bg-white/30 backdrop-blur-md flex items-center justify-center text-white border border-white/40 shadow-xl">
                            <Play className="w-6 h-6 fill-current ml-1" />
                        </div>
                    </div>
                )}
            </div>

            {/* Content Body */}
            <div className="p-6 flex flex-col flex-1">
                <div className="text-xs font-bold text-[var(--accent-primary)] mb-2 uppercase tracking-wide">
                    {lesson.chapterTitle}
                </div>
                <h3 className="font-serif text-lg font-semibold text-neutral-900 leading-snug mb-4 line-clamp-2">
                    {lesson.title}
                </h3>

                <div className="mt-auto">
                    {/* Progress representation */}
                    {!isProcessing && !isFailed && (
                        <>
                            <div className="relative w-full h-1.5 bg-neutral-100 rounded-full overflow-hidden mb-3">
                                <motion.div
                                    initial={{ width: 0 }}
                                    animate={{ width: `${lesson.progressPercent}%` }}
                                    transition={{ duration: 1, ease: "easeOut" }}
                                    className={`absolute top-0 left-0 h-full rounded-full ${isCompleted ? 'bg-emerald-500' : 'bg-[var(--accent-primary)]'}`}
                                />
                            </div>
                            <div className="flex items-center justify-between text-xs font-medium text-neutral-400">
                                <span>{lesson.progressPercent}% finished</span>
                                <span className="flex items-center gap-1.5">
                                    <Clock className="w-3.5 h-3.5" />
                                    {Math.ceil(lesson.durationSeconds / 60)}m
                                </span>
                            </div>
                        </>
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
        </motion.div>
    );
}
