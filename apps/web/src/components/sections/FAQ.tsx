"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Plus } from "lucide-react";

const faqs = [
    {
        q: "What kind of PDFs can I upload?",
        a: "Textbooks, lecture notes, research papers, study guides — anything text-based. If it's a scan or mostly images, accuracy may be lower, but we're improving that constantly.",
    },
    {
        q: "How long until my lesson is ready?",
        a: "Usually 1–3 minutes. A short chapter might take under a minute. A 100-page document might take 5. We'll notify you when it's ready.",
    },
    {
        q: "Is this actually better than just watching YouTube?",
        a: "YouTube is passive — you watch, you forget. HIE makes you engage: answer questions, explain things back, and get tested. Research shows active recall improves retention by 3–5× compared to passive video.",
    },
    {
        q: "Can I use this for university textbooks?",
        a: "That's exactly what it's built for. Dense academic content is where HIE shines — the AI breaks down complex material into manageable pieces and tests your understanding at each step.",
    },
    {
        q: "Is my data private? What about webcam access?",
        a: "Your PDFs are encrypted and never shared. If attention-aware features are on, all processing happens locally on your device — no webcam data leaves your browser. You can disable it anytime.",
    },
    {
        q: "What happens after my 3 free uploads?",
        a: "Your existing lessons stay accessible forever. You just can't create new ones until next month, or you can upgrade to Pro for unlimited uploads. No pressure.",
    },
];

export default function FAQ() {
    const [openIndex, setOpenIndex] = useState<number | null>(null);

    return (
        <section id="faq" className="py-20 lg:py-28 bg-[var(--color-light-bg)]">
            <div className="max-w-6xl mx-auto px-6 lg:px-8">
                <div className="grid lg:grid-cols-[1fr_1.4fr] gap-12 lg:gap-16">
                    {/* Left — sticky intro, not a centered header */}
                    <motion.div
                        initial={{ opacity: 0, y: 16 }}
                        whileInView={{ opacity: 1, y: 0 }}
                        viewport={{ once: true, margin: "-80px" }}
                        transition={{ duration: 0.5 }}
                        className="lg:sticky lg:top-28 lg:self-start"
                    >
                        <div className="flex items-center gap-2 mb-4">
                            <span className="w-6 h-px bg-[var(--accent-secondary)]" />
                            <span className="text-[0.72rem] font-mono uppercase tracking-[0.14em] text-[var(--accent-secondary)]">
                                Fair questions
                            </span>
                        </div>
                        <h2 className="font-serif text-primary mb-4">
                            <span className="block font-semibold text-[2.1rem] lg:text-[2.5rem] leading-[1.08] tracking-tight">
                                You should be skeptical.
                            </span>
                            <span className="block italic font-normal text-text-secondary text-[1.4rem] lg:text-[1.7rem] leading-[1.15] mt-1">
                                Good. Ask anyway.
                            </span>
                        </h2>
                        <p className="text-text-secondary text-[0.98rem] leading-relaxed mb-5">
                            Still stuck on something? We answer real emails from real people.
                        </p>
                        <a
                            href="mailto:hello@hieiq.ai"
                            className="inline-flex items-center gap-2 text-[0.88rem] font-semibold text-primary hover:text-[var(--accent-secondary)] transition-colors"
                        >
                            hello@hieiq.ai →
                        </a>
                    </motion.div>

                    {/* Right — accordion */}
                    <div className="divide-y divide-[var(--color-border-soft)]">
                        {faqs.map(({ q, a }, i) => {
                            const isOpen = openIndex === i;
                            const panelId = `faq-panel-${i}`;
                            return (
                                <motion.div
                                    key={i}
                                    initial={{ opacity: 0, y: 12 }}
                                    whileInView={{ opacity: 1, y: 0 }}
                                    viewport={{ once: true, margin: "-60px" }}
                                    transition={{ duration: 0.4, delay: i * 0.04 }}
                                >
                                    <button
                                        onClick={() => setOpenIndex(isOpen ? null : i)}
                                        aria-expanded={isOpen}
                                        aria-controls={panelId}
                                        className="w-full flex items-center justify-between gap-4 py-5 text-left group"
                                    >
                                        <span
                                            className={`font-serif text-[1.05rem] lg:text-[1.15rem] transition-colors ${isOpen ? "text-primary font-semibold" : "text-foreground group-hover:text-primary"
                                                }`}
                                        >
                                            {q}
                                        </span>
                                        <span
                                            className={`shrink-0 w-7 h-7 rounded-full flex items-center justify-center border transition-all duration-300 ${isOpen
                                                    ? "bg-[var(--accent-secondary)] border-[var(--accent-secondary)] rotate-45"
                                                    : "border-[var(--color-border-soft)]"
                                                }`}
                                        >
                                            <Plus className={`w-3.5 h-3.5 ${isOpen ? "text-primary" : "text-text-muted"}`} />
                                        </span>
                                    </button>
                                    <AnimatePresence initial={false}>
                                        {isOpen && (
                                            <motion.div
                                                id={panelId}
                                                role="region"
                                                aria-label={q}
                                                initial={{ height: 0, opacity: 0 }}
                                                animate={{ height: "auto", opacity: 1 }}
                                                exit={{ height: 0, opacity: 0 }}
                                                transition={{ duration: 0.25 }}
                                                className="overflow-hidden"
                                            >
                                                <p className="pb-5 pl-4 pr-6 text-[0.95rem] text-text-secondary leading-relaxed border-l-2 border-[var(--accent-secondary)]/40">
                                                    {a}
                                                </p>
                                            </motion.div>
                                        )}
                                    </AnimatePresence>
                                </motion.div>
                            );
                        })}
                    </div>
                </div>
            </div>
        </section>
    );
}
