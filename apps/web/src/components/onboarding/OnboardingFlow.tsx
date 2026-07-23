"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import axios from "axios";
import { AnimatePresence } from "framer-motion";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { onboardingService } from "@/services/onboarding.service";
import { QuestionCard } from "./QuestionCard";
import { DNAResultCard } from "./DNAResultCard";
import { QUESTIONS, DIMENSION_LABEL } from "./questions";
import type { LearnerDNA, OnboardingResult } from "@/types/assessment";

type Phase = "checking" | "disclaimer" | "questions" | "result" | "error";

const TOTAL = QUESTIONS.length;
const STORAGE_KEY = "onboarding_progress_v1";

interface PersistedProgress {
    current: number;
    answers: Record<string, number>;
    disclaimerAcknowledged: boolean;
    // Set only while resuming a re-assessment (Story 2-12) — ties the persisted blob to the
    // specific reassessment instance so a stale attempt from an earlier due session_count is
    // never silently resumed against a later, different one.
    dueSessionCount?: number;
}

function loadPersistedProgress(): PersistedProgress | null {
    if (typeof window === "undefined") return null;
    try {
        const raw = window.sessionStorage.getItem(STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw) as Partial<PersistedProgress>;
        if (typeof parsed.current !== "number" || typeof parsed.answers !== "object" || !parsed.answers) {
            return null;
        }
        return {
            current: parsed.current,
            answers: parsed.answers,
            disclaimerAcknowledged: Boolean(parsed.disclaimerAcknowledged),
            dueSessionCount: typeof parsed.dueSessionCount === "number" ? parsed.dueSessionCount : undefined,
        };
    } catch {
        return null;
    }
}

function persistProgress(progress: PersistedProgress) {
    if (typeof window === "undefined") return;
    try {
        window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(progress));
    } catch {
        // sessionStorage unavailable (private browsing / quota) — progress just won't survive a refresh
    }
}

function clearPersistedProgress() {
    if (typeof window === "undefined") return;
    try {
        window.sessionStorage.removeItem(STORAGE_KEY);
    } catch {
        // ignore
    }
}

function getStatus(err: unknown): number | undefined {
    return axios.isAxiosError(err) ? err.response?.status : undefined;
}

function getErrorDetail(err: unknown): string | undefined {
    return axios.isAxiosError<{ detail?: string }>(err) ? err.response?.data?.detail : undefined;
}

export function OnboardingFlow() {
    const router = useRouter();
    const [phase, setPhase] = useState<Phase>("checking");
    const [current, setCurrent] = useState(0);
    const [answers, setAnswers] = useState<Record<string, number>>({});
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [result, setResult] = useState<OnboardingResult | LearnerDNA | null>(null);
    const [submitError, setSubmitError] = useState<string | null>(null);
    const [submitErrorTerminal, setSubmitErrorTerminal] = useState(false);
    const [dueSessionCount, setDueSessionCount] = useState<number | undefined>(undefined);

    useEffect(() => {
        let cancelled = false;
        onboardingService
            .getLearnerDna()
            .then((dna) => {
                if (cancelled) return;
                if (dna.reassessment_due) {
                    // Due for a re-assessment — proceed into the same disclaimer/questions
                    // flow a first-time user gets rather than redirecting away. Only resume
                    // persisted progress if it was captured for this exact reassessment
                    // instance (dueSessionCount) — otherwise it's a stale attempt from an
                    // earlier reassessment and must not be silently mixed in.
                    setDueSessionCount(dna.session_count);
                    const persisted = loadPersistedProgress();
                    if (persisted?.disclaimerAcknowledged && persisted.dueSessionCount === dna.session_count) {
                        setCurrent(persisted.current);
                        setAnswers(persisted.answers);
                        setPhase("questions");
                    } else {
                        setPhase("disclaimer");
                    }
                    return;
                }
                clearPersistedProgress();
                router.push("/dashboard");
            })
            .catch((err) => {
                if (cancelled) return;
                if (getStatus(err) === 401) {
                    router.push("/signin");
                    return;
                }
                // 404 = not onboarded yet (expected). Any other error fails open into the flow
                // rather than hard-blocking the student on a transient network error.
                const persisted = loadPersistedProgress();
                if (persisted?.disclaimerAcknowledged) {
                    setCurrent(persisted.current);
                    setAnswers(persisted.answers);
                    setPhase("questions");
                } else {
                    setPhase("disclaimer");
                }
            });
        return () => {
            cancelled = true;
        };
        // useRouter()'s return value is referentially stable for the component's lifetime in the
        // Next.js App Router, and this effect is intentionally mount-only regardless — safe to omit.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        if (phase === "questions" || phase === "error") {
            persistProgress({ current, answers, disclaimerAcknowledged: true, dueSessionCount });
        }
    }, [phase, current, answers, dueSessionCount]);

    const question = QUESTIONS[current];
    const selectedIndex = question ? answers[question.id] : undefined;
    const isLast = current === TOTAL - 1;
    const canProceed = selectedIndex !== undefined;

    function handleSelect(index: number) {
        setAnswers((prev) => ({ ...prev, [question.id]: index }));
    }

    function handleBack() {
        if (current > 0) setCurrent((c) => c - 1);
    }

    function handleNext() {
        if (current < TOTAL - 1) setCurrent((c) => c + 1);
    }

    async function handleSubmit() {
        setIsSubmitting(true);
        setSubmitError(null);
        setSubmitErrorTerminal(false);

        const responses = QUESTIONS.map((q) => ({
            question_id: q.id,
            dimension: q.dimension,
            selected_index: answers[q.id] ?? 0,
            selected_text: q.options[answers[q.id] ?? 0],
        }));

        try {
            const data = await onboardingService.submitOnboarding(responses);
            clearPersistedProgress();
            setResult(data);
            setPhase("result");
            return;
        } catch (err) {
            if (getStatus(err) === 401) {
                router.push("/signin");
                return;
            }
            if (getStatus(err) === 409) {
                try {
                    const dna = await onboardingService.getLearnerDna();
                    clearPersistedProgress();
                    setResult(dna);
                    setPhase("result");
                    return;
                } catch {
                    // Onboarding is already complete server-side (the 409 proves it), but we
                    // couldn't fetch that existing profile either. Retrying submitOnboarding
                    // would just 409 forever — offer an escape hatch instead of a dead-end loop.
                    setSubmitError(
                        "You've already completed onboarding, but we couldn't load your profile right now."
                    );
                    setSubmitErrorTerminal(true);
                    setPhase("error");
                    return;
                }
            }
            setSubmitError(getErrorDetail(err) ?? "Submission failed. Please try again.");
            setPhase("error");
        } finally {
            setIsSubmitting(false);
        }
    }

    function handleContinue() {
        clearPersistedProgress();
        router.push("/dashboard");
    }

    if (phase === "checking") {
        return (
            <div className="flex min-h-[60vh] items-center justify-center">
                <Loader2 className="h-6 w-6 animate-spin text-[var(--accent-primary)]" />
            </div>
        );
    }

    if (phase === "disclaimer") {
        return (
            <div className="mx-auto w-full max-w-xl">
                <div className="rounded-2xl border border-neutral-100 bg-white p-8 shadow-sm">
                    <h1 className="mb-3 font-serif text-2xl font-semibold text-neutral-900">
                        Before we begin
                    </h1>
                    <p className="mb-8 leading-relaxed text-neutral-600">
                        This is not a clinical assessment. Scores are used only to personalise your
                        learning experience.
                    </p>
                    <Button
                        variant="primary"
                        size="md"
                        className="rounded-2xl"
                        onClick={() => setPhase("questions")}
                    >
                        I Understand, Begin Assessment
                    </Button>
                </div>
            </div>
        );
    }

    if (phase === "result" && result) {
        return (
            <div className="mx-auto w-full max-w-xl">
                <DNAResultCard result={result} onContinue={handleContinue} />
            </div>
        );
    }

    if (phase === "error") {
        return (
            <div className="mx-auto w-full max-w-xl">
                <div className="rounded-2xl border border-neutral-100 bg-white p-8 shadow-sm">
                    <p className="mb-6 text-sm text-red-600">{submitError}</p>
                    {submitErrorTerminal ? (
                        <Button variant="primary" size="md" className="rounded-2xl" onClick={handleContinue}>
                            Continue to Dashboard
                        </Button>
                    ) : (
                        <Button
                            variant="primary"
                            size="md"
                            className="rounded-2xl"
                            isLoading={isSubmitting}
                            disabled={isSubmitting}
                            onClick={handleSubmit}
                        >
                            Retry
                        </Button>
                    )}
                </div>
            </div>
        );
    }

    // phase: 'questions'
    return (
        <div className="mx-auto w-full max-w-xl">
            <div className="mb-8 text-center">
                <span className="text-xl font-bold text-[var(--accent-primary)]">TransformED AI</span>
                <h1 className="mt-3 font-serif text-2xl font-semibold text-neutral-900">
                    Learner DNA Assessment
                </h1>
            </div>

            <div className="mb-6">
                <div className="mb-1.5 flex items-center justify-between text-xs text-neutral-400">
                    <span>Question {current + 1} of {TOTAL}</span>
                    <span className="font-medium text-[var(--accent-primary)]">
                        {DIMENSION_LABEL[question.dimension]}
                    </span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-neutral-200">
                    <div
                        className="h-full rounded-full bg-[var(--accent-primary)] transition-all duration-300"
                        style={{ width: `${Math.round(((current + 1) / TOTAL) * 100)}%` }}
                    />
                </div>
            </div>

            <AnimatePresence mode="wait">
                <QuestionCard
                    key={question.id}
                    question={question}
                    selectedIndex={selectedIndex}
                    onSelect={handleSelect}
                />
            </AnimatePresence>

            <div className="mt-6 flex items-center justify-between">
                <Button variant="ghost" size="sm" onClick={handleBack} disabled={current === 0}>
                    Back
                </Button>

                {isLast ? (
                    <Button
                        variant="primary"
                        size="md"
                        className="rounded-2xl"
                        isLoading={isSubmitting}
                        disabled={!canProceed || isSubmitting}
                        onClick={handleSubmit}
                    >
                        Complete Assessment
                    </Button>
                ) : (
                    <Button
                        variant="primary"
                        size="md"
                        className="rounded-2xl"
                        disabled={!canProceed}
                        onClick={handleNext}
                    >
                        Next
                    </Button>
                )}
            </div>
        </div>
    );
}
