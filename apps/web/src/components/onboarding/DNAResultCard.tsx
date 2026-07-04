"use client";

import { motion } from "framer-motion";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { LearnerDNA, OnboardingResult } from "@/types/assessment";

export interface DNAResultCardProps {
    result: OnboardingResult | LearnerDNA;
    onContinue: () => void;
}

export function DNAResultCard({ result, onContinue }: DNAResultCardProps) {
    // Defensive: the backend shape is trusted only via a TS cast at the API boundary
    // (api.get<T>()/api.post<T>()) — guard against a runtime shape drift crashing this screen.
    const badgeLabels = result.badge_labels ?? [];
    const profileText = result.profile_text ?? "";

    return (
        <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: "easeOut" }}
            className="rounded-2xl border border-neutral-100 bg-white p-8 shadow-sm"
        >
            <div className="mb-4 inline-flex items-center gap-2 rounded-full bg-[var(--accent-secondary)]/20 px-3 py-1.5 text-xs font-medium text-[var(--accent-primary)]">
                <Sparkles className="h-3.5 w-3.5" />
                Your Learner DNA
            </div>

            {badgeLabels.length > 0 && (
                <div className="mb-5 flex flex-wrap gap-2">
                    {badgeLabels.map((label) => (
                        <span
                            key={label}
                            className="rounded-full border border-neutral-200 bg-neutral-50 px-3 py-1 text-sm font-medium text-neutral-800"
                        >
                            {label}
                        </span>
                    ))}
                </div>
            )}

            {profileText && (
                <p className="mb-8 whitespace-pre-line leading-relaxed text-neutral-600">
                    {profileText}
                </p>
            )}

            <Button variant="primary" size="md" className="rounded-2xl" onClick={onContinue}>
                Continue to Dashboard
            </Button>
        </motion.div>
    );
}
