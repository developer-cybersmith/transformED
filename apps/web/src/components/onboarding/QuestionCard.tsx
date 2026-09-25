"use client";

import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useRovingRadioGroup } from "@/hooks/useRovingRadioGroup";
import type { Question } from "./questions";

// Story 235: mirrors the backend's 3-format OnboardingAnswer shape
// (apps/api/app/modules/assessment/schemas.py) -- one variant per question
// format, discriminated on `format` so a stale index/text/value from a
// previously-answered different-format question can never leak through.
export type AnswerValue =
    | { format: "mcq"; index: number }
    | { format: "one_liner"; text: string }
    | { format: "true_false"; value: boolean };

export interface QuestionCardProps {
    question: Question;
    value: AnswerValue | undefined;
    onChange: (value: AnswerValue) => void;
}

const ONE_LINER_MAX_LENGTH = 1000;

export function QuestionCard({ question, value, onChange }: QuestionCardProps) {
    return (
        <motion.div
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -16 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            className="rounded-2xl border border-neutral-100 bg-white p-8 shadow-sm"
        >
            <p className="mb-6 text-base font-medium text-neutral-900">{question.text}</p>

            {question.format === "mcq" && (
                <McqOptions
                    options={question.options ?? []}
                    questionText={question.text}
                    selectedIndex={value?.format === "mcq" ? value.index : undefined}
                    onSelect={(index) => onChange({ format: "mcq", index })}
                />
            )}

            {question.format === "true_false" && (
                <TrueFalseOptions
                    questionText={question.text}
                    selectedValue={value?.format === "true_false" ? value.value : undefined}
                    onSelect={(v) => onChange({ format: "true_false", value: v })}
                />
            )}

            {question.format === "one_liner" && (
                <OneLinerInput
                    placeholder={question.placeholder}
                    text={value?.format === "one_liner" ? value.text : ""}
                    onChange={(text) => onChange({ format: "one_liner", text })}
                />
            )}
        </motion.div>
    );
}

function McqOptions({
    options,
    questionText,
    selectedIndex,
    onSelect,
}: {
    options: string[];
    questionText: string;
    selectedIndex: number | undefined;
    onSelect: (index: number) => void;
}) {
    const { setItemRef, handleKeyDown, getTabIndex } = useRovingRadioGroup({
        optionCount: options.length,
        selectedIndex: selectedIndex ?? null,
        onSelect,
    });

    return (
        <div role="radiogroup" aria-label={questionText} className="space-y-3">
            {options.map((option, idx) => {
                const selected = selectedIndex === idx;
                return (
                    <Button
                        key={idx}
                        ref={setItemRef(idx)}
                        type="button"
                        variant="outline"
                        role="radio"
                        aria-checked={selected}
                        tabIndex={getTabIndex(idx)}
                        onClick={() => onSelect(idx)}
                        onKeyDown={(e) => handleKeyDown(e, idx)}
                        className={cn(
                            "h-auto w-full justify-start rounded-2xl px-4 py-3 text-left text-sm font-normal",
                            selected
                                ? "border-[var(--accent-primary)] bg-[var(--accent-secondary)]/20 text-neutral-900"
                                : "border-neutral-200 bg-white text-neutral-700 hover:border-neutral-300 hover:bg-neutral-50"
                        )}
                    >
                        <span className="mr-3 font-semibold text-neutral-600">
                            {String.fromCharCode(65 + idx)}.
                        </span>
                        {option}
                    </Button>
                );
            })}
        </div>
    );
}

// Story 235 (AC8): reuses the identical useRovingRadioGroup pattern the MCQ
// branch already uses (optionCount: 2) rather than inventing a second
// roving-focus implementation for what is, mechanically, a 2-option radio
// group.
function TrueFalseOptions({
    questionText,
    selectedValue,
    onSelect,
}: {
    questionText: string;
    selectedValue: boolean | undefined;
    onSelect: (value: boolean) => void;
}) {
    const OPTIONS: readonly [string, boolean][] = [
        ["True", true],
        ["False", false],
    ];
    const selectedIndex = selectedValue === undefined ? null : selectedValue ? 0 : 1;

    const { setItemRef, handleKeyDown, getTabIndex } = useRovingRadioGroup({
        optionCount: OPTIONS.length,
        selectedIndex,
        onSelect: (idx) => onSelect(OPTIONS[idx][1]),
    });

    return (
        <div role="radiogroup" aria-label={questionText} className="flex gap-3">
            {OPTIONS.map(([label, optValue], idx) => {
                const selected = selectedValue === optValue;
                return (
                    <Button
                        key={label}
                        ref={setItemRef(idx)}
                        type="button"
                        variant="outline"
                        role="radio"
                        aria-checked={selected}
                        tabIndex={getTabIndex(idx)}
                        onClick={() => onSelect(optValue)}
                        onKeyDown={(e) => handleKeyDown(e, idx)}
                        className={cn(
                            "h-auto flex-1 rounded-2xl px-4 py-3 text-sm font-medium",
                            selected
                                ? "border-[var(--accent-primary)] bg-[var(--accent-secondary)]/20 text-neutral-900"
                                : "border-neutral-200 bg-white text-neutral-700 hover:border-neutral-300 hover:bg-neutral-50"
                        )}
                    >
                        {label}
                    </Button>
                );
            })}
        </div>
    );
}

// Story 235 (AC8): free-text one-liner, 1000-char cap matching the backend's
// OnboardingAnswer.response_text Field(max_length=1000), with a visible
// counter. Blank/whitespace-only text is never treated as "answered" --
// enforced by the parent's canProceed check (OnboardingFlow.tsx), not here.
function OneLinerInput({
    placeholder,
    text,
    onChange,
}: {
    placeholder: string | undefined;
    text: string;
    onChange: (text: string) => void;
}) {
    return (
        <div>
            <textarea
                value={text}
                onChange={(e) => onChange(e.target.value.slice(0, ONE_LINER_MAX_LENGTH))}
                placeholder={placeholder}
                rows={4}
                maxLength={ONE_LINER_MAX_LENGTH}
                className="w-full resize-none rounded-2xl border border-neutral-200 bg-white px-4 py-3 text-sm text-neutral-900 placeholder:text-neutral-400 focus:border-[var(--accent-primary)] focus:outline-none focus-visible:ring-4 focus-visible:ring-[var(--accent-primary)]/20"
            />
            <div className="mt-1.5 text-right text-xs text-neutral-400">
                {text.length}/{ONE_LINER_MAX_LENGTH}
            </div>
        </div>
    );
}
