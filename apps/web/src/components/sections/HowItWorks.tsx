"use client";

import { motion } from "framer-motion";
import { Upload, Brain, BookOpen, MessageSquare, BarChart3, FileText, CheckCircle2, Activity, Target } from "lucide-react";
import { cn } from "@/lib/utils";

const steps = [
    {
        num: "1",
        icon: Upload,
        title: "Upload Dense Material",
        desc: "Drop in your 50-page PDF or lecture slides. The engine accepts the raw material that usually causes cognitive overload.",
    },
    {
        num: "2",
        icon: Brain,
        title: "Cognitive Extraction",
        desc: "HIE maps the foundational concepts and underlying frameworks, structurally stripping away the noise.",
    },
    {
        num: "3",
        icon: BookOpen,
        title: "Immersive Guided Learning",
        desc: "Enter a structured focus environment where the AI acts as a sophisticated tutor, breaking concepts down incrementally.",
    },
    {
        num: "4",
        icon: Activity,
        title: "Adaptive Intervention",
        desc: "When you lose focus or consume passively, the system detects it and prompts active recall to rebuild your attention.",
    },
    {
        num: "5",
        icon: Target,
        title: "Capability Growth",
        desc: "Over time, cognitive crutches are removed. You build the psychological capacity to synthesize and focus completely independently.",
    },
];

// Nodes mapping for the 500x500 abstract visualization
const nodes = [
    { id: 1, icon: FileText, x: 90, y: 100, label: "Raw Material" },
    { id: 2, icon: Brain, x: 250, y: 250, label: "Cognitive Engine", isPrimary: true },
    { id: 3, icon: BookOpen, x: 410, y: 100, label: "Immersion" },
    { id: 4, icon: Activity, x: 410, y: 390, label: "Intervention" },
    { id: 5, icon: Target, x: 90, y: 390, label: "Self-Reliance" },
];

const paths = [
    // PDF -> AI Core
    "M 90 100 C 170 100 250 170 250 250",
    // AI Core -> Lessons
    "M 250 250 C 250 170 330 100 410 100",
    // Lessons -> Tutor
    "M 410 100 C 410 245 410 245 410 390",
    // Tutor -> Mastery
    "M 410 390 C 250 390 250 390 90 390"
];

function ProcessVisual() {
    return (
        <div className="relative w-full aspect-square max-h-[600px] mt-10 lg:mt-0 bg-[#f8fafc]/80 rounded-[2rem] border border-[#e2e8f0]/80 shadow-[inset_0_2px_20px_rgba(255,255,255,1)] overflow-hidden">
            {/* Soft grid background */}
            <div className="absolute inset-0 bg-[linear-gradient(to_right,#e2e8f080_1px,transparent_1px),linear-gradient(to_bottom,#e2e8f080_1px,transparent_1px)] bg-[size:32px_32px]"></div>

            {/* Glowing background orbs */}
            <div className="absolute top-[10%] left-[20%] w-64 h-64 bg-primary/15 rounded-full blur-3xl opacity-60"></div>
            <div className="absolute bottom-[10%] right-[20%] w-64 h-64 bg-sky-400/15 rounded-full blur-3xl opacity-60"></div>

            <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 500 500" fill="none">
                {paths.map((d, i) => (
                    <g key={i}>
                        {/* Base dashed line */}
                        <path d={d} className="stroke-[#cbd5e1]/80" strokeWidth="2" strokeDasharray="6 6" strokeLinecap="round" />
                        {/* Animated flowing energy */}
                        <motion.path
                            d={d}
                            className="stroke-primary"
                            strokeWidth="3.5"
                            strokeLinecap="round"
                            initial={{ pathLength: 0, pathOffset: 0, opacity: 0 }}
                            animate={{
                                pathLength: [0, 0.4, 0.4, 0],
                                pathOffset: [0, 0, 0.6, 1],
                                opacity: [0, 1, 1, 0]
                            }}
                            transition={{
                                duration: 3,
                                repeat: Infinity,
                                ease: "easeInOut",
                                delay: i * 0.75 // cascading pulse delay through the network
                            }}
                        />
                    </g>
                ))}
            </svg>

            {/* Overlay Nodes */}
            {nodes.map((node) => (
                <div
                    key={node.id}
                    className="absolute z-10 flex flex-col items-center justify-center pointer-events-none"
                    style={{ left: `${(node.x / 500) * 100}%`, top: `${(node.y / 500) * 100}%`, transform: 'translate(-50%, -50%)' }}
                >
                    <motion.div
                        animate={{ y: [0, -8, 0] }}
                        whileHover={{ scale: 1.08, y: -4 }}
                        transition={{
                            duration: 3.5,
                            repeat: Infinity,
                            ease: "easeInOut",
                            delay: node.id * 0.2
                        }}
                        className="flex flex-col items-center gap-2 pointer-events-auto cursor-default hover:z-20 transition-all"
                    >
                        {/* Card UI */}
                        <div className={cn(
                            "w-[56px] h-[56px] sm:w-[68px] sm:h-[68px] rounded-2xl flex items-center justify-center transition-all bg-white shadow-[0_8px_30px_rgb(0,0,0,0.06)] border border-[#e2e8f0]",
                            node.isPrimary && "w-[64px] h-[64px] sm:w-[80px] sm:h-[80px] rounded-[1.25rem] bg-gradient-to-tr from-primary to-primary-dark shadow-[0_8px_32px_rgba(47,128,237,0.35)] border-transparent"
                        )}>
                            <node.icon className={cn("w-6 h-6 sm:w-7 sm:h-7", node.isPrimary ? "text-white w-7 h-7 sm:w-8 sm:h-8" : "text-primary")} />
                        </div>
                        {/* Label */}
                        <span className="text-[10px] font-bold tracking-wider uppercase text-slate-500 bg-white/90 px-3 py-1.5 rounded-full shadow-sm border border-[#e2e8f0]/80 backdrop-blur-md">
                            {node.label}
                        </span>
                    </motion.div>
                </div>
            ))}
        </div>
    );
}

export default function HowItWorks() {
    return (
        <section id="how-it-works" className="py-20 lg:py-28 bg-transparent relative overflow-hidden">
            <div className="max-w-6xl mx-auto px-6 lg:px-8">
                <div className="grid lg:grid-cols-2 gap-12 lg:gap-20 items-center">

                    {/* Left - Timeline Information */}
                    <div className="relative z-10 max-w-xl">
                        <motion.div
                            initial={{ opacity: 0, y: 16 }}
                            whileInView={{ opacity: 1, y: 0 }}
                            viewport={{ once: true, margin: "-80px" }}
                            transition={{ duration: 0.4 }}
                            className="mb-14"
                        >
                            <p className="text-sm font-semibold text-primary mb-2 tracking-wide uppercase">
                                The Cognitive Pipeline
                            </p>
                            <h2 className="text-3xl sm:text-[2.25rem] font-bold text-foreground font-display tracking-tight leading-tight">
                                From cognitive overload to complete mastery.
                            </h2>
                        </motion.div>

                        <div className="space-y-0">
                            {steps.map(({ num, icon: Icon, title, desc }, i) => (
                                <motion.div
                                    key={num}
                                    initial={{ opacity: 0, y: 16 }}
                                    whileInView={{ opacity: 1, y: 0 }}
                                    viewport={{ once: true, margin: "-40px" }}
                                    whileHover={{ x: 4 }}
                                    transition={{ duration: 0.4, delay: i * 0.05, type: "spring", stiffness: 400, damping: 30 }}
                                    className="relative flex gap-6 pb-10 last:pb-0 group"
                                >
                                    {/* Vertical line connecting timeline icons */}
                                    {i < steps.length - 1 && (
                                        <div className="absolute left-[19px] top-12 bottom-0 w-[2px] bg-[#f1f5f9]" />
                                    )}

                                    {/* Step number icon circle */}
                                    <div className="w-10 h-10 rounded-full bg-white border-2 border-[#f1f5f9] flex items-center justify-center shrink-0 z-10 shadow-sm relative">
                                        <Icon className="w-4 h-4 text-primary" />
                                    </div>

                                    {/* Content Block */}
                                    <div className="pt-1.5">
                                        <h3 className="text-[0.95rem] font-semibold text-foreground mb-1">
                                            <span className="text-primary mr-1.5">{num}.</span>
                                            {title}
                                        </h3>
                                        <p className="text-sm text-text-secondary leading-relaxed">
                                            {desc}
                                        </p>
                                    </div>
                                </motion.div>
                            ))}
                        </div>
                    </div>

                    {/* Right - Premium Process Visualization */}
                    <motion.div
                        initial={{ opacity: 0, scale: 0.95, x: 20 }}
                        whileInView={{ opacity: 1, scale: 1, x: 0 }}
                        viewport={{ once: true, margin: "-80px" }}
                        transition={{ duration: 0.6, ease: "easeOut" }}
                        className="w-full h-full flex items-center justify-center relative z-0"
                    >
                        <ProcessVisual />
                    </motion.div>

                </div>
            </div>
        </section>
    );
}
