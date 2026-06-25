"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown } from "lucide-react";

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
        <section id="faq" className="py-20 lg:py-28 bg-[#f8fafc]">
            <div className="max-w-2xl mx-auto px-6 lg:px-8">
                {/* Header */}
                <motion.div
                    initial={{ opacity: 0, y: 16 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    viewport={{ once: true, margin: "-80px" }}
                    transition={{ duration: 0.4 }}
                    className="mb-10"
                >
                    <h2 className="text-3xl font-bold text-foreground font-display tracking-tight mb-2">
                        Common questions
                    </h2>
                    <p className="text-text-secondary">
                        If your question isn&apos;t here, email us. We reply fast.
                    </p>
                </motion.div>

                {/* Questions */}
                <div className="divide-y divide-[#e8eef3]">
                    {faqs.map(({ q, a }, i) => {
                        const isOpen = openIndex === i;
                        return (
                            <div key={i}>
                                <button
                                    onClick={() => setOpenIndex(isOpen ? null : i)}
                                    className="w-full flex items-center justify-between py-5 text-left group"
                                >
                                    <span className="text-[0.9rem] font-medium text-foreground pr-4 group-hover:text-primary transition-colors">
                                        {q}
                                    </span>
                                    <ChevronDown
                                        className={`w-4 h-4 text-text-muted shrink-0 transition-transform duration-200 ${isOpen ? "rotate-180" : ""
                                            }`}
                                    />
                                </button>
                                <AnimatePresence initial={false}>
                                    {isOpen && (
                                        <motion.div
                                            initial={{ height: 0, opacity: 0 }}
                                            animate={{ height: "auto", opacity: 1 }}
                                            exit={{ height: 0, opacity: 0 }}
                                            transition={{ duration: 0.2 }}
                                            className="overflow-hidden"
                                        >
                                            <p className="pb-5 text-sm text-text-secondary leading-relaxed">
                                                {a}
                                            </p>
                                        </motion.div>
                                    )}
                                </AnimatePresence>
                            </div>
                        );
                    })}
                </div>
            </div>
        </section>
    );
}
