"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Sparkles, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { onboardingService } from "@/services/onboarding.service";

const DISMISS_KEY_PREFIX = "dismissed_reassessment_prompt_at_session_";

function isDismissed(sessionCount: number): boolean {
    if (typeof window === "undefined") return false;
    try {
        return window.localStorage.getItem(`${DISMISS_KEY_PREFIX}${sessionCount}`) !== null;
    } catch {
        return false;
    }
}

function markDismissed(sessionCount: number) {
    if (typeof window === "undefined") return;
    try {
        window.localStorage.setItem(`${DISMISS_KEY_PREFIX}${sessionCount}`, "1");
    } catch {
        // localStorage unavailable (private browsing / quota) — dismissal just won't persist
    }
}

export function ReassessmentPrompt() {
    const router = useRouter();
    const [sessionCount, setSessionCount] = useState<number | null>(null);
    const [dismissed, setDismissed] = useState(false);

    useEffect(() => {
        let cancelled = false;
        onboardingService
            .getLearnerDna()
            .then((dna) => {
                if (cancelled) return;
                if (dna.reassessment_due) {
                    setSessionCount(dna.session_count);
                }
            })
            .catch(() => {
                // Fetch failure fails closed — no prompt, not a blocking error.
            });
        return () => {
            cancelled = true;
        };
    }, []);

    if (sessionCount === null || dismissed || isDismissed(sessionCount)) {
        return null;
    }

    function handleDismiss() {
        if (sessionCount !== null) markDismissed(sessionCount);
        setDismissed(true);
    }

    return (
        <AnimatePresence>
            <motion.div
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, ease: "easeOut" }}
                className="relative w-full rounded-2xl border border-neutral-100 bg-white shadow-sm p-6 flex items-center justify-between gap-4"
            >
                <div className="flex items-center gap-4">
                    <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-[var(--accent-primary)]/10 flex items-center justify-center">
                        <Sparkles className="w-5 h-5 text-[var(--accent-primary)]" />
                    </div>
                    <div>
                        <p className="font-medium text-neutral-900">Your Learner DNA is due for a refresh</p>
                        <p className="text-sm text-neutral-500">
                            Retake the diagnostic to sharpen your personalisation.
                        </p>
                    </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                    <Button
                        variant="outline"
                        size="sm"
                        className="rounded-2xl border-neutral-200"
                        onClick={() => router.push("/onboarding")}
                    >
                        Update My Profile
                    </Button>
                    <button
                        type="button"
                        aria-label="Dismiss"
                        onClick={handleDismiss}
                        className="text-neutral-400 hover:text-neutral-600 p-1"
                    >
                        <X className="w-4 h-4" />
                    </button>
                </div>
            </motion.div>
        </AnimatePresence>
    );
}
