"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import {
    booksService,
    type ChapterContextRequest,
    type DepthDurationValue,
    type LearningNeedValue,
} from "@/services/books.service";

// ── Option definitions (§4.3 questions) ──────────────────────────────────────

const DEPTH_OPTIONS: { value: DepthDurationValue; label: string }[] = [
    { value: "quick_15_20m",      label: "Quick (15–20 min)" },
    { value: "standard_30_45m",   label: "Standard (30–45 min)" },
    { value: "deep_60_90m",       label: "Deep dive (60–90 min)" },
    { value: "mastery_multi",     label: "Full mastery (multiple sessions)" },
    { value: "ai_decide",         label: "Let AI decide" },
];

const LEARNING_NEED_OPTIONS: { value: LearningNeedValue; label: string }[] = [
    { value: "examples_analogies",   label: "Examples & analogies" },
    { value: "formulas_derivations", label: "Formulas & derivations" },
    { value: "diagrams_visuals",     label: "Diagrams & visuals" },
    { value: "practice_questions",   label: "Practice questions" },
    { value: "adaptive_mix",         label: "Adaptive mix (AI decides)" },
];

// ── Sub-components ────────────────────────────────────────────────────────────

function ChipGroup<T extends string>({
    options,
    value,
    onChange,
}: {
    options: { value: T; label: string }[];
    value: T | null;
    onChange: (v: T | null) => void;
}) {
    return (
        <div className="flex flex-wrap gap-2">
            {options.map((opt) => {
                const selected = opt.value === value;
                return (
                    <button
                        key={opt.value}
                        type="button"
                        onClick={() => onChange(selected ? null : opt.value)}
                        className={`rounded-full border px-3 py-1 text-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)] ${
                            selected
                                ? "border-[var(--accent-primary)] bg-[var(--accent-primary)] text-white"
                                : "border-neutral-200 text-neutral-700 hover:border-[var(--accent-primary)] hover:text-[var(--accent-primary)]"
                        }`}
                    >
                        {opt.label}
                    </button>
                );
            })}
        </div>
    );
}

function TrueFalseToggle({
    value,
    onChange,
}: {
    value: boolean | null;
    onChange: (v: boolean | null) => void;
}) {
    return (
        <div className="flex gap-2">
            {([true, false] as const).map((bool) => {
                const label = bool ? "Yes" : "No";
                const selected = value === bool;
                return (
                    <button
                        key={label}
                        type="button"
                        onClick={() => onChange(selected ? null : bool)}
                        className={`rounded-full border px-4 py-1 text-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)] ${
                            selected
                                ? "border-[var(--accent-primary)] bg-[var(--accent-primary)] text-white"
                                : "border-neutral-200 text-neutral-700 hover:border-[var(--accent-primary)] hover:text-[var(--accent-primary)]"
                        }`}
                    >
                        {label}
                    </button>
                );
            })}
        </div>
    );
}

// ── Form state ────────────────────────────────────────────────────────────────

interface FormState {
    depth_duration: DepthDurationValue | null;
    learning_need: LearningNeedValue | null;
    specific_doubt: string;
    goal_and_skip: string;
    prerequisites_done: boolean | null;
}

const EMPTY_FORM: FormState = {
    depth_duration: null,
    learning_need: null,
    specific_doubt: "",
    goal_and_skip: "",
    prerequisites_done: null,
};

// ── Main component ────────────────────────────────────────────────────────────

interface ChapterContextFormProps {
    bookId: string;
    chapterId: string;
    /** Called when the student clicks "Generate Now" — after saving context.
     *  force is true only when form context changed since last fetch/generation (isDirty). */
    onGenerate: (force: boolean) => void;
    /** Called when the student clicks "Skip" — no save, just generate. */
    onSkip: () => void;
}

export function ChapterContextForm({
    bookId,
    chapterId,
    onGenerate,
    onSkip,
}: ChapterContextFormProps) {
    const [form, setForm] = useState<FormState>(EMPTY_FORM);
    // savedContext tracks the last values that were fetched from the server (or
    // successfully PUT). null means no context has been fetched yet (new chapter
    // or fetch failed). Used to compute isDirty so we only send force:true when
    // context actually changed since the last generation.
    const [savedContext, setSavedContext] = useState<FormState | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    // generatingRef: re-entrancy guard — prevents a double-click race where two
    // near-simultaneous clicks both read the pre-PUT savedContext, both compute
    // isDirty=true, and both fire force:true (landing on the unguarded D45 gate).
    const generatingRef = useRef(false);
    // mountedRef: unmount guard — prevents calling onGenerate or setting state
    // after the component unmounts (e.g. the student navigates away while the
    // PUT is in flight).
    const mountedRef = useRef(true);

    // Set mountedRef to false on unmount so in-flight PUT callbacks are no-ops.
    useEffect(() => {
        return () => {
            mountedRef.current = false;
        };
    }, []);

    // Pre-populate from existing chapter context on mount.
    useEffect(() => {
        let cancelled = false;

        async function fetchContext() {
            setLoading(true);
            // AbortController cancels the inflight request when the 5 s timeout
            // fires — without this, the server still processes the full GET even
            // after the client has moved on to rendering an empty form.
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 5000);
            try {
                const row = await booksService.getChapterContext(
                    bookId,
                    chapterId,
                    controller.signal
                );
                clearTimeout(timeoutId);
                if (cancelled) return;
                if (row) {
                    const fetched: FormState = {
                        depth_duration: (row.depth_duration as DepthDurationValue) ?? null,
                        learning_need: (row.learning_need as LearningNeedValue) ?? null,
                        specific_doubt: row.specific_doubt ?? "",
                        goal_and_skip: row.goal_and_skip ?? "",
                        prerequisites_done: row.prerequisites_done ?? null,
                    };
                    setForm(fetched);
                    setSavedContext(fetched);
                }
            } catch {
                // Abort (timeout), network failure, or parse error — all non-fatal:
                // form stays empty and the student can proceed.
                clearTimeout(timeoutId);
            } finally {
                if (!cancelled) setLoading(false);
            }
        }

        void fetchContext();
        return () => { cancelled = true; };
    }, [bookId, chapterId]);

    function set<K extends keyof FormState>(key: K, value: FormState[K]) {
        setForm((prev) => ({ ...prev, [key]: value }));
    }

    async function handleGenerateNow() {
        // Re-entrancy guard: drop any double-click that arrives while a PUT is in
        // flight (disabled={saving} is React state and can race on rapid clicks).
        if (generatingRef.current) return;
        generatingRef.current = true;
        setSaving(true);

        // isDirty: true when context changed from what the backend last saw.
        // savedContext===null means no prior context exists (new chapter or fetch
        // failed) — always treat as dirty so generation proceeds with force:true.
        const isDirty =
            savedContext === null ||
            form.depth_duration !== savedContext.depth_duration ||
            form.learning_need !== savedContext.learning_need ||
            (form.specific_doubt || null) !== (savedContext.specific_doubt || null) ||
            (form.goal_and_skip || null) !== (savedContext.goal_and_skip || null) ||
            form.prerequisites_done !== savedContext.prerequisites_done;
        const body: ChapterContextRequest = {
            depth_duration: form.depth_duration,
            learning_need: form.learning_need,
            specific_doubt: form.specific_doubt || null,
            goal_and_skip: form.goal_and_skip || null,
            prerequisites_done: form.prerequisites_done,
        };
        // AbortController lets us cancel the PUT if it hangs (10 s timeout).
        const controller = new AbortController();
        const putTimeoutId = setTimeout(() => controller.abort(), 10_000);
        try {
            await booksService.putChapterContext(bookId, chapterId, body, controller.signal);
            clearTimeout(putTimeoutId);
            // PUT succeeded — update savedContext so the next Generate Now click
            // without further edits correctly sends force:false (no redundant regen).
            if (mountedRef.current) setSavedContext({ ...form });
        } catch {
            clearTimeout(putTimeoutId);
            // Save failure or PUT timeout is non-fatal — lesson generation still
            // proceeds. savedContext is NOT updated: the backend still has the old
            // context, so isDirty remains correct on the next click.
            if (mountedRef.current) {
                console.warn("[ChapterContextForm] putChapterContext failed — continuing with generate");
            }
        } finally {
            if (mountedRef.current) setSaving(false);
            generatingRef.current = false;
        }
        if (mountedRef.current) onGenerate(isDirty);
    }

    if (loading) {
        return (
            <div className="flex items-center gap-2 py-6 text-sm text-neutral-400">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading…
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-5">
            <p className="text-sm font-medium text-neutral-700">
                Tell us about this chapter <span className="font-normal text-neutral-400">(all optional)</span>
            </p>

            {/* Q41: Depth and time */}
            <div className="flex flex-col gap-2">
                <label className="text-sm text-neutral-600">
                    How deep do you want to go, and how long do you have?
                </label>
                <ChipGroup
                    options={DEPTH_OPTIONS}
                    value={form.depth_duration}
                    onChange={(v) => set("depth_duration", v)}
                />
            </div>

            {/* Q42: Learning need */}
            <div className="flex flex-col gap-2">
                <label className="text-sm text-neutral-600">
                    What do you need most from this lesson?
                </label>
                <ChipGroup
                    options={LEARNING_NEED_OPTIONS}
                    value={form.learning_need}
                    onChange={(v) => set("learning_need", v)}
                />
            </div>

            {/* Q43: Specific doubt */}
            <div className="flex flex-col gap-2">
                <label className="text-sm text-neutral-600">
                    Any specific doubt or topic you want clarified?
                </label>
                <input
                    type="text"
                    maxLength={500}
                    value={form.specific_doubt}
                    onChange={(e) => set("specific_doubt", e.target.value)}
                    placeholder="e.g. Why does the chain rule work for composite functions?"
                    className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm text-neutral-800 placeholder:text-neutral-400 focus:border-[var(--accent-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-primary)]"
                />
            </div>

            {/* Q44: Goal and skip */}
            <div className="flex flex-col gap-2">
                <label className="text-sm text-neutral-600">
                    By the end, what should you be able to do? Any topics to skip?
                </label>
                <input
                    type="text"
                    maxLength={500}
                    value={form.goal_and_skip}
                    onChange={(e) => set("goal_and_skip", e.target.value)}
                    placeholder="e.g. Solve related-rates problems. Skip: historical proofs."
                    className="w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm text-neutral-800 placeholder:text-neutral-400 focus:border-[var(--accent-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-primary)]"
                />
            </div>

            {/* Q45: Prerequisites done */}
            <div className="flex flex-col gap-2">
                <label className="text-sm text-neutral-600">
                    Have you completed the prerequisites for this chapter?
                </label>
                <TrueFalseToggle
                    value={form.prerequisites_done}
                    onChange={(v) => set("prerequisites_done", v)}
                />
            </div>

            {/* Actions */}
            <div className="flex items-center gap-4 border-t border-neutral-100 pt-4">
                <button
                    type="button"
                    disabled={saving}
                    onClick={handleGenerateNow}
                    className="inline-flex items-center gap-2 rounded-full bg-[var(--accent-primary)] px-5 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)]"
                >
                    {saving ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                        <Sparkles className="h-4 w-4" />
                    )}
                    Generate Now
                </button>
                <button
                    type="button"
                    onClick={onSkip}
                    className="text-sm text-neutral-400 hover:text-neutral-600 focus:outline-none focus-visible:underline"
                >
                    Skip
                </button>
            </div>
        </div>
    );
}
