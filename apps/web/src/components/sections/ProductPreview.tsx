"use client";

import { motion } from "framer-motion";
import {
    Brain,
    CheckCircle,
    Sparkles,
    Clock,
    BookOpen,
    TrendingUp,
} from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

function RealtimeWhiteboardVisual() {
    // 0 = Chaos, 1 = Collapse & Emerge, 2 = Branching
    const [phase, setPhase] = useState(0);

    useEffect(() => {
        let timeoutId: NodeJS.Timeout;
        if (phase === 0) {
            timeoutId = setTimeout(() => setPhase(1), 3500); // Chaos lasts 3.5s
        } else if (phase === 1) {
            timeoutId = setTimeout(() => setPhase(2), 1200); // Collapse/Emerge takes 1.2s
        } else if (phase === 2) {
            timeoutId = setTimeout(() => setPhase(0), 5000); // Structured phase lasts 5s
        }
        return () => clearTimeout(timeoutId);
    }, [phase]);

    // Words scattered around before they collapse
    const chaosWords = [
        { text: "chapter", x: -100, y: -120 },
        { text: "important", x: 180, y: -80 },
        { text: "research", x: -80, y: 130 },
        { text: "definition", x: 140, y: 100 },
        { text: "formula", x: 60, y: -140 },
        { text: "concept", x: -150, y: 20 },
        { text: "summary", x: 220, y: 30 }
    ];

    return (
        <div className="relative w-full h-[350px] lg:h-[450px] flex items-center justify-center pointer-events-none">

            {/* The central anchor point for the "Key Idea". Set to Left 25% / Top 50% */}
            <div className="absolute left-[25%] top-[50%] w-0 h-0">

                {/* --- STATE 0: Chaos Floating Phrases --- */}
                {chaosWords.map((word, i) => (
                    <motion.div
                        key={i}
                        className="absolute text-[12px] font-mono whitespace-nowrap px-2.5 py-1 bg-white/60 border border-slate-200/50 backdrop-blur-sm rounded-md text-slate-500 shadow-sm"
                        initial={{ opacity: 0, x: 0, y: 0, scale: 0.5, filter: "blur(4px)" }}
                        animate={
                            phase === 0
                                ? {
                                    opacity: [0, 0.8, 0.8],
                                    x: [0, word.x, word.x],
                                    y: [0, word.y - 10, word.y + (i % 2 === 0 ? 5 : -5)],
                                    scale: [0.5, 1, 1],
                                    filter: ["blur(4px)", "blur(0px)", "blur(0px)"]
                                }
                                : {
                                    opacity: 0,
                                    x: 0,
                                    y: 0,
                                    scale: 0,
                                    filter: "blur(4px)"
                                }
                        }
                        transition={{
                            duration: phase === 0 ? 3.5 : 0.8,
                            ease: phase === 0 ? "easeOut" : "backIn",
                            times: phase === 0 ? [0, 0.4, 1] : undefined
                        }}
                        style={{ marginLeft: '-50%', marginTop: '-10px' }} // Center the text approximately
                    >
                        {word.text}
                    </motion.div>
                ))}

                {/* --- STATE 1 & 2: Core "Key Idea" --- */}
                {/* Background pulse for main center node */}
                <motion.div
                    className="absolute -inset-16 bg-primary/10 rounded-full blur-2xl"
                    animate={{
                        opacity: phase >= 1 ? 1 : 0,
                        scale: phase === 2 ? [1, 1.2, 1] : 0.5
                    }}
                    transition={{
                        scale: { duration: 3, repeat: Infinity, ease: "easeInOut" },
                        opacity: { duration: 0.5 }
                    }}
                />

                <motion.div
                    className="absolute flex items-center justify-center whitespace-nowrap z-30"
                    initial={{ scale: 0, opacity: 0 }}
                    animate={{
                        scale: phase >= 1 ? 1 : 0,
                        opacity: phase >= 1 ? 1 : 0
                    }}
                    transition={{ type: "spring", stiffness: 200, damping: 15, delay: phase === 1 ? 0.3 : 0 }}
                    style={{ left: '-50px', top: '-15px' }} // Approximate centering for the text block
                >
                    {/* Handwritten circle SVG effect behind text */}
                    <svg className="absolute w-[180px] h-[70px] pointer-events-none -left-[30px] -top-3" viewBox="0 0 100 50" preserveAspectRatio="none">
                        <motion.path
                            d="M 50 5 C 80 5 95 20 95 25 C 95 40 80 45 50 45 C 20 45 5 40 5 25 C 5 10 20 5 45 6"
                            fill="none"
                            stroke="#3b82f6"
                            strokeWidth="1.5"
                            strokeLinecap="round"
                            strokeDasharray="6 4"
                            initial={{ pathLength: 0, opacity: 0 }}
                            animate={{
                                pathLength: phase >= 1 ? 1 : 0,
                                opacity: phase >= 1 ? 0.8 : 0
                            }}
                            transition={{ duration: 1, ease: "easeOut", delay: phase === 1 ? 0.5 : 0 }}
                        />
                    </svg>

                    <div className="flex flex-col items-center">
                        <span className="text-[17px] font-serif font-semibold text-slate-800">Key Idea</span>
                        <span className="text-[11px] text-primary uppercase font-bold tracking-widest mt-0.5">Foundational</span>
                    </div>
                </motion.div>


                {/* --- STATE 2: Branches (The Study Tree) --- */}
                {/* SVG Connections Container */}
                <div className="absolute z-10 w-[500px] h-[500px] pointer-events-none" style={{ left: '0px', top: '-250px' }}>
                    <svg className="absolute inset-0 w-full h-full" viewBox="0 0 500 500">
                        {/* Smooth connector paths to the 4 nodes */}
                        {/* Simple Explanation */}
                        <motion.path d="M 40 250 Q 80 250 100 130 T 200 130" stroke="#cbd5e1" strokeWidth="1.5" fill="none" initial={{ pathLength: 0 }} animate={{ pathLength: phase === 2 ? 1 : 0 }} transition={{ duration: 0.8 }} />
                        {/* Real Example */}
                        <motion.path d="M 40 250 Q 120 250 120 210 T 200 210" stroke="#cbd5e1" strokeWidth="1.5" fill="none" initial={{ pathLength: 0 }} animate={{ pathLength: phase === 2 ? 1 : 0 }} transition={{ duration: 0.8, delay: 0.2 }} />
                        {/* Practice Question */}
                        <motion.path d="M 40 250 Q 120 250 120 290 T 200 290" stroke="#cbd5e1" strokeWidth="1.5" fill="none" initial={{ pathLength: 0 }} animate={{ pathLength: phase === 2 ? 1 : 0 }} transition={{ duration: 0.8, delay: 0.4 }} />
                        {/* Summary */}
                        <motion.path d="M 40 250 Q 80 250 100 370 T 200 370" stroke="#cbd5e1" strokeWidth="1.5" fill="none" initial={{ pathLength: 0 }} animate={{ pathLength: phase === 2 ? 1 : 0 }} transition={{ duration: 0.8, delay: 0.6 }} />
                    </svg>
                </div>

                {/* The 4 Learning Branches Nodes */}
                {[
                    { label: "Simple Explanation", y: -120, delay: 0.3 },
                    { label: "Real Example", y: -40, delay: 0.5 },
                    { label: "Practice Question", y: 40, delay: 0.7 },
                    { label: "Summary", y: 120, delay: 0.9 },
                ].map((item, i) => (
                    <motion.div
                        key={i}
                        className="absolute left-[210px] whitespace-nowrap z-20 flex items-center gap-3"
                        initial={{ opacity: 0, x: -10 }}
                        animate={{
                            opacity: phase === 2 ? 1 : 0,
                            x: phase === 2 ? 0 : -10
                        }}
                        transition={{ duration: 0.6, ease: "easeOut", delay: phase === 2 ? item.delay : 0 }}
                        style={{ top: `${item.y}px`, marginTop: '-12px' }}
                    >
                        <div className="w-2 h-2 rounded-full border-2 border-primary bg-white z-10" />
                        <span className="text-[14px] font-medium text-slate-700">{item.label}</span>
                    </motion.div>
                ))}

            </div>
        </div>
    );
}

export default function ProductPreview() {
    return (
        <section className="py-20 lg:py-28 bg-white overflow-hidden">
            <div className="max-w-6xl mx-auto px-6 lg:px-8">
                {/* Header */}
                <motion.div
                    initial={{ opacity: 0, y: 16 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    viewport={{ once: true, margin: "-80px" }}
                    transition={{ duration: 0.4 }}
                    className="text-center max-w-2xl mx-auto mb-16"
                >
                    <h2 className="text-3xl sm:text-[2.25rem] font-serif font-semibold text-foreground tracking-tight leading-tight mb-3">
                        What a lesson actually looks like
                    </h2>
                    <p className="text-text-secondary text-[1.05rem]">
                        Not mockups. This is the real experience.
                    </p>
                </motion.div>

                <div className="space-y-6">
                    {/* Large block: AI Tutor + Visual side by side */}
                    <motion.div
                        initial={{ opacity: 0, y: 20 }}
                        whileInView={{ opacity: 1, y: 0 }}
                        viewport={{ once: true, margin: "-40px" }}
                        transition={{ duration: 0.5 }}
                        className="bg-[#f8fafc]/50 backdrop-blur-md rounded-3xl border border-[#e8eef3] p-6 lg:p-10"
                    >
                        <div className="grid lg:grid-cols-[1.1fr_1fr] gap-4 lg:gap-10 items-center">
                            {/* Left: Chat flow */}
                            <div className="relative z-10">
                                <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-8 flex items-center gap-2">
                                    <Sparkles className="w-4 h-4 text-primary" />
                                    AI Tutor in action
                                </p>
                                <div className="space-y-5">
                                    {/* AI */}
                                    <div className="flex gap-3.5">
                                        <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 border border-primary/20 mt-1">
                                            <Brain className="w-4 h-4 text-primary" />
                                        </div>
                                        <div className="bg-white rounded-2xl rounded-tl-sm px-5 py-4 text-[0.9rem] text-slate-700 leading-relaxed border border-[#e2e8f0] shadow-sm">
                                            This document is incredibly dense, but there&apos;s a pattern here. Let&apos;s pull out the noise and look at the core structure. What do you notice about how these main concepts connect?
                                        </div>
                                    </div>
                                    {/* Student */}
                                    <div className="flex gap-3.5 justify-end">
                                        <div className="bg-primary rounded-2xl rounded-tr-sm px-5 py-4 text-[0.9rem] text-white leading-relaxed max-w-md shadow-md">
                                            It seems like they all build off that first foundational idea?
                                        </div>
                                    </div>
                                    {/* AI follow-up */}
                                    <div className="flex gap-3.5">
                                        <div className="w-8 h-8 rounded-lg bg-emerald-50 flex items-center justify-center shrink-0 border border-emerald-100 mt-1">
                                            <CheckCircle className="w-4 h-4 text-emerald-600" />
                                        </div>
                                        <div className="bg-white rounded-2xl rounded-tl-sm px-5 py-4 text-[0.9rem] text-slate-700 leading-relaxed border border-[#e2e8f0] max-w-md shadow-sm">
                                            Exactly. When you map it out visually, it&apos;s so much easier to remember. Let&apos;s try applying this framework to the next chapter.
                                        </div>
                                    </div>
                                </div>
                            </div>

                            {/* Right: The Live Concept Graph */}
                            <div className="h-full w-full relative">
                                <RealtimeWhiteboardVisual />
                            </div>
                        </div>
                    </motion.div>

                    {/* Three smaller cards bottom row */}
                    <div className="grid sm:grid-cols-3 gap-6">
                        <motion.div
                            initial={{ opacity: 0, y: 16 }}
                            whileInView={{ opacity: 1, y: 0 }}
                            viewport={{ once: true, margin: "-40px" }}
                            transition={{ duration: 0.4, delay: 0.05 }}
                            className="bg-white rounded-2xl border border-[#e8eef3] p-6 lg:p-7 shadow-sm"
                        >
                            <div className="flex items-center gap-2 mb-5">
                                <BookOpen className="w-4 h-4 text-primary" />
                                <span className="text-[13px] font-bold text-foreground">Lesson Progress</span>
                            </div>
                            <div className="space-y-3.5">
                                {["Foundational concepts", "Core mechanisms", "Practical applications", "Advanced synthesis"].map(
                                    (item, i) => (
                                        <div key={item} className="flex items-center gap-2.5 text-[13px]">
                                            <CheckCircle
                                                className={`w-4 h-4 ${i < 2 ? "text-emerald-500" : "text-[#d4d4d8]"}`}
                                            />
                                            <span
                                                className={
                                                    i < 2 ? "text-text-muted line-through" : i === 2 ? "text-primary font-bold" : "text-text-secondary"
                                                }
                                            >
                                                {item}
                                            </span>
                                        </div>
                                    )
                                )}
                            </div>
                        </motion.div>

                        <motion.div
                            initial={{ opacity: 0, y: 16 }}
                            whileInView={{ opacity: 1, y: 0 }}
                            viewport={{ once: true, margin: "-40px" }}
                            transition={{ duration: 0.4, delay: 0.1 }}
                            className="bg-white rounded-2xl border border-[#e8eef3] p-6 lg:p-7 shadow-sm"
                        >
                            <div className="flex items-center gap-2 mb-5">
                                <TrendingUp className="w-4 h-4 text-emerald-600" />
                                <span className="text-[13px] font-bold text-foreground">Your Stats</span>
                            </div>
                            <div className="grid grid-cols-2 gap-3 pb-1">
                                {[
                                    { val: "78%", lbl: "Mastery" },
                                    { val: "5", lbl: "Day streak" },
                                    { val: "4.2h", lbl: "This week" },
                                    { val: "23", lbl: "Concepts" },
                                ].map(({ val, lbl }) => (
                                    <div key={lbl} className="text-center py-2.5 bg-slate-50/50 rounded-xl border border-[#f0f0f0] shadow-sm">
                                        <p className="text-[17px] font-bold text-foreground">{val}</p>
                                        <p className="text-[10px] uppercase tracking-wider font-semibold text-text-muted mt-0.5">{lbl}</p>
                                    </div>
                                ))}
                            </div>
                        </motion.div>

                        <motion.div
                            initial={{ opacity: 0, y: 16 }}
                            whileInView={{ opacity: 1, y: 0 }}
                            viewport={{ once: true, margin: "-40px" }}
                            transition={{ duration: 0.4, delay: 0.15 }}
                            className="bg-white rounded-2xl border border-[#e8eef3] p-6 lg:p-7 shadow-sm"
                        >
                            <div className="flex items-center gap-2 mb-4">
                                <Clock className="w-4 h-4 text-amber-600" />
                                <span className="text-[13px] font-bold text-foreground">Quick Quiz</span>
                            </div>
                            <p className="text-[13px] text-foreground mb-4 leading-relaxed font-medium">
                                Which learning step consolidates multiple ideas into one overarching theme?
                            </p>
                            <div className="space-y-2">
                                {["Review", "Synthesis", "Analysis"].map((opt, i) => (
                                    <div
                                        key={opt}
                                        className={`px-4 py-2.5 rounded-xl text-[13px] border transition-colors ${i === 1
                                            ? "border-emerald-200 bg-emerald-50 text-emerald-700 font-bold"
                                            : "border-[#e8eef3] bg-white text-text-secondary"
                                            }`}
                                    >
                                        {opt}
                                    </div>
                                ))}
                            </div>
                        </motion.div>
                    </div>
                </div>
            </div>
        </section>
    );
}
