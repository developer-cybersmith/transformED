"use client";

import { useEffect, useMemo, useState, useRef } from "react";
import { motion, useScroll, useTransform } from "framer-motion";
import { ArrowRight, Play, Brain, BookOpen, CheckCircle } from "lucide-react";
import Link from "next/link";
import { AuroraBackground } from "@/components/ui/AuroraBackground";

export default function Hero() {
    const [titleNumber, setTitleNumber] = useState(0);
    const titles = useMemo(
        () => ["deep thinker.", "focused scholar.", "master learner.", "problem solver."],
        []
    );

    const containerRef = useRef<HTMLDivElement>(null);
    const { scrollYProgress } = useScroll({
        target: containerRef,
        offset: ["start start", "end start"]
    });

    const textY = useTransform(scrollYProgress, [0, 1], [0, 100]);
    const textOpacity = useTransform(scrollYProgress, [0, 0.8], [1, 0]);
    const mockupY = useTransform(scrollYProgress, [0, 1], [0, -80]);

    useEffect(() => {
        const timeoutId = setTimeout(() => {
            if (titleNumber === titles.length - 1) {
                setTitleNumber(0);
            } else {
                setTitleNumber(titleNumber + 1);
            }
        }, 2500);
        return () => clearTimeout(timeoutId);
    }, [titleNumber, titles]);

    return (
        <div ref={containerRef}>
            <AuroraBackground
                className="pt-32 pb-20 lg:pt-40 lg:pb-32 overflow-hidden"
                showRadialGradient={true}
            >
                <div className="relative max-w-7xl mx-auto px-6 lg:px-8 z-10 w-full">
                    <div className="grid lg:grid-cols-2 gap-16 lg:gap-24 items-center">
                        {/* Left — Copy */}
                        <motion.div style={{ y: textY, opacity: textOpacity }}>
                            <motion.div
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ duration: 0.6 }}
                            >
                                <h1 className="text-[2.75rem] sm:text-5xl lg:text-[3.2rem] font-extrabold tracking-tight leading-[1.15] text-foreground font-display mb-6 inline-block w-full">
                                    The end of passive learning.<br />
                                    <span className="text-primary">Become a </span>
                                    <span className="relative inline-flex overflow-hidden min-w-[370px] align-bottom">
                                        <span className="invisible">problem solver.</span>
                                        {titles.map((title, index) => (
                                            <motion.span
                                                key={index}
                                                className="absolute left-0 text-primary"
                                                initial={{ opacity: 0, y: "100%" }}
                                                transition={{ type: "spring", stiffness: 50 }}
                                                animate={
                                                    titleNumber === index
                                                        ? { y: 0, opacity: 1 }
                                                        : { y: titleNumber > index ? "-100%" : "100%", opacity: 0 }
                                                }
                                            >
                                                {title}
                                            </motion.span>
                                        ))}
                                    </span>
                                </h1>

                                <p className="text-[1.1rem] text-text-secondary leading-[1.75] max-w-lg mb-10">
                                    Human's attention span has been dropping due to modern technological advancements causing cognitive decline. HIE (Human Intelligence Engine) acts as an AI Tutor that monitors your IQ, EQ, SQ, and Critical Thinking to mature your analytical reasoning.
                                </p>

                                {/* CTA */}
                                <div className="flex flex-wrap items-center gap-4 mb-6">
                                    <motion.div
                                        whileHover={{ y: -2, boxShadow: "0 20px 40px -10px rgba(7,23,44,0.4)" }}
                                        whileTap={{ y: 1 }}
                                        transition={{ type: "spring", stiffness: 400, damping: 25 }}
                                        className="rounded-xl"
                                    >
                                        <Link
                                            href="/signup"
                                            className="group inline-flex items-center gap-2.5 px-7 py-3.5 text-[0.95rem] font-semibold text-white bg-primary rounded-xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_4px_16px_rgba(7,23,44,0.25)] transition-colors duration-150"
                                        >
                                            Try it free
                                            <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
                                        </Link>
                                    </motion.div>
                                    <motion.a
                                        href="#how-it-works"
                                        whileHover={{ x: 2, color: "#1e293b" }}
                                        transition={{ type: "spring", stiffness: 400, damping: 25 }}
                                        className="inline-flex items-center gap-2 px-5 py-3.5 text-[0.95rem] font-medium text-text-secondary transition-colors"
                                    >
                                        <Play className="w-4 h-4" />
                                        See how it works
                                    </motion.a>
                                </div>

                                {/* Trust layer */}
                                <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[0.85rem] text-text-muted font-medium">
                                    <span className="flex items-center gap-1.5"><CheckCircle className="w-3.5 h-3.5 text-emerald-500" /> Free to try</span>
                                    <span className="flex items-center gap-1.5"><CheckCircle className="w-3.5 h-3.5 text-emerald-500" /> Designed for deep learning</span>
                                    <span className="flex items-center gap-1.5"><CheckCircle className="w-3.5 h-3.5 text-emerald-500" /> No credit card</span>
                                </div>
                            </motion.div>
                        </motion.div>

                        {/* Right — Product Mockup */}
                        <motion.div style={{ y: mockupY }} className="relative z-10">
                            <motion.div
                                initial={{ opacity: 0, x: 30 }}
                                animate={{ opacity: 1, x: 0 }}
                                transition={{ duration: 0.7, delay: 0.15 }}
                                className="relative lg:ml-6 mt-10 lg:mt-0"
                            >
                                {/* Decorative glow behind mockup */}
                                <motion.div
                                    animate={{
                                        scale: [1, 1.05, 1],
                                        opacity: [0.6, 0.4, 0.6],
                                        rotate: [0, 5, -5, 0]
                                    }}
                                    transition={{
                                        duration: 18,
                                        repeat: Infinity,
                                        ease: "linear"
                                    }}
                                    className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[110%] h-[110%] bg-gradient-to-tr from-primary/15 to-[var(--accent-secondary)]/15 blur-3xl rounded-full z-0 pointer-events-none"
                                />

                                {/* Main lesson card */}
                                <motion.div
                                    className="bg-white/90 backdrop-blur-xl rounded-2xl border border-white shadow-[0_20px_60px_-15px_rgba(0,0,0,0.08),_0_0_40px_-10px_rgba(7,23,44,0.12)] overflow-hidden relative z-10"
                                >
                                    {/* Window chrome */}
                                    <div className="flex items-center justify-between px-5 py-3 border-b border-[#f1f5f9] bg-[#fafbfc]/50">
                                        <div className="flex items-center gap-2">
                                            <div className="flex gap-1.5">
                                                <div className="w-2.5 h-2.5 rounded-full bg-[#fca5a5]" />
                                                <div className="w-2.5 h-2.5 rounded-full bg-[#fde68a]" />
                                                <div className="w-2.5 h-2.5 rounded-full bg-[#86efac]" />
                                            </div>
                                            <span className="text-[11px] text-text-muted ml-2 font-medium">Focus Environment Active</span>
                                        </div>
                                        <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-50 border border-emerald-100">
                                            <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                                            <span className="text-[9px] font-bold text-emerald-700 uppercase tracking-widest">High Engagement</span>
                                        </div>
                                    </div>

                                    <div className="p-5 lg:p-6 space-y-5">
                                        {/* Flow indicator */}
                                        <div>
                                            <div className="flex justify-between text-[11px] text-text-muted mb-2">
                                                <span className="font-semibold text-foreground">Cognitive Load: Optimal</span>
                                                <span>Focus streak: 12m</span>
                                            </div>
                                            <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                                                <motion.div
                                                    initial={{ width: 0 }}
                                                    animate={{ width: "75%" }}
                                                    transition={{ delay: 1.2, duration: 1.5, ease: "easeOut" }}
                                                    className="h-full bg-emerald-400 rounded-full relative"
                                                >
                                                    <div className="absolute inset-0 bg-gradient-to-r from-transparent to-white/30 animate-pulse"></div>
                                                </motion.div>
                                            </div>
                                        </div>

                                        {/* AI Intervention block */}
                                        <div className="bg-[#f8fafc] rounded-xl p-4 lg:p-5 border border-[#f1f5f9] relative overflow-hidden">
                                            <div className="absolute top-0 right-0 w-32 h-32 bg-primary/5 rounded-full blur-2xl -mt-10 -mr-10"></div>
                                            <div className="flex gap-3.5 relative">
                                                <div className="w-8 h-8 rounded-lg bg-white shadow-sm border border-slate-100 flex items-center justify-center shrink-0 mt-0.5">
                                                    <Brain className="w-4 h-4 text-primary" />
                                                </div>
                                                <div>
                                                    <p className="text-[11px] font-bold text-slate-800 mb-1 uppercase tracking-wider">Passive detection</p>
                                                    <p className="text-[12px] text-slate-600 leading-relaxed font-medium">
                                                        I noticed you've been passively consuming for a while. Let's shift gears and ensure you're actually retaining this conceptually.
                                                    </p>
                                                </div>
                                            </div>
                                        </div>

                                        {/* Teach-back prompt */}
                                        <div className="rounded-xl p-4 lg:p-5 border border-primary/20 bg-gradient-to-b from-primary/[0.02] to-transparent shadow-[inset_0_2px_10px_rgba(7,23,44,0.02)]">
                                            <p className="text-[11px] font-bold text-primary mb-2 flex items-center gap-1.5 uppercase tracking-widest">
                                                <span className="relative flex h-2 w-2">
                                                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-40"></span>
                                                    <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
                                                </span>
                                                Active Recall Intervention
                                            </p>
                                            <p className="text-[14px] text-slate-800 leading-relaxed font-medium mb-1">
                                                Before we move forward, explain the foundational concept holding this chapter together.
                                            </p>
                                            <p className="text-[11px] text-slate-400 mb-3">Teach it to me in your own words.</p>
                                            <div className="mt-3 h-10 bg-white rounded-lg border border-[#e2e8f0] px-3.5 flex items-center shadow-sm">
                                                <motion.span
                                                    initial={{ opacity: 0 }}
                                                    animate={{ opacity: 1 }}
                                                    transition={{ delay: 0.5, duration: 0.5 }}
                                                    className="text-[12px] text-slate-400"
                                                >
                                                    I think the main idea is that...
                                                </motion.span>
                                            </div>
                                        </div>
                                    </div>
                                </motion.div>
                            </motion.div>
                        </motion.div>
                    </div>
                </div>
            </AuroraBackground>
        </div>
    );
}
