"use client";

import { useState, useEffect } from "react";
import { BookContextResponse, booksService } from "@/services/books.service";

interface BookContextFormProps {
    bookId: string;
}

const FIELDS: Array<{
    key: keyof Omit<BookContextResponse, "book_id" | "updated_at">;
    label: string;
    placeholder: string;
    isRadio?: boolean;
    radioOptions?: Array<{ value: string; label: string }>;
}> = [
    {
        key: "why_uploaded",
        label: "Why did you upload this book/PDF?",
        placeholder: "e.g. Preparing for an exam, learning a new topic at work…",
    },
    {
        key: "what_to_achieve",
        label: "What do you want to achieve from it?",
        placeholder: "e.g. Pass my semester exam, build a working understanding of the concepts…",
    },
    {
        key: "complete_or_selected",
        label: "Complete book or selected chapters?",
        placeholder: "",
        isRadio: true,
        radioOptions: [
            { value: "complete", label: "Complete book" },
            { value: "selected", label: "Selected chapters" },
        ],
    },
    {
        key: "important_sections",
        label: "Which sections or topics are most important or difficult for you?",
        placeholder: "e.g. Chapter 3 on thermodynamics, anything involving integration…",
    },
    {
        key: "deadline_and_depth",
        label: "What is your deadline, and how much depth do you want?",
        placeholder: "e.g. Exam in 2 weeks, need a solid working understanding not just overview…",
    },
    {
        key: "follow_or_reorganize",
        label: "Should we follow the document exactly, or reorganize it for optimal learning?",
        placeholder: "",
        isRadio: true,
        radioOptions: [
            { value: "follow", label: "Follow the document exactly" },
            { value: "reorganize", label: "Reorganize for optimal learning" },
        ],
    },
];

type FormValues = {
    why_uploaded: string;
    what_to_achieve: string;
    complete_or_selected: string;
    important_sections: string;
    deadline_and_depth: string;
    follow_or_reorganize: string;
};

const EMPTY: FormValues = {
    why_uploaded: "",
    what_to_achieve: "",
    complete_or_selected: "",
    important_sections: "",
    deadline_and_depth: "",
    follow_or_reorganize: "",
};

export function BookContextForm({ bookId }: BookContextFormProps) {
    const [dismissed, setDismissed] = useState(false);
    const [values, setValues] = useState<FormValues>(EMPTY);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [savedAt, setSavedAt] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        setDismissed(false);
        setValues(EMPTY);
        setSavedAt(null);
        setError(null);
        setLoading(true);
    }, [bookId]);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const ctx = await booksService.getBookContext(bookId);
                if (!cancelled && ctx) {
                    setValues({
                        why_uploaded: ctx.why_uploaded ?? "",
                        what_to_achieve: ctx.what_to_achieve ?? "",
                        complete_or_selected: ctx.complete_or_selected ?? "",
                        important_sections: ctx.important_sections ?? "",
                        deadline_and_depth: ctx.deadline_and_depth ?? "",
                        follow_or_reorganize: ctx.follow_or_reorganize ?? "",
                    });
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

    const handleSave = async () => {
        setSaving(true);
        setError(null);
        try {
            const saved = await booksService.upsertBookContext(bookId, {
                why_uploaded: values.why_uploaded || null,
                what_to_achieve: values.what_to_achieve || null,
                complete_or_selected: values.complete_or_selected || null,
                important_sections: values.important_sections || null,
                deadline_and_depth: values.deadline_and_depth || null,
                follow_or_reorganize: values.follow_or_reorganize || null,
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
            <div className="mb-4 flex items-start justify-between gap-4">
                <div>
                    <h2 className="text-base font-semibold text-neutral-900">
                        Tell us about this book
                    </h2>
                    <p className="mt-0.5 text-sm text-neutral-500">
                        Optional — helps us personalise every lesson we generate from it.
                    </p>
                </div>
                <a
                    role="button"
                    tabIndex={0}
                    onClick={() => setDismissed(true)}
                    onKeyDown={(e) => e.key === "Enter" && setDismissed(true)}
                    className="shrink-0 cursor-pointer text-sm text-neutral-400 hover:text-neutral-600 transition-colors"
                >
                    Skip for now
                </a>
            </div>

            <div className="space-y-4">
                {FIELDS.map((field) => (
                    <div key={field.key}>
                        <label className="block text-sm font-medium text-neutral-700 mb-1.5">
                            {field.label}
                        </label>
                        {field.isRadio && field.radioOptions ? (
                            <div className="flex gap-4">
                                {field.radioOptions.map((opt) => (
                                    <label
                                        key={opt.value}
                                        className="flex items-center gap-2 cursor-pointer text-sm text-neutral-700"
                                    >
                                        <input
                                            type="radio"
                                            name={field.key}
                                            value={opt.value}
                                            checked={values[field.key] === opt.value}
                                            onChange={() =>
                                                setValues((v) => ({ ...v, [field.key]: opt.value }))
                                            }
                                            className="accent-[var(--accent-primary)]"
                                        />
                                        {opt.label}
                                    </label>
                                ))}
                            </div>
                        ) : (
                            <textarea
                                rows={2}
                                maxLength={500}
                                placeholder={field.placeholder}
                                value={values[field.key]}
                                onChange={(e) =>
                                    setValues((v) => ({ ...v, [field.key]: e.target.value }))
                                }
                                className="w-full resize-none rounded-xl border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm text-neutral-800 placeholder:text-neutral-400 focus:border-[var(--accent-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--accent-primary)]"
                            />
                        )}
                    </div>
                ))}
            </div>

            <div className="mt-4 flex items-center gap-4">
                <button
                    onClick={handleSave}
                    disabled={saving}
                    className="rounded-xl bg-[var(--accent-primary)] px-4 py-2 text-sm font-medium text-white hover:opacity-90 transition-opacity disabled:opacity-50"
                >
                    {saving ? "Saving…" : "Save"}
                </button>
                {savedAt && !error && (
                    <span className="text-xs text-neutral-400">
                        Saved
                    </span>
                )}
                {error && (
                    <span className="text-xs text-red-500">{error}</span>
                )}
            </div>
        </div>
    );
}
