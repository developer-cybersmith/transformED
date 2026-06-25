"use client";

import { motion } from "framer-motion";

const steps = [
    { label: "Distracted", opacity: 0.3 },
    { label: "Guided", opacity: 0.5 },
    { label: "Focused", opacity: 0.7 },
    { label: "Independent", opacity: 0.9 },
    { label: "Scholar", opacity: 1, active: true },
];

export function LearnerEvolution() {
    return (
        <div className="relative mt-8 max-w-sm">
            <div className="absolute left-3 top-2 bottom-2 w-0.5 bg-gradient-to-b from-neutral-800 via-[var(--accent-primary)]/50 to-[var(--accent-primary)] rounded-full" />

            <div className="space-y-6">
                {steps.map((step, index) => (
                    <motion.div
                        key={step.label}
                        initial={{ opacity: 0, x: -20 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ duration: 0.5, delay: index * 0.15 }}
                        className="flex items-center gap-6 relative"
                    >
                        <div
                            className={`w-6 h-6 rounded-full flex items-center justify-center z-10 shrink-0 ${step.active
                                    ? "bg-[var(--accent-primary)] shadow-[0_0_20px_rgba(var(--accent-primary-rgb),0.5)]"
                                    : "bg-neutral-900 border-2 border-neutral-700"
                                }`}
                        >
                            {step.active && <div className="w-2 h-2 rounded-full bg-white" />}
                        </div>
                        <div
                            className={`text-lg font-medium tracking-wide transition-all duration-700`}
                            style={{ opacity: step.opacity, color: step.active ? 'white' : '#a3a3a3' }}
                        >
                            {step.label}
                        </div>
                    </motion.div>
                ))}
            </div>
        </div>
    );
}
