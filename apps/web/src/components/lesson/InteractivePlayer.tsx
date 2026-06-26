// MOCK DEMO ONLY — DO NOT IMPORT OR EXTEND THIS FILE IN SPRINT 1+
// Uses MockLesson types (timeline[], slide.content) which are incompatible with the
// frozen LessonPackage contract (narration.timestamps[], slide.bullets[]).
// Replace with: PlayerLoader → Player → Zustand player.machine (S1-01 through S1-06).
"use client";

import { MockLesson, Slide, TimelineEvent, SlideChangeEvent, QuizEvent, TeachbackEvent, InterventionEvent } from "@/mocks/data/lessons";
import { JargonHover } from "@/components/player/JargonHover";
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
                <Link href="/dashboard" className="w-12 h-12 flex items-center justify-center rounded-2xl bg-white/5 border border-white/10 hover:bg-white/10 hover:border-white/20 hover:scale-105 text-neutral-400 hover:text-white transition-all shadow-sm">
                    <ArrowLeft className="w-5 h-5" />
                </Link>

                <div className="text-center bg-black/40 px-8 py-3 rounded-full border border-white/5 shadow-xl backdrop-blur-md">
                    <div className="text-[10px] font-bold text-[var(--accent-primary)] uppercase tracking-[0.2em] mb-1">
                        {initialLesson.chapterTitle}
                    </div>
                    <h2 className="text-sm font-semibold text-white tracking-wide">
                        {initialLesson.title}
                    </h2>
                </div>

                <button className="w-12 h-12 flex items-center justify-center rounded-2xl bg-white/5 border border-white/10 hover:bg-white/10 hover:border-white/20 hover:scale-105 text-neutral-400 hover:text-white transition-all shadow-sm">
                    <Volume2 className="w-5 h-5" />
                </button>
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
            <div className="h-36 px-8 flex flex-col justify-center border-t border-white/5 bg-black/60 shadow-[0_-20px_40px_rgba(0,0,0,0.5)] backdrop-blur-2xl z-20 relative">

                <div className="flex items-center gap-6 max-w-4xl w-full mx-auto">
                    <span className="text-xs font-semibold text-neutral-500 w-12 text-right tabular-nums">
                        {formatTime(currentTime)}
                    </span>

                    {/* Scrub Bar */}
                    <div className="flex-1 h-3 bg-neutral-900 border border-white/5 rounded-full cursor-pointer relative group overflow-hidden shadow-inner">
                        <div
                            className="absolute top-0 left-0 h-full bg-gradient-to-r from-[var(--accent-secondary)] to-[var(--accent-primary)] rounded-full transition-all duration-1000 ease-linear shadow-[0_0_15px_var(--accent-primary)]"
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

                    <span className="text-xs font-semibold text-neutral-600 w-12 tabular-nums">
                        {formatTime(initialLesson.durationSeconds)}
                    </span>
                </div>

                <div className="flex items-center justify-center gap-8 mt-6">
                    <button onClick={() => setCurrentTime(Math.max(0, currentTime - 10))} className="p-2 text-neutral-500 hover:text-white hover:-translate-x-1 transition-all">
                        <SkipBack className="w-5 h-5 fill-current" />
                    </button>

                    <div className="relative">
                        {!isPlaying && (
                            <div className="absolute inset-0 bg-[var(--accent-primary)] rounded-full blur-xl opacity-40 animate-pulse pointer-events-none" />
                        )}
                        <button
                            onClick={togglePlay}
                            className={`relative w-16 h-16 flex items-center justify-center rounded-full transition-all duration-300 hover:scale-[1.03] ${isPlaying ? 'bg-white/10 text-white border border-white/20 hover:bg-white/20 shadow-md' : 'bg-gradient-to-br from-[var(--accent-primary)] to-[var(--accent-secondary)] text-white shadow-[0_8px_30px_-5px_var(--accent-primary)]'}`}
                        >
                            {isPlaying ? <Pause className="w-6 h-6 fill-current" /> : <Play className="w-7 h-7 fill-current ml-1.5" />}
                        </button>
                    </div>

                    <button onClick={() => setCurrentTime(Math.min(initialLesson.durationSeconds, currentTime + 10))} className="p-2 text-neutral-500 hover:text-white hover:translate-x-1 transition-all">
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
            initial={{ opacity: 0, scale: 0.96, y: 10, filter: "blur(10px)" }}
            animate={{ opacity: 1, scale: 1, y: 0, filter: "blur(0px)" }}
            exit={{ opacity: 0, scale: 1.02, y: -10, filter: "blur(10px)" }}
            transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
            className="w-full max-w-5xl"
        >
            <div className="bg-black/40 backdrop-blur-3xl border border-white/5 rounded-[2.5rem] p-16 md:p-24 shadow-[0_20px_100px_-10px_rgba(0,0,0,0.8)] relative overflow-hidden group">
                {/* Glow Effects */}
                <div className="absolute top-0 right-0 w-[600px] h-[600px] bg-[var(--accent-primary)]/10 rounded-full blur-[140px] -translate-y-1/2 translate-x-1/3 pointer-events-none group-hover:bg-[var(--accent-primary)]/15 transition-all duration-1000" />
                <div className="absolute bottom-0 left-0 w-80 h-80 bg-[var(--accent-secondary)]/10 rounded-full blur-[100px] translate-y-1/2 -translate-x-1/4 pointer-events-none group-hover:bg-[var(--accent-secondary)]/15 transition-all duration-1000" />

                <h1 className="text-4xl md:text-5xl lg:text-6xl font-extrabold text-white mb-8 leading-[1.1] tracking-tight max-w-4xl drop-shadow-md">
                    {slide.title}
                </h1>
                <div className="text-xl md:text-2xl lg:text-3xl text-neutral-300/90 leading-relaxed max-w-4xl font-medium tracking-wide">
                    <JargonHover text={slide.content} jargon={[]} />
                </div>
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
