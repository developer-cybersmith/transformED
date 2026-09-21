"use client";

import { useState, useEffect } from "react";
import {
    BookContextResponse,
    CoverageValue,
    DeadlineValue,
    DifficultyValue,
    PurposeValue,
    StructureValue,
    booksService,
} from "@/services/books.service";

interface BookContextFormProps {
    bookId: string;
}

// ── §4.2 MCQ option definitions ──────────────────────────────────────────────

const PURPOSE_OPTIONS: Array<{ value: PurposeValue; label: string }> = [
    { value: "exam_prep", label: "Exam prep" },
    { value: "project_job", label: "Project / job requirement" },
    { value: "deep_mastery", label: "Deep mastery" },
    { value: "quick_reference", label: "Quick reference" },
    { value: "recommended_reading", label: "Recommended reading" },
];

const COVERAGE_OPTIONS: Array<{ value: CoverageValue; label: string }> = [
    { value: "complete_book", label: "Complete book" },
    { value: "selected_chapters", label: "Selected chapters" },
    { value: "difficult_sections", label: "Difficult sections only" },
    { value: "exam_relevant", label: "Exam-relevant parts" },
    { value: "ai_decide", label: "Let AI decide" },
];

const DIFFICULTY_OPTIONS: Array<{ value: DifficultyValue; label: string }> = [
    { value: "theory_heavy", label: "Theory-heavy sections" },
    { value: "numerical_formula", label: "Numerical / formula" },
    { value: "case_studies", label: "Case studies" },
    { value: "dense_language", label: "Dense language" },
    { value: "dont_know", label: "I don't know — find them" },
];

const DEADLINE_OPTIONS: Array<{ value: DeadlineValue; label: string }> = [
    { value: "urgent_2wk", label: "Urgent < 2 weeks" },
    { value: "one_month", label: "1 month" },
    { value: "two_three_months", label: "2–3 months" },
    { value: "no_deadline", label: "No deadline" },
    { value: "key_insights_only", label: "Just key insights" },
];

const STRUCTURE_OPTIONS: Array<{ value: StructureValue; label: string }> = [
    { value: "follow_exactly", label: "Follow exactly" },
    { value: "reorganise_by_difficulty", label: "Reorganise by concept difficulty" },
    { value: "reorganise_by_goal", label: "Reorganise by goal" },
    { value: "hybrid", label: "Hybrid" },
    { value: "ai_choose", label: "Let AI choose" },
];

// ── Form state ────────────────────────────────────────────────────────────────

type FormValues = {
    purpose: PurposeValue | "";
    coverage_scope: CoverageValue | "";
    expected_difficulty: DifficultyValue | "";
    deadline_depth: DeadlineValue | "";
    structure_preference: StructureValue | "";
    motivation: string;
    end_goal: string;
    feared_section: string;
    prior_attempt: boolean | null;
    outcome_clarity: boolean | null;
};

const EMPTY: FormValues = {
    purpose: "",
    coverage_scope: "",
    expected_difficulty: "",
    deadline_depth: "",
    structure_preference: "",
    motivation: "",
    end_goal: "",
    feared_section: "",
    prior_attempt: null,
    outcome_clarity: null,
};

function fromResponse(ctx: BookContextResponse): FormValues {
    return {
        purpose: (ctx.purpose as PurposeValue) ?? "",
        coverage_scope: (ctx.coverage_scope as CoverageValue) ?? "",
        expected_difficulty: (ctx.expected_difficulty as DifficultyValue) ?? "",
        deadline_depth: (ctx.deadline_depth as DeadlineValue) ?? "",
        structure_preference: (ctx.structure_preference as StructureValue) ?? "",
        motivation: ctx.motivation ?? "",
        end_goal: ctx.end_goal ?? "",
        feared_section: ctx.feared_section ?? "",
        prior_attempt: ctx.prior_attempt ?? null,
        outcome_clarity: ctx.outcome_clarity ?? null,
    };
}

// ── Sub-components ────────────────────────────────────────────────────────────

function RadioGroup<T extends string>({
    name,
    options,
    value,
    onChange,
}: {
    name: string;
    options: Array<{ value: T; label: string }>;
    value: T | "";
    onChange: (v: T) => void;
}) {
    return (
        <div className="flex flex-wrap gap-2 mt-1.5">
            {options.map((opt) => (
                <label
                    key={opt.value}
                    className={`flex items-center gap-1.5 cursor-pointer rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                        value === opt.value
                            ? "border-[var(--accent-primary)] bg-[var(--accent-primary)]/10 text-[var(--accent-primary)] font-medium"
                            : "border-neutral-200 text-neutral-600 hover:border-neutral-300"
                    }`}
                >
                    <input
                        type="radio"
                        name={name}
                        value={opt.value}
                        checked={value === opt.value}
                        onChange={() => onChange(opt.value)}
                        className="sr-only"
                    />
                    {opt.label}
                </label>
            ))}
        </div>
    );
}

function TrueFalseToggle({
    value,
    onChange,
}: {
    value: boolean | null;
    onChange: (v: boolean) => void;
}) {
    return (
        <div className="flex gap-2 mt-1.5">
            {[true, false].map((bool) => (
                <button
                    key={String(bool)}
                    type="button"
                    onClick={() => onChange(bool)}
                    className={`rounded-lg border px-4 py-1.5 text-xs transition-colors ${
                        value === bool
                            ? "border-[var(--accent-primary)] bg-[var(--accent-primary)]/10 text-[var(--accent-primary)] font-medium"
                            : "border-neutral-200 text-neutral-600 hover:border-neutral-300"
                    }`}
                >
                    {bool ? "True" : "False"}
                </button>
            ))}
        </div>
    );
}

// ── Main component ────────────────────────────────────────────────────────────

export function BookContextForm({ bookId }: BookContextFormProps) {
    const [dismissed, setDismissed] = useState(false);
    const [values, setValues] = useState<FormValues>(EMPTY);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [savedAt, setSavedAt] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    // Reset dismissed state when bookId changes so a new book always shows the form.
    useEffect(() => {
        setDismissed(false);
    }, [bookId]);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        (async () => {
            try {
                const ctx = await booksService.getBookContext(bookId);
                if (!cancelled && ctx) {
                    setValues(fromResponse(ctx));
                    if (ctx.updated_at) setSavedAt(ctx.updated_at);
                }
            } catch {
                // No context saved yet — form stays empty.
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => { cancelled = true; };
    }, [bookId]);

    const set = <K extends keyof FormValues>(key: K, val: FormValues[K]) =>
        setValues((v) => ({ ...v, [key]: val }));

    const handleSave = async () => {
        setSaving(true);
        setError(null);
        try {
            const saved = await booksService.upsertBookContext(bookId, {
                purpose: values.purpose || null,
                coverage_scope: values.coverage_scope || null,
                expected_difficulty: values.expected_difficulty || null,
                deadline_depth: values.deadline_depth || null,
                structure_preference: values.structure_preference || null,
                motivation: values.motivation || null,
                end_goal: values.end_goal || null,
                feared_section: values.feared_section || null,
                prior_attempt: values.prior_attempt,
                outcome_clarity: values.outcome_clarity,
            });
            if (saved.updated_at) setSavedAt(saved.updated_at);
        } catch {
            setError("Couldn't save — please try again.");
        } finally {
            setSaving(false);
        }
    };

    if (dismissed) return null;
    if (loading) return null;

    return (
        <div className="mb-8 rounded-2xl border border-neutral-100 bg-white/80 px-6 py-5">
            {/* Header */}
            <div className="mb-5 flex items-start justify-between gap-4">
                <div>
                    <h2 className="text-base font-semibold text-neutral-900">
                        Tell us about this book
                    </h2>
                    <p className="mt-0.5 text-sm text-neutral-500">
                        Optional — helps personalise every lesson we generate from it.
                    </p>
                </div>
                <button
                    onClick={() => setDismissed(true)}
                    className="shrink-0 text-sm text-neutral-400 hover:text-neutral-600 transition-colors"
                    aria-label="Skip book context form"
                >
                    Skip for now
                </button>
            </div>

            <div className="space-y-5">
                {/* Q31 */}
                <div>
                    <p className="text-sm font-medium text-neutral-700">
                        Why have you uploaded this book / PDF?
                    </p>
                    <RadioGroup
                        name="purpose"
                        options={PURPOSE_OPTIONS}
                        value={values.purpose}
                        onChange={(v) => set("purpose", v)}
                    />
                </div>

                {/* Q32 */}
                <div>
                    <p className="text-sm font-medium text-neutral-700">
                        What do you want covered?
                    </p>
                    <RadioGroup
                        name="coverage_scope"
                        options={COVERAGE_OPTIONS}
                        value={values.coverage_scope}
                        onChange={(v) => set("coverage_scope", v)}
                    />
                </div>

                {/* Q33 */}
                <div>
                    <p className="text-sm font-medium text-neutral-700">
                        Which parts of this book do you expect to be hardest for you?
                    </p>
                    <RadioGroup
                        name="expected_difficulty"
                        options={DIFFICULTY_OPTIONS}
                        value={values.expected_difficulty}
                        onChange={(v) => set("expected_difficulty", v)}
                    />
                </div>

                {/* Q34 */}
                <div>
                    <p className="text-sm font-medium text-neutral-700">
                        Your deadline and depth requirement:
                    </p>
                    <RadioGroup
                        name="deadline_depth"
                        options={DEADLINE_OPTIONS}
                        value={values.deadline_depth}
                        onChange={(v) => set("deadline_depth", v)}
                    />
                </div>

                {/* Q35 */}
                <div>
                    <p className="text-sm font-medium text-neutral-700">
                        Should the tutor follow the book exactly, or reorganise it for learning?
                    </p>
                    <RadioGroup
                        name="structure_preference"
                        options={STRUCTURE_OPTIONS}
                        value={values.structure_preference}
                        onChange={(v) => set("structure_preference", v)}
                    />
                </div>

                {/* Q36 */}
                <div>
                    <label className="block text-sm font-medium text-neutral-700" htmlFor="motivation">
                        Why do you want to learn from this specific book — in one honest line?
                    </label>
                    <input
                        id="motivation"
                        type="text"
                        maxLength={500}
                        placeholder="e.g. I need to pass my machine learning exam next month."
                        value={values.motivation}
                        onChange={(e) => set("motivation", e.target.value)}
                        className="mt-1.5 w-full rounded-xl border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm text-neutral-800 placeholder:text-neutral-400 focus:border-[var(--accent-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-primary)]"
                    />
                </div>

                {/* Q37 */}
                <div>
                    <label className="block text-sm font-medium text-neutral-700" htmlFor="end_goal">
                        What is the end goal once you finish learning this book? What will you be able to DO?
                    </label>
                    <input
                        id="end_goal"
                        type="text"
                        maxLength={500}
                        placeholder="e.g. Build and deploy a neural network from scratch."
                        value={values.end_goal}
                        onChange={(e) => set("end_goal", e.target.value)}
                        className="mt-1.5 w-full rounded-xl border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm text-neutral-800 placeholder:text-neutral-400 focus:border-[var(--accent-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-primary)]"
                    />
                </div>

                {/* Q38 */}
                <div>
                    <label className="block text-sm font-medium text-neutral-700" htmlFor="feared_section">
                        Which section or topic in this book are you most worried about, and why?
                    </label>
                    <input
                        id="feared_section"
                        type="text"
                        maxLength={500}
                        placeholder="e.g. Backpropagation — the maths always loses me."
                        value={values.feared_section}
                        onChange={(e) => set("feared_section", e.target.value)}
                        className="mt-1.5 w-full rounded-xl border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm text-neutral-800 placeholder:text-neutral-400 focus:border-[var(--accent-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-primary)]"
                    />
                </div>

                {/* Q39 */}
                <div>
                    <p className="text-sm font-medium text-neutral-700">
                        I have tried to read this book before and stopped midway.
                    </p>
                    <TrueFalseToggle
                        value={values.prior_attempt}
                        onChange={(v) => set("prior_attempt", v)}
                    />
                </div>

                {/* Q40 */}
                <div>
                    <p className="text-sm font-medium text-neutral-700">
                        I can clearly picture how I will use this knowledge in real life.
                    </p>
                    <TrueFalseToggle
                        value={values.outcome_clarity}
                        onChange={(v) => set("outcome_clarity", v)}
                    />
                </div>
            </div>

            {/* Footer */}
            <div className="mt-5 flex items-center gap-4">
                <button
                    onClick={handleSave}
                    disabled={saving}
                    className="rounded-xl bg-[var(--accent-primary)] px-4 py-2 text-sm font-medium text-white hover:opacity-90 transition-opacity disabled:opacity-50"
                >
                    {saving ? "Saving…" : "Save"}
                </button>
                {savedAt && !error && (
                    <span className="text-xs text-neutral-400">Saved</span>
                )}
                {error && (
                    <span className="text-xs text-red-500">{error}</span>
                )}
            </div>
        </div>
    );
}
