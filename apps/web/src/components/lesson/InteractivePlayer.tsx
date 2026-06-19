"use client";

import { MockLesson, Slide, TimelineEvent, SlideChangeEvent, QuizEvent, TeachbackEvent, InterventionEvent } from "@/mocks/data/lessons";
import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Play, Pause, ArrowLeft, Volume2, SkipBack, SkipForward, Mic, CheckCircle, ChevronRight, Zap } from "lucide-react";
import Link from "next/link";

interface InteractivePlayerProps {
    initialLesson: MockLesson;
}

export function InteractivePlayer({ initialLesson }: InteractivePlayerProps) {
    const [isPlaying, setIsPlaying] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const [activeSlide, setActiveSlide] = useState<Slide | null>(
        initialLesson.slides.length > 0 ? initialLesson.slides[0] : null
    );
    const [activeIntervention, setActiveIntervention] = useState<TimelineEvent | null>(null);

    // Audio Timeline Loop (1 tick = 1 virtual second)
    // We speed it up slightly (e.g. 500ms real time = 1s virtual) to make demos brisker, 
    // or keep it 1000ms. Let's use 1000ms for accurate display.
    useEffect(() => {
        if (!isPlaying || activeIntervention) return;

        const interval = setInterval(() => {
            setCurrentTime(prev => {
                const nextTime = prev + 1;
                if (nextTime >= initialLesson.durationSeconds) {
                    setIsPlaying(false);
                    return initialLesson.durationSeconds;
                }
                return nextTime;
            });
        }, 1000); // 1 real second

        return () => clearInterval(interval);
    }, [isPlaying, activeIntervention, initialLesson.durationSeconds]);

    // Timeline Engine: resolve active slide and popup interventions
    useEffect(() => {
        const sortedEvents = [...initialLesson.timeline].sort((a, b) => a.timestamp - b.timestamp);

        // 1. Resolve active slide
        const pastSlideEvents = sortedEvents.filter(e => e.type === 'slide_change' && e.timestamp <= currentTime) as SlideChangeEvent[];
        if (pastSlideEvents.length > 0) {
            const latest = pastSlideEvents[pastSlideEvents.length - 1];
            const slide = initialLesson.slides.find(s => s.id === latest.slideId);
            if (slide && slide.id !== activeSlide?.id) {
                setActiveSlide(slide);
            }
        }

        // 2. Resolve Active Interventions (Quiz/Teachback/Pause)
        // If an intervention exactly matches the current timestamp, and we haven't popped it yet
        const immediateIntervention = sortedEvents.find(e => e.type !== 'slide_change' && e.timestamp === currentTime);

        if (immediateIntervention && !activeIntervention) {
            // Auto-pause and pop intervention
            setIsPlaying(false);
            setActiveIntervention(immediateIntervention);
        }
    }, [currentTime, initialLesson.timeline, initialLesson.slides, activeSlide?.id, activeIntervention]);

    const formatTime = (seconds: number) => {
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
    };

    const handleDismissIntervention = () => {
        setActiveIntervention(null);
        // Step time forward by 1 tick so it doesn't immediately re-trigger the same intervention
        setCurrentTime(prev => prev + 1);
        setIsPlaying(true);
    };

    const togglePlay = () => {
        // If we are at the end, restart
        if (currentTime >= initialLesson.durationSeconds) {
            setCurrentTime(0);
            setIsPlaying(true);
        } else {
            setIsPlaying(!isPlaying);
        }
    }

    const progressPercent = (currentTime / initialLesson.durationSeconds) * 100;

    return (
        <div className="w-full h-full flex flex-col pt-8">
            {/* Top Bar Navigation */}
            <div className="px-8 flex items-center justify-between z-20">
                <Link href="/dashboard" className="w-12 h-12 flex items-center justify-center rounded-full bg-neutral-900 border border-neutral-800 text-neutral-400 hover:text-white hover:bg-neutral-800 transition-colors">
                    <ArrowLeft className="w-5 h-5" />
                </Link>

                <div className="text-center">
                    <div className="text-xs font-semibold text-[var(--accent-primary)] uppercase tracking-wider mb-1">
                        {initialLesson.chapterTitle}
                    </div>
                    <h2 className="text-xl font-semibold text-white">
                        {initialLesson.title}
                    </h2>
                </div>

                <div className="w-12 h-12 flex items-center justify-center rounded-full bg-neutral-900 border border-neutral-800 text-neutral-400">
                    <Volume2 className="w-5 h-5" />
                </div>
            </div>

            {/* Center Stage Presentation */}
            <div className="flex-1 relative flex items-center justify-center p-8 overflow-hidden">
                {/* Background Ambient Glows */}
                <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-[var(--accent-primary)]/10 rounded-full blur-[120px] pointer-events-none" />

                <AnimatePresence mode="wait">
                    {activeIntervention ? (
                        <InterventionLayer
                            key={`int-${activeIntervention.id}`}
                            event={activeIntervention}
                            onComplete={handleDismissIntervention}
                        />
                    ) : (
                        <SlideLayer
                            key={`slide-${activeSlide?.id || 'empty'}`}
                            slide={activeSlide}
                        />
                    )}
                </AnimatePresence>
            </div>

            {/* Bottom Audio Controller */}
            <div className="h-32 px-8 flex flex-col justify-center border-t border-neutral-800/50 bg-neutral-900/50 backdrop-blur-xl z-20 relative">

                <div className="flex items-center gap-6 max-w-4xl w-full mx-auto">
                    <span className="text-xs font-medium text-neutral-400 w-12 text-right tabular-nums">
                        {formatTime(currentTime)}
                    </span>

                    {/* Scrub Bar */}
                    <div className="flex-1 h-2 bg-neutral-800 rounded-full cursor-pointer relative group">
                        <div
                            className="absolute top-0 left-0 h-full bg-[var(--accent-primary)] rounded-full transition-all duration-1000 ease-linear"
                            style={{ width: `${progressPercent}%` }}
                        />
                        {/* Interactive timeline markers for interventions */}
                        {initialLesson.timeline.filter(e => e.type !== 'slide_change').map(event => (
                            <div
                                key={`marker-${event.id}`}
                                className="absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full bg-white border-2 border-[var(--accent-primary)] shadow-[0_0_10px_var(--accent-primary)] z-10"
                                style={{ left: `${(event.timestamp / initialLesson.durationSeconds) * 100}%`, transform: 'translate(-50%, -50%)' }}
                            />
                        ))}
                    </div>

                    <span className="text-xs font-medium text-neutral-500 w-12 tabular-nums">
                        {formatTime(initialLesson.durationSeconds)}
                    </span>
                </div>

                <div className="flex items-center justify-center gap-6 mt-4">
                    <button onClick={() => setCurrentTime(Math.max(0, currentTime - 10))} className="text-neutral-500 hover:text-white transition-colors">
                        <SkipBack className="w-5 h-5 fill-current" />
                    </button>

                    <button
                        onClick={togglePlay}
                        className={`w-14 h-14 flex items-center justify-center rounded-full transition-all duration-300 ${isPlaying ? 'bg-white text-neutral-900 border border-white' : 'bg-[var(--accent-primary)] text-white shadow-[0_4px_20px_-4px_var(--accent-primary)]'}`}
                    >
                        {isPlaying ? <Pause className="w-6 h-6 fill-current" /> : <Play className="w-6 h-6 fill-current ml-1" />}
                    </button>

                    <button onClick={() => setCurrentTime(Math.min(initialLesson.durationSeconds, currentTime + 10))} className="text-neutral-500 hover:text-white transition-colors">
                        <SkipForward className="w-5 h-5 fill-current" />
                    </button>
                </div>
            </div>
        </div>
    );
}

function SlideLayer({ slide }: { slide: Slide | null }) {
    if (!slide) return <div className="text-neutral-500">Preparing presentation...</div>;

    return (
        <motion.div
            initial={{ opacity: 0, scale: 0.95, filter: "blur(10px)" }}
            animate={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
            exit={{ opacity: 0, scale: 1.05, filter: "blur(10px)" }}
            transition={{ duration: 0.7, ease: "easeOut" }}
            className="w-full max-w-5xl"
        >
            <div className="bg-neutral-900/60 backdrop-blur-3xl border border-white/10 rounded-[3rem] p-16 md:p-24 shadow-[0_0_100px_rgba(0,0,0,0.5)] relative overflow-hidden group">
                <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-[var(--accent-primary)]/10 rounded-full blur-[120px] -translate-y-1/2 translate-x-1/4 pointer-events-none group-hover:bg-[var(--accent-primary)]/20 transition-all duration-1000" />
                <div className="absolute bottom-0 left-0 w-64 h-64 bg-emerald-500/10 rounded-full blur-[100px] translate-y-1/2 -translate-x-1/4 pointer-events-none group-hover:bg-emerald-500/20 transition-all duration-1000" />

                <h1 className="text-4xl md:text-6xl font-extrabold text-transparent bg-clip-text bg-gradient-to-br from-white via-white to-neutral-500 mb-8 leading-tight tracking-tight">
                    {slide.title}
                </h1>
                <p className="text-xl md:text-3xl text-neutral-300 leading-relaxed max-w-3xl font-medium">
                    {slide.content}
                </p>
            </div>
        </motion.div>
    );
}

function InterventionLayer({ event, onComplete }: { event: TimelineEvent, onComplete: () => void }) {

    if (event.type === 'quiz') {
        const quiz = event as QuizEvent;
        const [selected, setSelected] = useState<number | null>(null);

        const handleSelect = (idx: number) => {
            setSelected(idx);
            // Simulate answer validation delay
            setTimeout(() => {
                onComplete();
            }, 1000);
        };

        return (
            <motion.div
                initial={{ opacity: 0, y: 40 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -40 }}
                className="w-full max-w-2xl bg-neutral-900 border border-[var(--accent-primary)]/50 shadow-[0_0_50px_rgba(var(--accent-primary-rgb),0.1)] rounded-[2.5rem] p-12 text-center relative overflow-hidden"
            >
                <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-[var(--accent-primary)] to-transparent" />

                <div className="w-16 h-16 bg-[var(--accent-primary)]/20 text-[var(--accent-primary)] rounded-full flex items-center justify-center mx-auto mb-6">
                    <Zap className="w-8 h-8" />
                </div>

                <h3 className="text-sm font-bold uppercase tracking-widest text-[var(--accent-primary)] mb-4">Knowledge Check</h3>
                <h2 className="text-2xl font-semibold text-white mb-8">{quiz.question}</h2>

                <div className="flex flex-col gap-3">
                    {quiz.options.map((opt, idx) => {
                        const isCorrect = idx === quiz.correctOptionIndex;
                        const isSelected = selected === idx;

                        let optStyle = "bg-neutral-800 border-neutral-700 hover:bg-neutral-700 text-neutral-300";
                        if (selected !== null) {
                            if (isSelected && isCorrect) optStyle = "bg-emerald-500/20 border-emerald-500 text-emerald-400";
                            if (isSelected && !isCorrect) optStyle = "bg-red-500/20 border-red-500 text-red-500";
                            if (!isSelected && isCorrect) optStyle = "bg-emerald-500/10 border-emerald-500 text-emerald-500 opactity-50";
                        }

                        return (
                            <button
                                key={idx}
                                disabled={selected !== null}
                                onClick={() => handleSelect(idx)}
                                className={`w-full p-4 rounded-2xl border transition-all duration-300 font-medium ${optStyle}`}
                            >
                                {opt}
                            </button>
                        );
                    })}
                </div>
            </motion.div>
        );
    }

    if (event.type === 'teachback') {
        const tb = event as TeachbackEvent;
        return (
            <motion.div
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, y: 20 }}
                className="w-full max-w-2xl bg-neutral-900 border border-purple-500/50 shadow-[0_0_50px_rgba(168,85,247,0.1)] rounded-[2.5rem] p-12 text-center"
            >
                <div className="w-16 h-16 bg-purple-500/20 text-purple-400 rounded-full flex items-center justify-center mx-auto mb-6">
                    <Mic className="w-8 h-8" />
                </div>
                <h3 className="text-sm font-bold uppercase tracking-widest text-purple-400 mb-4">Teachback Required</h3>
                <h2 className="text-2xl font-semibold text-white mb-8 leading-snug">"{tb.prompt}"</h2>

                <p className="text-neutral-500 mb-8">Speak your answer aloud to reinforce your understanding.</p>

                <button
                    onClick={onComplete}
                    className="w-full py-4 bg-purple-500 hover:bg-purple-600 text-white font-bold rounded-2xl transition-colors shadow-[0_4px_20px_-4px_rgba(168,85,247,0.5)] flex items-center justify-center gap-2"
                >
                    <CheckCircle className="w-5 h-5" /> I have explained it
                </button>
            </motion.div>
        );
    }

    if (event.type === 'intervention') {
        const int = event as InterventionEvent;
        return (
            <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="w-full max-w-xl bg-neutral-800 rounded-3xl p-8 text-center border border-neutral-700"
            >
                <h3 className="text-lg font-semibold text-white mb-2">Attention</h3>
                <p className="text-neutral-400 mb-6">{int.message}</p>
                <button onClick={onComplete} className="px-6 py-2 bg-white text-black font-semibold rounded-full hover:bg-neutral-200">
                    Continue Learning
                </button>
            </motion.div>
        );
    }

    return null;
}
