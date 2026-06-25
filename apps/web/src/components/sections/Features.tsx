"use client";

import { useRef, useState } from "react";
import { motion, useScroll, useTransform, useMotionValueEvent } from "framer-motion";
import CognitiveVisualization from "./CognitiveVisualization";

const capabilities = [
    {
        num: "01",
        title: "Attention-Aware Intervention",
        description: "Detects when you drift into passive consumption and instantly shifts modes—prompting active recall to snap you back into deep focus.",
        image: "/phases/phase-1.png"
    },
    {
        num: "02",
        title: "Adaptive Cognitive Tutor",
        description: "Not a generic chatbot. A specialized engine that breaks down complex frameworks when you're stuck, and steps back when you're capable.",
        image: "/phases/phase-2.png"
    },
    {
        num: "03",
        title: "Learning DNA Mapping",
        description: "As you interact, the system maps out how your brain synthesizes information—identifying cognitive gaps and adjusting the difficulty curve.",
        image: "/phases/phase-3.png"
    },
    {
        num: "04",
        title: "Independent Progression",
        description: "The goal isn't to hold your hand forever. The system gradually removes cognitive crutches until you can parse massive documents entirely on your own.",
        image: "/phases/phase-4.png"
    }
];

function PhaseCard({ cap, index }: { cap: typeof capabilities[0], index: number }) {
    const cardRef = useRef<HTMLDivElement>(null);
    const { scrollYProgress } = useScroll({
        target: cardRef,
        offset: ["start 75%", "start 35%"]
    });

    const opacity = useTransform(scrollYProgress, [0, 1], [0.3, 1]);
    const y = useTransform(scrollYProgress, [0, 1], [20, 0]);
    const scale = useTransform(scrollYProgress, [0, 1], [0.98, 1]);
    const colorOpacity = useTransform(scrollYProgress, [0, 1], [0.2, 1]);

    return (
        <motion.div
            ref={cardRef}
            style={{ opacity, y, scale }}
            className="relative group border-t border-slate-200/80 pt-8"
        >
            <motion.span
                style={{ opacity: colorOpacity }}
                className="block text-primary font-mono text-sm tracking-wider mb-5 flex items-center gap-2"
            >
                <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                [ PHASE {cap.num} ]
            </motion.span>
            <h3 className="text-xl sm:text-2xl font-bold text-slate-900 mb-4 tracking-tight leading-tight group-hover:text-primary transition-colors duration-300">
                {cap.title}
            </h3>
            <p className="text-slate-500 leading-[1.8] text-[1.05rem] mb-10">
                {cap.description}
            </p>

            {/* Contextual Premium Mockup */}
            <div className="relative w-full rounded-[2rem] overflow-hidden shadow-[0_12px_40px_rgb(0,0,0,0.06)] border border-slate-200/60 opacity-80 group-hover:opacity-100 transition-all duration-700 bg-white">
                <img
                    src={cap.image}
                    alt={`Visualization of Phase ${cap.num}`}
                    className="w-full h-auto object-cover transform scale-100 group-hover:scale-105 transition-transform duration-[1.5s] ease-out"
                />
            </div>
        </motion.div>
    );
}

export default function Features() {
    const containerRef = useRef<HTMLElement>(null);
    const [activePhase, setActivePhase] = useState(0);

    const { scrollYProgress } = useScroll({
        target: containerRef,
        offset: ["start start", "end end"]
    });

    // Map the scroll progress of the entire section to specific phases
    const phaseIndex = useTransform(scrollYProgress, (pos) => {
        if (pos < 0.25) return 0;
        if (pos < 0.5) return 1;
        if (pos < 0.75) return 2;
        return 3;
    });

    useMotionValueEvent(phaseIndex, "change", (latest) => {
        setActivePhase(latest);
    });

    return (
        <section id="features" ref={containerRef} className="py-24 lg:py-32 bg-transparent relative">
            <div className="max-w-6xl mx-auto px-6 lg:px-8">

                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    viewport={{ once: true, margin: "-100px" }}
                    transition={{ duration: 0.6 }}
                    className="max-w-3xl mb-20 lg:mb-28"
                >
                    <p className="text-slate-900 font-semibold tracking-widest uppercase text-[11px] mb-6">
                        The Cognitive Engine
                    </p>
                    <h2 className="text-[2.5rem] sm:text-[3.5rem] font-bold text-slate-900 font-display tracking-tight leading-[1.05] mb-8">
                        The architecture of self-reliance.
                    </h2>
                    <p className="text-[1.1rem] sm:text-[1.25rem] text-slate-500 leading-[1.6] max-w-2xl">
                        HIE does not just reorganize your PDFs. It acts as an AI Tutor running a continuous cognitive loop designed to rapidly overcome the 7-second attention span and mature your reasoning.
                    </p>
                </motion.div>

                <div className="grid lg:grid-cols-2 gap-16 lg:gap-24 relative">
                    {/* Left Column - Sticky Cognitive Visualization */}
                    <div className="hidden lg:block relative z-10 w-full">
                        <div className="sticky top-[15vh] w-full h-[600px]">
                            <CognitiveVisualization activePhase={activePhase} />
                        </div>
                    </div>

                    {/* Right Column - Scrolling Phases */}
                    <div className="relative z-20 space-y-24 sm:space-y-32 pb-[10vh] pt-10">
                        {capabilities.map((cap, i) => (
                            <PhaseCard key={cap.num} cap={cap} index={i} />
                        ))}
                    </div>
                </div>

            </div>

            {/* Ambient Intelligence Flow */}
            <motion.div
                animate={{
                    x: ["-100%", "200%"],
                    opacity: [0, 0.05, 0]
                }}
                transition={{ duration: 12, repeat: Infinity, ease: "linear" }}
                className="absolute top-1/3 left-0 w-[400px] h-[200px] bg-gradient-to-r from-transparent via-primary/20 to-transparent blur-[80px] pointer-events-none -z-10"
            />
            <motion.div
                animate={{
                    x: ["200%", "-100%"],
                    opacity: [0, 0.08, 0]
                }}
                transition={{ duration: 18, repeat: Infinity, ease: "linear", delay: 2 }}
                className="absolute bottom-1/3 left-0 w-[600px] h-[300px] bg-gradient-to-r from-transparent via-sky-400/20 to-transparent blur-[100px] pointer-events-none -z-10"
            />
        </section>
    );
}
