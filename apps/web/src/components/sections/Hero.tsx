"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ArrowRight, Play } from "lucide-react";
import Link from "next/link";

const PASSAGES = [
    {
        source: "Cognitive Science, Ch. 4 — Attention & Retention",
        text: "The brain evolved to notice movement and novelty, not dense paragraphs. When attention drifts, comprehension doesn't fade — it drops off a cliff.",
        trigger: "cliff",
        question: "Quick check — what happens to comprehension when attention drifts?",
        answer: "It doesn't fade — it drops sharply.",
    },
    {
        source: "Cognitive Science, Ch. 7 — Study Techniques",
        text: "Highlighting a sentence feels like learning, but it only proves your eyes moved across it. Real retention needs retrieval, not re-reading.",
        trigger: "retrieval,",
        question: "Quick check — what does real retention actually require?",
        answer: "Retrieval — actively recalling it, not re-reading.",
    },
    {
        source: "Cognitive Science, Ch. 9 — Divided Attention",
        text: "Multitasking doesn't split attention evenly. Each switch has a cost, and the brain never fully returns to where it left off.",
        trigger: "cost,",
        question: "Quick check — what happens every time attention switches tasks?",
        answer: "It pays a cost — focus never fully resets.",
    },
];

type Phase = "idle" | "reading" | "drift" | "prompt" | "answering" | "resuming" | "retained";

const STATUS: Record<Phase, { label: string; className: string }> = {
    idle: { label: "Reading", className: "text-text-muted border-[var(--color-border-soft)]" },
    reading: { label: "Reading", className: "text-emerald-700 border-emerald-200" },
    drift: { label: "Attention drift detected", className: "text-red-700 border-red-200" },
    prompt: { label: "Waiting for recall", className: "text-primary border-[var(--accent-secondary)]/40 bg-[var(--accent-secondary)]/8" },
    answering: { label: "Waiting for recall", className: "text-primary border-[var(--accent-secondary)]/40 bg-[var(--accent-secondary)]/8" },
    resuming: { label: "Resuming — reinforced", className: "text-emerald-700 border-emerald-200" },
    retained: { label: "Concept retained", className: "text-primary border-[var(--accent-secondary)]/40 bg-[var(--accent-secondary)]/8" },
};

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export default function Hero() {
    const [passageIdx, setPassageIdx] = useState(0);
    const [inkedCount, setInkedCount] = useState(0);
    const [phase, setPhase] = useState<Phase>("idle");
    const [typedAnswer, setTypedAnswer] = useState("");
    const [isPaused, setIsPaused] = useState(false);
    const isPausedRef = useRef(false);

    useEffect(() => {
        const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        if (prefersReducedMotion) {
            // Accessibility requires the final state to appear immediately with
            // zero animation — deferring this past a microtask would risk a
            // visible flash of the "idle" frame first, which is the exact
            // motion this branch exists to prevent.
            const words = PASSAGES[0].text.split(" ");
            /* eslint-disable react-hooks/set-state-in-effect */
            setInkedCount(words.length);
            setTypedAnswer(PASSAGES[0].answer);
            setPhase("retained");
            /* eslint-enable react-hooks/set-state-in-effect */
            return;
        }

        let cancelled = false;

        async function wait(ms: number) {
            let remaining = ms;
            while (remaining > 0) {
                if (cancelled) return;
                if (isPausedRef.current) {
                    await sleep(80);
                    continue;
                }
                const step = Math.min(40, remaining);
                await sleep(step);
                remaining -= step;
            }
        }

        async function runCycle() {
            let idx = 0;
            while (!cancelled) {
                const passage = PASSAGES[idx];
                const words = passage.text.split(" ");
                const triggerIndex = words.findIndex((w) => w.includes(passage.trigger));

                setPassageIdx(idx);
                setInkedCount(0);
                setTypedAnswer("");
                setPhase("reading");
                await wait(400);

                for (let i = 0; i <= triggerIndex; i++) {
                    if (cancelled) return;
                    setInkedCount(i + 1);
                    await wait(65);
                }
                if (cancelled) return;

                setPhase("drift");
                await wait(900);
                if (cancelled) return;

                setPhase("prompt");
                await wait(900);
                if (cancelled) return;

                setPhase("answering");
                for (let i = 0; i <= passage.answer.length; i++) {
                    if (cancelled) return;
                    setTypedAnswer(passage.answer.slice(0, i));
                    await wait(24);
                }
                await wait(650);
                if (cancelled) return;

                setPhase("resuming");
                for (let i = triggerIndex + 1; i <= words.length; i++) {
                    if (cancelled) return;
                    setInkedCount(i);
                    await wait(50);
                }
                if (cancelled) return;

                setPhase("retained");
                await wait(3000);
                if (cancelled) return;

                idx = (idx + 1) % PASSAGES.length;
            }
        }

        runCycle();
        return () => {
            cancelled = true;
        };
    }, []);

    const passage = PASSAGES[passageIdx];
    const words = passage.text.split(" ");
    const triggerIndex = words.findIndex((w) => w.includes(passage.trigger));
    const promptOpen = phase === "prompt" || phase === "answering";
    const isCaretVisible = phase === "reading" || phase === "resuming";
    const status = isPaused
        ? { label: "Paused — move away to resume", className: "text-text-secondary border-[var(--color-border-soft)] bg-[var(--color-light-bg)]" }
        : STATUS[phase];

    return (
        <section className="relative overflow-hidden pt-20 pb-6 lg:pt-24 lg:pb-8 min-h-[100svh]">
            {/* Ambient glow, top-right */}
            <div
                className="absolute inset-0 pointer-events-none"
                style={{
                    background:
                        "radial-gradient(820px 500px at 82% -10%, rgba(198,164,92,0.13), transparent 62%)",
                }}
            />

            <div className="relative z-10 max-w-[1600px] mx-auto w-full px-6 lg:px-12">
                <motion.div
                    initial={{ opacity: 0, y: 16 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.6 }}
                    className="max-w-xl"
                >
                    <div className="flex items-center gap-2 mb-4">
                        <span className="w-6 h-px bg-[var(--accent-secondary)]" />
                        <span className="text-[0.75rem] font-mono uppercase tracking-[0.14em] text-[var(--accent-secondary)]">
                            AI Tutor · built different
                        </span>
                    </div>

                    <h1 className="font-serif text-primary mb-5">
                        <span className="block font-semibold text-[2.75rem] sm:text-[3.4rem] lg:text-[4.1rem] leading-[1.03] tracking-tight">
                            Study smarter.
                        </span>
                        <span className="block italic font-normal text-text-secondary text-[1.7rem] sm:text-[2.1rem] lg:text-[2.55rem] leading-[1.15] mt-1">
                            Then study <span className="text-[var(--accent-secondary)]">alone.</span>
                        </span>
                    </h1>

                    <p className="text-[1.05rem] lg:text-[1.15rem] text-text-secondary leading-[1.65] mb-6 pl-4 border-l-2 border-[var(--color-border-soft)]">
                        HIE builds real understanding through guided lessons, active recall, and
                        teach-back — <strong className="text-primary font-semibold">not another app that wants your attention forever.</strong>
                    </p>

                    <div className="flex items-center gap-2 mb-4 text-[0.82rem] font-mono text-text-muted">
                        <span>Here&apos;s what that looks like</span>
                        <motion.span
                            animate={{ y: [0, 3, 0] }}
                            transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
                            className="text-[var(--accent-secondary)]"
                        >
                            ↓
                        </motion.span>
                    </div>
                </motion.div>

                {/* Stage — live interruption demo. Hover to pause and read at your own pace. */}
                <motion.div
                    initial={{ opacity: 0, y: 16 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.6, delay: 0.15 }}
                    onMouseEnter={() => {
                        isPausedRef.current = true;
                        setIsPaused(true);
                    }}
                    onMouseLeave={() => {
                        isPausedRef.current = false;
                        setIsPaused(false);
                    }}
                    className="bg-white border border-[var(--color-border-soft)] rounded-2xl shadow-[0_24px_60px_-24px_rgba(7,23,44,0.2)] p-5 lg:p-6"
                >
                    <div className="flex items-center justify-between mb-3">
                        <span className="text-[0.72rem] font-mono text-text-muted">{passage.source}</span>
                        <span
                            className={`flex items-center gap-1.5 text-[0.68rem] font-mono uppercase tracking-wide px-2.5 py-1 rounded-full border transition-colors duration-300 ${status.className}`}
                        >
                            <span className="w-1.5 h-1.5 rounded-full bg-current" />
                            {status.label}
                        </span>
                    </div>

                    <p className="text-[1.1rem] lg:text-[1.18rem] leading-[1.6]">
                        {words.map((word, i) => (
                            <Fragment key={i}>
                                <span
                                    className={`transition-all duration-300 ${i < inkedCount
                                            ? "text-primary blur-none opacity-100"
                                            : "text-[var(--color-border-soft)] blur-[1.5px] opacity-70"
                                        } ${i === triggerIndex && i < inkedCount ? "bg-[var(--accent-secondary)]/25 rounded" : ""
                                        }`}
                                >
                                    {word}
                                </span>{" "}
                                {isCaretVisible && i === inkedCount - 1 && (
                                    <span className="inline-block w-[2px] h-[1em] align-middle bg-[var(--accent-secondary)] animate-pulse" />
                                )}
                            </Fragment>
                        ))}
                    </p>

                    <div
                        className="overflow-hidden transition-[max-height,opacity,margin] duration-500 ease-out"
                        style={{ maxHeight: promptOpen ? 116 : 0, opacity: promptOpen ? 1 : 0, marginTop: promptOpen ? 14 : 0 }}
                    >
                        <div className="rounded-xl border border-[var(--accent-secondary)] bg-gradient-to-b from-[var(--accent-secondary)]/8 to-transparent p-4">
                            <p className="text-[0.94rem] font-semibold text-primary mb-2">{passage.question}</p>
                            <div className="h-9 bg-[var(--color-light-bg)] rounded-lg border border-[var(--color-border-soft)] px-3.5 flex items-center">
                                <span className="text-[0.85rem] text-primary font-medium">{typedAnswer}</span>
                                {phase === "answering" && (
                                    <span className="inline-block w-[2px] h-4 bg-[var(--accent-secondary)] ml-0.5 animate-pulse" />
                                )}
                            </div>
                        </div>
                    </div>

                    <div
                        className="overflow-hidden transition-[max-height,opacity,margin] duration-500 ease-out"
                        style={{ maxHeight: phase === "retained" ? 32 : 0, opacity: phase === "retained" ? 1 : 0, marginTop: phase === "retained" ? 12 : 0 }}
                    >
                        <span className="inline-flex items-center gap-1.5 text-[0.8rem] font-semibold text-emerald-700 bg-emerald-50 px-3 py-1 rounded-full">
                            ✓ Retained — concept understood, not just seen
                        </span>
                    </div>
                </motion.div>

                <motion.div
                    initial={{ opacity: 0, y: 16 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.6, delay: 0.25 }}
                    className="mt-5"
                >
                    <div className="flex flex-wrap items-center gap-4 mb-3">
                        <motion.div
                            whileHover={{ y: -2, boxShadow: "0 20px 40px -10px rgba(7,23,44,0.4)" }}
                            whileTap={{ y: 1 }}
                            transition={{ type: "spring", stiffness: 400, damping: 25 }}
                            className="rounded-xl"
                        >
                            <Link
                                href="/signup"
                                className="group inline-flex items-center gap-2.5 px-7 py-3.5 text-[0.98rem] font-semibold text-white bg-primary rounded-xl shadow-[0_1px_2px_rgba(0,0,0,0.05),0_4px_16px_rgba(7,23,44,0.25)] transition-colors duration-150"
                            >
                                Try it free
                                <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
                            </Link>
                        </motion.div>
                        <a
                            href="#how-it-works"
                            className="inline-flex items-center gap-2 px-3 py-3.5 text-[0.98rem] font-medium text-text-secondary hover:text-primary transition-colors"
                        >
                            <Play className="w-4 h-4" />
                            See how it works
                        </a>
                    </div>

                    <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[0.85rem] text-text-muted font-medium">
                        <span className="flex items-center gap-1.5">
                            <span className="text-emerald-600">✓</span> Free to try
                        </span>
                        <span className="flex items-center gap-1.5">
                            <span className="text-emerald-600">✓</span> Private Learner DNA profile — never a raw score
                        </span>
                        <span className="flex items-center gap-1.5">
                            <span className="text-emerald-600">✓</span> No credit card
                        </span>
                    </div>
                </motion.div>
            </div>
        </section>
    );
}
