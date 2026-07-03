"use client";

import { useEffect, useState } from "react";

const PHASES = [
    "Passive Consumer",
    "Guided Learner",
    "Active Synthesizer",
    "Self-Reliant Scholar",
];

export function LearnerEvolution() {
    const [active, setActive] = useState(0);

    useEffect(() => {
        const interval = setInterval(() => {
            setActive((prev) => (prev + 1) % PHASES.length);
        }, 2200);
        return () => clearInterval(interval);
    }, []);

    return (
        <div className="mt-2">
            {/* Progress track */}
            <div className="relative flex items-center justify-between mb-7 px-1">
                <div className="absolute left-1 right-1 top-1/2 -translate-y-1/2 h-[2px] bg-white/10" />
                <div
                    className="absolute left-1 top-1/2 -translate-y-1/2 h-[2px] bg-[var(--accent-secondary)] transition-all duration-700 ease-out"
                    style={{ width: `calc(${(active / (PHASES.length - 1)) * 100}% - 2px)` }}
                />
                {PHASES.map((phase, i) => (
                    <div
                        key={phase}
                        className={`relative z-10 w-3 h-3 rounded-full border-2 transition-all duration-500 ${i <= active
                                ? "bg-[var(--accent-secondary)] border-[var(--accent-secondary)] shadow-[0_0_14px_rgba(198,164,92,0.6)]"
                                : "bg-neutral-900 border-white/20"
                            }`}
                    />
                ))}
            </div>

            {/* Current phase, cross-fading */}
            <div className="relative h-9 mb-1">
                {PHASES.map((phase, i) => (
                    <div
                        key={phase}
                        className={`absolute inset-0 flex items-center font-serif italic text-2xl text-white transition-all duration-500 ${i === active ? "opacity-100 translate-y-0" : "opacity-0 translate-y-1 pointer-events-none"
                            }`}
                    >
                        {phase}
                    </div>
                ))}
            </div>
            <p className="text-[0.7rem] font-mono text-neutral-500 uppercase tracking-widest">
                Phase {active + 1} of {PHASES.length}
            </p>
        </div>
    );
}
