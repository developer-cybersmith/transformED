"use client";

import { useRef } from "react";
import { motion, useScroll, useTransform } from "framer-motion";
import { ArrowRight, BrainCog, Smartphone, Focus, BrainCircuit, Target, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";

export default function TransformationPromise() {
    const sectionRef = useRef<HTMLElement>(null);
    const { scrollYProgress } = useScroll({
        target: sectionRef,
        offset: ["start center", "center center"]
    });

    const beforeOpacity = useTransform(scrollYProgress, [0, 1], [1, 0.7]);
    const beforeScale = useTransform(scrollYProgress, [0, 1], [1, 0.95]);

    const afterOpacity = useTransform(scrollYProgress, [0, 1], [0.7, 1]);
    const afterScale = useTransform(scrollYProgress, [0, 1], [0.95, 1.02]);
    const afterY = useTransform(scrollYProgress, [0, 1], [20, 0]);

    return (
        <section ref={sectionRef} className="py-24 bg-transparent relative overflow-hidden">
            <div className="max-w-6xl mx-auto px-6 lg:px-8">
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    viewport={{ once: true, margin: "-100px" }}
                    transition={{ duration: 0.6 }}
                    className="text-center max-w-3xl mx-auto mb-16"
                >
                    <h2 className="text-[2.25rem] sm:text-[2.75rem] font-bold text-slate-900 font-display tracking-tight leading-[1.1] mb-6">
                        The Shift to Self-Reliance
                    </h2>
                    <p className="text-[1.1rem] text-slate-600 leading-[1.75]">
                        We don't just build software that reads PDFs for you. We build a cognitive engine designed to fundamentally alter how you process information.
                    </p>
                </motion.div>

                <div className="grid lg:grid-cols-[auto_auto_auto] lg:grid-cols-[1fr_auto_1fr] gap-8 items-center relative z-10">

                    {/* Before State */}
                    <motion.div
                        style={{ opacity: beforeOpacity, scale: beforeScale }}
                        className="bg-white rounded-3xl p-8 lg:p-10 border border-slate-200 shadow-sm relative overflow-hidden group transition-shadow duration-300 hover:shadow-[0_8px_30px_rgb(0,0,0,0.04)]"
                    >
                        <div className="absolute top-0 left-0 w-full h-1 bg-slate-200" />
                        <div className="flex items-center gap-4 mb-8">
                            <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center">
                                <BrainCog className="w-6 h-6 text-slate-500" />
                            </div>
                            <div>
                                <h3 className="text-xl font-bold text-slate-900">Overwhelmed</h3>
                                <p className="text-sm text-slate-500 font-medium">The default modern state</p>
                            </div>
                        </div>

                        <ul className="space-y-4">
                            {[
                                "Relies on video entertainment to learn",
                                "Skims helplessly through dense 50-page PDFs",
                                "Loses focus after 10 minutes of reading",
                                "Recognizes material but can't actively explain it"
                            ].map((item, i) => (
                                <li key={i} className="flex gap-3 text-slate-600">
                                    <Smartphone className="w-5 h-5 text-slate-300 shrink-0 mt-0.5" />
                                    <span className="leading-relaxed text-[0.95rem]">{item}</span>
                                </li>
                            ))}
                        </ul>
                    </motion.div>

                    {/* Arrow / Connector */}
                    <motion.div
                        initial={{ opacity: 0, scale: 0.8 }}
                        whileInView={{ opacity: 1, scale: 1 }}
                        viewport={{ once: true }}
                        className="hidden lg:flex w-14 h-14 rounded-full bg-white border border-slate-200 shadow-sm items-center justify-center z-20 shrink-0"
                    >
                        <ArrowRight className="w-6 h-6 text-slate-400" />
                    </motion.div>

                    {/* After State */}
                    <motion.div
                        style={{ opacity: afterOpacity, scale: afterScale, y: afterY }}
                        className="bg-white rounded-3xl p-8 lg:p-10 border border-primary/20 shadow-[0_8px_30px_rgb(0,0,0,0.04)] relative overflow-hidden group transition-shadow duration-300"
                    >
                        <div className="absolute inset-0 bg-gradient-to-br from-primary/[0.03] to-transparent pointer-events-none" />
                        <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-primary to-sky-400" />

                        <div className="flex items-center gap-4 mb-8 relative">
                            <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center transition-transform duration-300">
                                <Target className="w-6 h-6 text-primary" />
                            </div>
                            <div>
                                <h3 className="text-xl font-bold text-slate-900">Self-Reliant Scholar</h3>
                                <p className="text-sm text-primary font-bold">The TransformED state</p>
                            </div>
                        </div>

                        <ul className="space-y-4 relative">
                            {[
                                "Extracts core insights instantly",
                                "Maintains deep focus via adaptive interventions",
                                "Synthesizes concepts systematically",
                                "Proves mastery through active teach-back"
                            ].map((item, i) => (
                                <li key={i} className="flex gap-3 text-slate-700 font-medium">
                                    <CheckCircle2 className="w-5 h-5 text-emerald-500 shrink-0 mt-0.5" />
                                    <span className="leading-relaxed text-[0.95rem]">{item}</span>
                                </li>
                            ))}
                        </ul>
                    </motion.div>

                </div>
            </div>

            {/* Ambient Upward Growth Drift */}
            <motion.div
                animate={{
                    y: [100, -100],
                    opacity: [0, 0.15, 0]
                }}
                transition={{ duration: 15, repeat: Infinity, ease: "linear" }}
                className="absolute bottom-0 left-1/2 -translate-x-1/2 w-[800px] h-[800px] bg-primary/10 rounded-full blur-[140px] pointer-events-none -z-10"
            />
            <motion.div
                animate={{
                    y: [150, -150],
                    x: [0, 30, -30, 0],
                    opacity: [0, 0.1, 0]
                }}
                transition={{ duration: 22, repeat: Infinity, ease: "linear", delay: 5 }}
                className="absolute bottom-0 left-1/4 w-[500px] h-[500px] bg-sky-300/10 rounded-full blur-[120px] pointer-events-none -z-10"
            />
        </section>
    );
}
