"use client";

import { useRef } from "react";
import { motion, useScroll, useTransform } from "framer-motion";
import { BookOpen, ZapOff, BrainCircuit } from "lucide-react";

export default function TheCrisis() {
    const sectionRef = useRef<HTMLElement>(null);
    const { scrollYProgress } = useScroll({
        target: sectionRef,
        offset: ["start end", "end start"]
    });

    const cardFrictionY = useTransform(scrollYProgress, [0, 1], [40, -40]);
    const headerFrictionY = useTransform(scrollYProgress, [0, 1], [0, 30]);

    return (
        <section ref={sectionRef} className="py-24 lg:py-32 bg-transparent relative overflow-hidden">
            <div className="max-w-5xl mx-auto px-6 lg:px-8">
                <motion.div
                    style={{ y: headerFrictionY }}
                    initial={{ opacity: 0, y: 20 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    viewport={{ once: true, margin: "-100px" }}
                    transition={{ duration: 0.6 }}
                    className="text-center max-w-3xl mx-auto mb-20"
                >
                    <p className="text-rose-500 font-semibold tracking-wider uppercase text-sm mb-4">The Learning Crisis</p>
                    <h2 className="text-[2.5rem] sm:text-[3rem] font-bold text-slate-900 font-display tracking-tight leading-[1.1] mb-6">
                        We are conditioned to scroll, not to think.
                    </h2>
                    <p className="text-[1.1rem] text-slate-600 leading-[1.8]">
                        Modern students aren't failing because the material is too hard. They're failing because passive consumption has destroyed their ability to focus deeply. Staring at a dense 50-page PDF doesn't work when your brain expects constant stimulation.
                    </p>
                </motion.div>

                <motion.div style={{ y: cardFrictionY }} className="grid md:grid-cols-3 gap-8 lg:gap-12 relative z-10 w-full">
                    {[
                        {
                            icon: BookOpen,
                            title: "Passive Consumption",
                            desc: "Reading words without processing them. You reach the bottom of the page and realize you haven't retained a single concept."
                        },
                        {
                            icon: ZapOff,
                            title: "Fragmented Attention",
                            desc: "Jumping between tabs and notifications. Without guided immersion, the brain seeks the quickest path to a dopamine hit."
                        },
                        {
                            icon: BrainCircuit,
                            title: "The Illusion of Competence",
                            desc: "Recognizing a term in a textbook makes you feel like you know it—until you sit down for the exam and draw a blank."
                        }
                    ].map((item, index) => (
                        <motion.div
                            key={item.title}
                            initial={{ opacity: 0, y: 30 }}
                            whileInView={{ opacity: 1, y: 0 }}
                            viewport={{ once: true, margin: "-100px" }}
                            whileHover={{ y: -2 }}
                            transition={{ duration: 0.5, delay: index * 0.15, type: "spring", stiffness: 400, damping: 30 }}
                            className="relative flex flex-col items-center text-center p-6 border border-transparent hover:border-slate-100 rounded-3xl transition-colors duration-300 group"
                        >
                            <motion.div
                                className="w-14 h-14 rounded-2xl bg-white border border-slate-100 flex items-center justify-center mb-6 shadow-sm group-hover:shadow-[0_8px_30px_rgb(0,0,0,0.04)] transition-all duration-300"
                            >
                                <item.icon className="w-6 h-6 text-slate-400 group-hover:text-primary transition-colors duration-300" />
                            </motion.div>
                            <h3 className="text-xl font-bold text-slate-900 mb-3">{item.title}</h3>
                            <p className="text-slate-600 leading-relaxed text-[0.95rem]">
                                {item.desc}
                            </p>
                        </motion.div>
                    ))}
                </motion.div>
            </div>

            {/* Ambient Crisis Drift */}
            <motion.div
                animate={{
                    y: [0, -40, 0],
                    opacity: [0.1, 0.2, 0.1]
                }}
                transition={{ duration: 25, repeat: Infinity, ease: "easeInOut" }}
                className="absolute top-1/4 -left-32 w-[600px] h-[600px] bg-slate-400/10 rounded-full blur-[140px] pointer-events-none -z-10"
            />
            <motion.div
                animate={{
                    y: [0, 50, 0],
                    x: [0, -40, 0],
                    opacity: [0.1, 0.2, 0.1]
                }}
                transition={{ duration: 30, repeat: Infinity, ease: "easeInOut", delay: 2 }}
                className="absolute bottom-1/4 -right-32 w-[500px] h-[500px] bg-slate-300/10 rounded-full blur-[140px] pointer-events-none -z-10"
            />
        </section>
    );
}
