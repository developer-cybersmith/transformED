"use client";

import { motion } from "framer-motion";

const problems = [
    "You re-read the same paragraph 4 times and still can't explain it.",
    "You watch a 90-minute lecture at 2× speed and remember nothing.",
    "Your textbook has 400 pages. Your exam is in 3 days.",
    "You highlight everything. It helps with nothing.",
];

const solutions = [
    {
        label: "Active recall",
        detail: "You get quizzed on what you just read — not next week, right now.",
    },
    {
        label: "Teach-back",
        detail: "Explain the concept back to the AI. If you can teach it, you know it.",
    },
    {
        label: "Adaptive depth",
        detail: "Struggling? The AI slows down and tries a different angle. Got it? It moves on.",
    },
    {
        label: "Structured flow",
        detail: "No more jumping between topics. Concepts build on each other in the right order.",
    },
];

export default function WhyHIE() {
    return (
        <section className="py-20 lg:py-28 bg-[#f8fafc]">
            <div className="max-w-6xl mx-auto px-6 lg:px-8">
                <div className="grid lg:grid-cols-2 gap-16 lg:gap-24">
                    {/* Left — the problem */}
                    <motion.div
                        initial={{ opacity: 0, y: 16 }}
                        whileInView={{ opacity: 1, y: 0 }}
                        viewport={{ once: true, margin: "-60px" }}
                        transition={{ duration: 0.4 }}
                    >
                        <p className="text-sm font-semibold text-rose-500 mb-2 tracking-wide uppercase">
                            The problem
                        </p>
                        <h2 className="text-2xl sm:text-3xl font-bold text-foreground font-display tracking-tight leading-snug mb-8">
                            Most study methods were designed before the internet existed.
                        </h2>

                        <div className="space-y-4">
                            {problems.map((p, i) => (
                                <div
                                    key={i}
                                    className="flex items-start gap-3 text-[0.9rem] text-text-secondary leading-relaxed"
                                >
                                    <span className="w-5 h-5 rounded-full bg-rose-50 text-rose-400 text-xs flex items-center justify-center shrink-0 mt-0.5 font-medium">
                                        ×
                                    </span>
                                    {p}
                                </div>
                            ))}
                        </div>
                    </motion.div>

                    {/* Right — the solution */}
                    <motion.div
                        initial={{ opacity: 0, y: 16 }}
                        whileInView={{ opacity: 1, y: 0 }}
                        viewport={{ once: true, margin: "-60px" }}
                        transition={{ duration: 0.4, delay: 0.08 }}
                    >
                        <p className="text-sm font-semibold text-emerald-600 mb-2 tracking-wide uppercase">
                            What actually works
                        </p>
                        <h2 className="text-2xl sm:text-3xl font-bold text-foreground font-display tracking-tight leading-snug mb-8">
                            Learning science says: make the brain work.
                        </h2>

                        <div className="space-y-5">
                            {solutions.map(({ label, detail }, i) => (
                                <div key={i} className="flex items-start gap-3">
                                    <span className="w-5 h-5 rounded-full bg-emerald-50 text-emerald-500 text-xs flex items-center justify-center shrink-0 mt-0.5 font-medium">
                                        ✓
                                    </span>
                                    <div>
                                        <p className="text-[0.9rem] font-semibold text-foreground">{label}</p>
                                        <p className="text-[0.85rem] text-text-secondary leading-relaxed">{detail}</p>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </motion.div>
                </div>
            </div>
        </section>
    );
}
