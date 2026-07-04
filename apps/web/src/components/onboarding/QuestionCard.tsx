"use client";

import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Question } from "./questions";

export interface QuestionCardProps {
    question: Question;
    selectedIndex: number | undefined;
    onSelect: (index: number) => void;
}

export function QuestionCard({ question, selectedIndex, onSelect }: QuestionCardProps) {
    return (
        <motion.div
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -16 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            className="rounded-2xl border border-neutral-100 bg-white p-8 shadow-sm"
        >
            <p className="mb-6 text-base font-medium text-neutral-900">{question.text}</p>

            <div role="radiogroup" aria-label={question.text} className="space-y-3">
                {question.options.map((option, idx) => {
                    const selected = selectedIndex === idx;
                    return (
                        <Button
                            key={idx}
                            type="button"
                            variant="outline"
                            role="radio"
                            aria-checked={selected}
                            onClick={() => onSelect(idx)}
                            className={cn(
                                "h-auto w-full justify-start rounded-2xl px-4 py-3 text-left text-sm font-normal",
                                selected
                                    ? "border-[var(--accent-primary)] bg-[var(--accent-secondary)]/20 text-neutral-900"
                                    : "border-neutral-200 bg-white text-neutral-700 hover:border-neutral-300 hover:bg-neutral-50"
                            )}
                        >
                            <span className="mr-3 font-semibold text-neutral-400">
                                {String.fromCharCode(65 + idx)}.
                            </span>
                            {option}
                        </Button>
                    );
                })}
            </div>
        </motion.div>
    );
}
