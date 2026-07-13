"use client";

import { motion } from "framer-motion";
import { Brain, Activity, Target, Focus } from "lucide-react";
import { cn } from "@/lib/utils";

const insights = [
    "Focus drifting. Initiating active recall prompt.",
    "Mapping abstract models. Breaking down into mental hooks.",
    "Synthesizing structure. Adjusting difficulty curve.",
    "Engine detaching. Scholar is fully self-reliant."
];

const nodes = [
    { id: 0, icon: Focus, label: "Attention", x: 20, y: 15 },
    { id: 1, icon: Brain, label: "Guidance", x: 80, y: 40 },
    { id: 2, icon: Activity, label: "Mapping", x: 20, y: 65 },
    { id: 3, icon: Target, label: "Reliance", x: 80, y: 90 },
];

const SVG_WIDTH = 500;
const SVG_HEIGHT = 600;

function xPx(pct: number) {
    return (pct / 100) * SVG_WIDTH;
}

function yPx(pct: number) {
    return (pct / 100) * SVG_HEIGHT;
}

const paths = [
    `M ${xPx(nodes[0].x)} ${yPx(nodes[0].y)} C ${xPx(nodes[0].x) + 150} ${yPx(nodes[0].y)}, ${xPx(nodes[1].x) - 150} ${yPx(nodes[1].y)}, ${xPx(nodes[1].x)} ${yPx(nodes[1].y)}`,
    `M ${xPx(nodes[1].x)} ${yPx(nodes[1].y)} C ${xPx(nodes[1].x) - 150} ${yPx(nodes[1].y)}, ${xPx(nodes[2].x) + 150} ${yPx(nodes[2].y)}, ${xPx(nodes[2].x)} ${yPx(nodes[2].y)}`,
    `M ${xPx(nodes[2].x)} ${yPx(nodes[2].y)} C ${xPx(nodes[2].x) + 150} ${yPx(nodes[2].y)}, ${xPx(nodes[3].x) - 150} ${yPx(nodes[3].y)}, ${xPx(nodes[3].x)} ${yPx(nodes[3].y)}`
];

export default function CognitiveVisualization({ activePhase }: { activePhase: number }) {

    // Path lengths used to roughly animate strokeDashoffset
    // If phase is 0 (first node), no line filled
    // If phase is 1 (second node), fill first path
    // If phase is 2 (third node), fill second path
    // If phase is 3 (fourth node), fill third path

    return (
        <div className="w-full h-full min-h-[600px] relative bg-[#f8fafc]/50 rounded-3xl border border-[#e2e8f0]/60 shadow-[inset_0_2px_20px_rgba(255,255,255,1)] overflow-hidden flex items-center justify-center">

            {/* Background Soft Grid */}
            <div className="absolute inset-0 bg-[linear-gradient(to_right,#e2e8f080_1px,transparent_1px),linear-gradient(to_bottom,#e2e8f080_1px,transparent_1px)] bg-[size:32px_32px]"></div>

            {/* Responsive SVG Layer */}
            <div className="absolute inset-x-8 inset-y-12 max-w-[500px] mx-auto">
                <svg className="w-full h-full overflow-visible" viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`} preserveAspectRatio="xMidYMid meet">
                    {/* Background paths */}
                    {paths.map((d, i) => (
                        <path key={i} d={d} className="stroke-[#cbd5e1]/40" strokeWidth="2" strokeDasharray="6 6" fill="none" strokeLinecap="round" />
                    ))}

                    {/* Active paths */}
                    {paths.map((d, i) => {
                        const isActive = activePhase > i;
                        return (
                            <motion.path
                                key={`active-${i}`}
                                d={d}
                                className="stroke-primary"
                                strokeWidth="3"
                                fill="none"
                                strokeLinecap="round"
                                initial={{ pathLength: 0, opacity: 0 }}
                                animate={{
                                    pathLength: isActive ? 1 : 0,
                                    opacity: isActive ? 1 : 0
                                }}
                                transition={{ duration: 1.5, ease: "easeInOut" }}
                            />
                        )
                    })}

                    {/* Ambient Flow Pluse on active path segment */}
                    {paths.map((d, i) => {
                        return (
                            <motion.path
                                key={`pulse-${i}`}
                                d={d}
                                className="stroke-[var(--accent-primary)]"
                                strokeWidth="4"
                                fill="none"
                                strokeLinecap="round"
                                initial={{ pathLength: 0, pathOffset: 0, opacity: 0 }}
                                animate={
                                    activePhase === i ? {
                                        pathLength: [0, 0.3, 0.3, 0],
                                        pathOffset: [0, 0, 0.7, 1],
                                        opacity: [0, 0.8, 0.8, 0]
                                    } : {
                                        pathLength: 0, opacity: 0
                                    }
                                }
                                transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                            />
                        )
                    })}
                </svg>

                {/* Tracking nodes inside a relative container mapped to SVG percentages */}
                <div className="absolute inset-0 pointer-events-none">
                    {nodes.map((node) => {
                        const isActive = activePhase >= node.id;
                        const isCurrent = activePhase === node.id;
                        return (
                            <div
                                key={node.id}
                                className="absolute flex flex-col items-center justify-center transition-all duration-1000"
                                style={{
                                    left: `${node.x}%`,
                                    top: `${node.y}%`,
                                    transform: 'translate(-50%, -50%)',
                                    zIndex: isCurrent ? 20 : 10
                                }}
                            >
                                {/* Glowing Aura */}
                                <motion.div
                                    animate={{
                                        opacity: isCurrent ? 0.6 : 0,
                                        scale: isCurrent ? 1 : 0.5
                                    }}
                                    transition={{ duration: 1.5 }}
                                    className="absolute w-24 h-24 bg-primary/20 rounded-full blur-xl"
                                />

                                {/* Icon Node */}
                                <motion.div
                                    animate={{
                                        scale: isCurrent ? 1.15 : isActive ? 1 : 0.95,
                                        y: isCurrent ? -4 : 0
                                    }}
                                    transition={{ type: "spring", stiffness: 300, damping: 25 }}
                                    className={cn(
                                        "w-12 h-12 sm:w-14 sm:h-14 rounded-2xl flex items-center justify-center transition-colors duration-700 shadow-sm border",
                                        isActive
                                            ? "bg-white border-primary/20 shadow-[0_8px_20px_rgba(7,23,44,0.12)] text-primary"
                                            : "bg-[#f8fafc] border-[#cbd5e1]/40 text-slate-400"
                                    )}
                                >
                                    <node.icon className="w-5 h-5 sm:w-6 sm:h-6" />
                                </motion.div>

                                {/* Label Component */}
                                <motion.span
                                    animate={{
                                        opacity: isActive ? 1 : 0.5,
                                        y: isCurrent ? 0 : -4
                                    }}
                                    className={cn(
                                        "absolute top-full mt-2 sm:mt-3 text-[10px] sm:text-[11px] font-bold tracking-wider uppercase whitespace-nowrap bg-white/90 px-3 py-1 sm:py-1.5 rounded-full shadow-sm border backdrop-blur-md transition-colors duration-700",
                                        isActive ? "text-primary border-primary/20" : "text-slate-400 border-slate-200"
                                    )}
                                >
                                    {node.label}
                                </motion.span>
                            </div>
                        )
                    })}
                </div>
            </div>

            {/* AI Contextual Tutor Overlay */}
            <motion.div
                className="absolute bottom-6 sm:bottom-10 left-1/2 -translate-x-1/2 w-[90%] max-w-[340px]"
            >
                <div className="bg-white/80 backdrop-blur-xl border border-white/40 shadow-[0_8px_30px_rgb(0,0,0,0.06)] rounded-2xl p-4 flex gap-4 items-start relative overflow-hidden">
                    {/* Soft gradient background inset */}
                    <div className="absolute inset-0 bg-gradient-to-tr from-primary/[0.04] to-transparent pointer-events-none" />

                    <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0 border border-primary/20">
                        <div className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                    </div>
                    <div>
                        <p className="text-[10px] font-bold tracking-wider uppercase text-primary mb-1">
                            Engine Insight
                        </p>
                        <motion.p
                            key={activePhase}
                            initial={{ opacity: 0, y: 5 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -5 }}
                            transition={{ duration: 0.5 }}
                            className="text-sm text-slate-700 leading-snug font-medium"
                        >
                            {insights[activePhase] || insights[3]}
                        </motion.p>
                    </div>
                </div>
            </motion.div>

        </div>
    );
}
