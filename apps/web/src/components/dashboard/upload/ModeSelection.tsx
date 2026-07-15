"use client";

import { useEffect, useRef } from "react";
import { LEARNER_TIER_OPTIONS, type LearnerTier } from "@/types/learnerMode";

interface ModeSelectionProps {
    onSelect: (tier: LearnerTier) => void;
}

export function ModeSelection({ onSelect }: ModeSelectionProps) {
    const firstCardRef = useRef<HTMLButtonElement>(null);

    // Moves focus onto the screen as soon as it mounts — otherwise a keyboard
    // user's focus is left on whatever triggered this screen (e.g. "Browse
    // Files"), which then unmounts, dropping focus to document.body.
    useEffect(() => {
        firstCardRef.current?.focus();
    }, []);

    return (
        <div className="w-full grid grid-cols-1 sm:grid-cols-3 gap-6">
            {LEARNER_TIER_OPTIONS.map((option, index) => (
                <button
                    key={option.id}
                    ref={index === 0 ? firstCardRef : undefined}
                    type="button"
                    onClick={() => onSelect(option.id)}
                    className="flex flex-col items-start text-left p-8 rounded-[2rem] border border-neutral-100 bg-white/80 backdrop-blur-xl shadow-[0_8px_30px_rgb(0,0,0,0.04)] hover:shadow-lg hover:border-[var(--accent-primary)]/50 hover:-translate-y-1 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--accent-primary)]/20 transition-all duration-300"
                >
                    <h4 className="font-serif text-xl font-semibold tracking-tight text-neutral-900 mb-2">
                        {option.label}
                    </h4>
                    <p className="text-neutral-500 text-sm leading-relaxed">
                        {option.description}
                    </p>
                </button>
            ))}
        </div>
    );
}
