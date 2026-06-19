"use client";

import { useRef } from "react";
import { motion, useScroll, useTransform } from "framer-motion";
import { Milestone } from "lucide-react";

const journeySteps = [
    {
        stage: "Phase 01",
        title: "Passive Consumer",
        desc: "Relies on skimming and rote memorization. Struggles to maintain focus on complex, dense texts.",
    },
    {
        stage: "Phase 02",
        title: "Guided Learner",
        desc: "Uses the cognitive engine to extract structures. Begins to recognize underlying patterns in the noise.",
    },
    {
        stage: "Phase 03",
        title: "Active Synthesizer",
        desc: "Anticipates concepts before the AI prompts them. Uses teach-back naturally to verify own understanding.",
    },
    {
        stage: "Phase 04",
        title: "Self-Reliant Scholar",
        desc: "Parses overwhelming information independently. The engine is no longer a crutch—it's just a faster workflow.",
    }
];

function PhaseTimelineNode({ step, i }: { step: typeof journeySteps[0], i: number }) {
    const nodeRef = useRef<HTMLDivElement>(null);
    const { scrollYProgress } = useScroll({
        target: nodeRef,
        offset: ["start 85%", "start 45%"]
    });

    const opacity = useTransform(scrollYProgress, [0, 1], [0.3, 1]);
    const scale = useTransform(scrollYProgress, [0, 1], [0.95, 1]);
    const y = useTransform(scrollYProgress, [0, 1], [20, 0]);
    const iconScale = useTransform(scrollYProgress, [0, 1], [0.8, 1.1]);

    const isEven = i % 2 === 0;

    return (
        <motion.div ref={nodeRef} style={{ opacity, scale, y }} className="relative flex flex-col sm:flex-row items-start sm:items-center justify-between group">
            {/* Left Side (or Top on mobile) */}
            <div className="w-full sm:w-[calc(50%-3rem)] pl-16 sm:pl-0 sm:text-right mb-4 sm:mb-0">
                {isEven && (
                    <>
                        <p className="text-primary font-mono text-sm mb-2 transition-colors">{step.stage}</p>
                        <h3 className="text-xl lg:text-2xl font-bold mb-3 group-hover:text-sky-300 transition-colors duration-300">{step.title}</h3>
                        <p className="text-slate-400 leading-relaxed text-[0.95rem]">{step.desc}</p>
                    </>
                )}
            </div>

            {/* Center Milestone Node */}
            <motion.div
                style={{ scale: iconScale }}
                className="absolute left-0 sm:left-1/2 w-12 h-12 rounded-full border-4 border-slate-900 bg-slate-800 flex items-center justify-center sm:-translate-x-1/2 ring-2 ring-transparent group-hover:ring-primary/50 group-hover:bg-primary transition-all duration-500 z-10"
            >
                <Milestone className="w-5 h-5 text-slate-400 group-hover:text-white transition-colors" />
            </motion.div>

            {/* Right Side (or Bottom on mobile) */}
            <div className="w-full sm:w-[calc(50%-3rem)] pl-16 sm:pl-0">
                {!isEven && (
                    <>
                        <p className="text-primary font-mono text-sm mb-2 transition-colors">{step.stage}</p>
                        <h3 className="text-xl lg:text-2xl font-bold mb-3 group-hover:text-sky-300 transition-colors duration-300">{step.title}</h3>
                        <p className="text-slate-400 leading-relaxed text-[0.95rem]">{step.desc}</p>
                    </>
                )}
            </div>
        </motion.div>
    );
}

export default function JourneyToSelfReliance() {
    const sectionRef = useRef<HTMLElement>(null);
    const { scrollYProgress } = useScroll({
        target: sectionRef,
        offset: ["start center", "end center"]
    });

    const lineHeight = useTransform(scrollYProgress, [0, 1], ["0%", "100%"]);

    return (
        <section ref={sectionRef} className="py-24 lg:py-32 bg-slate-900 text-white relative overflow-hidden">
            {/* Background ambiance */}
            <div className="absolute top-0 left-1/2 -translate-x-1/2 w-full max-w-4xl h-full bg-[radial-gradient(ellipse_at_top,rgba(47,128,237,0.15),transparent_70%)] pointer-events-none" />

            <div className="max-w-5xl mx-auto px-6 lg:px-8 relative z-10">
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    viewport={{ once: true, margin: "-100px" }}
                    transition={{ duration: 0.6 }}
                    className="text-center max-w-3xl mx-auto mb-20 lg:mb-28"
                >
                    <h2 className="text-[2.25rem] sm:text-[3rem] font-bold font-display tracking-tight leading-[1.1] mb-6">
                        The Evolution of a Learner
                    </h2>
                    <p className="text-[1.1rem] text-slate-400 leading-[1.75]">
                        TransformED is temporary by design. Our metric for success is the day you no longer need the AI to understand the textbook.
                    </p>
                </motion.div>

                {/* Vertical Timeline */}
                <div className="relative max-w-3xl mx-auto">
                    {/* The Center Line Base */}
                    <div className="absolute left-[24px] sm:left-1/2 top-0 bottom-0 w-[2px] bg-slate-800 sm:-translate-x-1/2" />

                    {/* The Animated Fill Line */}
                    <motion.div
                        style={{ height: lineHeight }}
                        className="absolute left-[24px] sm:left-1/2 top-0 w-[2px] bg-gradient-to-b from-primary via-sky-400 to-emerald-400 sm:-translate-x-1/2 z-0"
                    />

                    <div className="space-y-16 lg:space-y-24">
                        {journeySteps.map((step, i) => (
                            <PhaseTimelineNode key={step.stage} step={step} i={i} />
                        ))}
                    </div>
                </div>

            </div>
        </section>
    );
}
