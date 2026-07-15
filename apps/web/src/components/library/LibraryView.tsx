"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Play, CheckCircle2, AlertCircle, RefreshCw, LayoutGrid } from "lucide-react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { formatTimeAgo, formatLessonStatusLabel } from "@/lib/utils";
import type { LibraryData } from "@/services/library.service";
import type { LessonStatusResponse } from "@/services/upload.service";

const PAGE_SIZE = 24;

interface LibraryViewProps {
    initialData: LibraryData;
}

type TabKey = 'all' | 'generating' | 'ready' | 'failed';

function isGenerating(lesson: LessonStatusResponse): boolean {
    return lesson.status === 'queued' || lesson.status === 'running';
}

export function LibraryView({ initialData }: LibraryViewProps) {
    const router = useRouter();
    const [activeTab, setActiveTab] = useState<TabKey>('all');
    const [lessons, setLessons] = useState<LessonStatusResponse[]>(initialData.lessons);
    const [hasMore, setHasMore] = useState(initialData.lessons.length === PAGE_SIZE);
    const [loadingMore, setLoadingMore] = useState(false);

    const getFilteredLessons = (): LessonStatusResponse[] => {
        if (activeTab === 'all') return lessons;
        if (activeTab === 'generating') return lessons.filter(isGenerating);
        if (activeTab === 'ready') return lessons.filter((l) => l.status === 'ready');
        if (activeTab === 'failed') return lessons.filter((l) => l.status === 'failed');
        return [];
    };

    const filteredLessons = getFilteredLessons();

    const tabs: { key: TabKey; label: string; count: number }[] = [
        { key: 'all', label: 'All Lessons', count: lessons.length },
        { key: 'generating', label: 'Generating', count: lessons.filter(isGenerating).length },
        { key: 'ready', label: 'Ready', count: lessons.filter((l) => l.status === 'ready').length },
        { key: 'failed', label: 'Failed', count: lessons.filter((l) => l.status === 'failed').length },
    ];

    const handleLoadMore = async () => {
        setLoadingMore(true);
        try {
            const { data } = await api.get<LessonStatusResponse[]>('content/lessons', {
                params: { limit: PAGE_SIZE, offset: lessons.length },
            });
            setLessons((prev) => [...prev, ...data]);
            setHasMore(data.length === PAGE_SIZE);
        } finally {
            setLoadingMore(false);
        }
    };

    if (lessons.length === 0) {
        return (
            <div className="col-span-full h-64 flex flex-col items-center justify-center text-neutral-400 border-2 border-dashed border-neutral-200 rounded-3xl">
                <LayoutGrid className="w-8 h-8 mb-4 text-neutral-300" />
                <p className="mb-4">No lessons yet — upload your first PDF to get started.</p>
                <Button variant="primary" size="sm" onClick={() => router.push('/upload')}>
                    Upload a PDF
                </Button>
            </div>
        );
    }

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
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 pb-12">
                <AnimatePresence mode="popLayout">
                    {filteredLessons.map((lesson, idx) => (
                        <LibraryCard
                            key={lesson.lesson_id}
                            lesson={lesson}
                            onNavigateToLesson={() => router.push(`/lesson/${lesson.lesson_id}`)}
                            index={idx}
                        />
                    ))}
                    {filteredLessons.length === 0 && (
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

            {hasMore && (
                <div className="flex justify-center pb-24">
                    <Button variant="outline" size="md" onClick={handleLoadMore} disabled={loadingMore}>
                        {loadingMore ? 'Loading...' : 'Load more'}
                    </Button>
                </div>
            )}
        </div>
    );
}

function LibraryCard({ lesson, onNavigateToLesson, index }: { lesson: LessonStatusResponse, onNavigateToLesson: () => void, index: number }) {
    const router = useRouter();
    const generating = isGenerating(lesson);
    const isFailed = lesson.status === 'failed';
    const isReady = lesson.status === 'ready';

    return (
        <motion.div
            layout
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.4, ease: "easeOut", delay: index * 0.05 }}
            onClick={isReady ? onNavigateToLesson : undefined}
            className={`group relative w-full bg-white rounded-3xl border border-neutral-100 shadow-sm transition-all duration-300 flex flex-col overflow-hidden p-6 ${isReady ? 'cursor-pointer hover:shadow-xl hover:-translate-y-1' : 'opacity-90 cursor-default'
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
            </div>

            <h3 className="font-serif text-lg font-semibold text-neutral-900 leading-snug mb-2 line-clamp-2">
                {lesson.title ?? 'Untitled Lesson'}
            </h3>

            <div className="mt-auto text-xs font-medium text-neutral-400">
                {lesson.created_at && <span>Created {formatTimeAgo(lesson.created_at)}</span>}
            </div>

            {isFailed && (
                <div className="mt-3">
                    <p className="text-sm font-medium text-red-500 mb-3">
                        {lesson.error ?? 'Generation failed — please try again.'}
                    </p>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={(e) => {
                            e.stopPropagation();
                            router.push('/upload');
                        }}
                    >
                        Upload Again
                    </Button>
                </div>
            )}

            {isReady && (
                <div className="absolute inset-0 z-20 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none">
                    <div className="w-14 h-14 rounded-full bg-neutral-900/10 backdrop-blur-md flex items-center justify-center text-neutral-900 border border-neutral-900/10 shadow-xl">
                        <Play className="w-6 h-6 fill-current ml-1" />
                    </div>
                </div>
            )}
        </motion.div>
    );
}
