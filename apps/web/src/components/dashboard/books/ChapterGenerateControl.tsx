"use client";

import { useState } from "react";
import { AlertCircle, Check, Info, Loader2, Sparkles, X } from "lucide-react";
// Reused verbatim from S2-07. NOT copied, NOT forked, and its props are
// unchanged (`{ onSelect }`) -- W3 AC2. It still lives under `upload/` because
// that is where S2-07 put it and moving a file W3 does not own would be a
// gratuitous conflict; the component itself has nothing upload-specific in it.
import { ModeSelection } from "@/components/dashboard/upload/ModeSelection";
import { LEARNER_TIER_TO_BACKEND, type LearnerTier } from "@/types/learnerMode";
import {
    booksService,
    generateLessonErrorMessage,
    type ChapterResponse,
    type LessonGenerationResponse,
} from "@/services/books.service";

/**
 * `truncation_expected` in prose (AC5). Said at GENERATION time, before the
 * student waits ~15 minutes for a lesson built from part of their chapter --
 * and said as a warning, not an error, because the request WAS accepted.
 */
export const TRUNCATION_WARNING =
    "This chapter is longer than we can read in one pass, so this lesson will cover part of it, " +
    "not all of it. It will still be generated.";

/** AC3: a 200 is not a second 202, and must never be reported as new work. */
export const ALREADY_GENERATING_MESSAGE =
    "You're already generating this chapter at that depth — we didn't start a second one. " +
    "Give the first one time to finish.";

export const ALREADY_READY_MESSAGE =
    "You've already generated this chapter at that depth, and it's ready to watch.";

export const GENERATION_STARTED_MESSAGE =
    "We've started building this lesson. It takes a few minutes — this page updates on its own.";

type Phase =
    | { kind: "idle" }
    | { kind: "choosing" }
    | { kind: "submitting" }
    /** 202 -- a lesson row was created and a job enqueued. */
    | { kind: "created"; lesson: LessonGenerationResponse }
    /** 200 -- an equivalent lesson already existed. Nothing was created. */
    | { kind: "existing"; lesson: LessonGenerationResponse }
    | { kind: "error"; message: string };

interface ChapterGenerateControlProps {
    bookId: string;
    chapter: ChapterResponse;
    /** Called after any successful response so the card can re-read the server. */
    onGenerated?: () => void;
}

/**
 * The Generate control for one chapter card.
 *
 * Renders a FRAGMENT of two siblings so it can sit inside `ChapterRow`'s
 * wrapping flex row: the action button (a shrink-0 cell in the row) and, when
 * open, a full-width panel below it.
 *
 * `"use client"` is load-bearing, not decoration: `lib/api.ts`'s auth
 * interceptor only attaches an `Authorization` header in the browser, so an RSC
 * would send this POST unauthenticated.
 */
export function ChapterGenerateControl({
    bookId,
    chapter,
    onGenerated,
}: ChapterGenerateControlProps) {
    const [phase, setPhase] = useState<Phase>({ kind: "idle" });

    // A chapter whose only lesson FAILED is offered Retry, not Watch -- the
    // Watch gate (`watchableLessonId`) is untouched by this story (AC7).
    const isRetry = chapter.latest_lesson?.status === "failed";

    async function handleSelect(tier: LearnerTier) {
        // The single tier mapping. There is no second copy of this anywhere.
        const backendTier = LEARNER_TIER_TO_BACKEND[tier];
        setPhase({ kind: "submitting" });
        try {
            const { created, lesson } = await booksService.generateLesson(
                bookId,
                chapter.chapter_id,
                backendTier,
            );
            setPhase({ kind: created ? "created" : "existing", lesson });
            // Revalidate on BOTH success paths: a 200 means the server already
            // knows something this card may not (AC6). Never optimistic -- the
            // card's status comes from `latest_lesson.status`.
            onGenerated?.();
        } catch (error) {
            // No automatic retry, ever. The endpoint is 3/minute and 20/hour per
            // user with a 3-concurrent cap; a retry loop here spends the
            // student's budget and locks them out of their own book.
            setPhase({ kind: "error", message: generateLessonErrorMessage(error) });
        }
    }

    const truncated =
        (phase.kind === "created" || phase.kind === "existing") &&
        phase.lesson.truncation_expected;

    return (
        <>
            <div className="flex shrink-0 items-center gap-2">
                {phase.kind === "idle" || phase.kind === "error" ? (
                    <button
                        type="button"
                        onClick={() => setPhase({ kind: "choosing" })}
                        className="inline-flex items-center gap-2 rounded-full border border-neutral-200 px-4 py-2 text-sm text-neutral-700 transition-colors hover:border-[var(--accent-primary)] hover:text-[var(--accent-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)]"
                    >
                        <Sparkles className="h-4 w-4" />
                        {phase.kind === "error" ? "Try again" : isRetry ? "Retry" : "Generate"}
                    </button>
                ) : phase.kind === "choosing" ? (
                    <button
                        type="button"
                        onClick={() => setPhase({ kind: "idle" })}
                        className="inline-flex items-center gap-2 rounded-full border border-neutral-200 px-4 py-2 text-sm text-neutral-500 transition-colors hover:text-neutral-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)]"
                    >
                        <X className="h-4 w-4" />
                        Cancel
                    </button>
                ) : phase.kind === "submitting" ? (
                    <span className="inline-flex items-center gap-2 rounded-full bg-neutral-100 px-4 py-2 text-sm text-neutral-500">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        Starting…
                    </span>
                ) : (
                    // created | existing -- the same affordance for both, because
                    // the same chapter at a DIFFERENT tier is deliberately a new
                    // lesson, and re-picking the SAME tier is the honest way to
                    // reach the 200 path rather than a second spinner.
                    <button
                        type="button"
                        onClick={() => setPhase({ kind: "choosing" })}
                        className="inline-flex items-center gap-2 rounded-full border border-neutral-200 px-4 py-2 text-sm text-neutral-500 transition-colors hover:text-neutral-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)]"
                    >
                        <Sparkles className="h-4 w-4" />
                        Generate at a different depth
                    </button>
                )}
            </div>

            {phase.kind === "choosing" && (
                <div className="w-full basis-full border-t border-neutral-100 pt-4">
                    <p className="mb-4 text-sm text-neutral-500">
                        How deep should this lesson go?
                    </p>
                    <ModeSelection onSelect={handleSelect} />
                </div>
            )}

            {phase.kind === "error" && (
                <div
                    role="alert"
                    className="flex w-full basis-full items-start gap-2 rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-600"
                >
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>{phase.message}</span>
                </div>
            )}

            {(phase.kind === "created" || phase.kind === "existing") && (
                <div className="flex w-full basis-full flex-col gap-2">
                    <div
                        role="status"
                        className="flex items-start gap-2 rounded-2xl border border-neutral-100 bg-neutral-50 px-4 py-3 text-sm text-neutral-600"
                    >
                        <Check className="mt-0.5 h-4 w-4 shrink-0" />
                        <span>
                            {phase.kind === "created"
                                ? GENERATION_STARTED_MESSAGE
                                : phase.lesson.status === "ready"
                                  ? ALREADY_READY_MESSAGE
                                  : ALREADY_GENERATING_MESSAGE}
                        </span>
                    </div>

                    {truncated && (
                        <div
                            role="status"
                            className="flex items-start gap-2 rounded-2xl border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-700"
                        >
                            <Info className="mt-0.5 h-4 w-4 shrink-0" />
                            <span>
                                <span className="sr-only">Warning: </span>
                                {TRUNCATION_WARNING}
                            </span>
                        </div>
                    )}
                </div>
            )}
        </>
    );
}
