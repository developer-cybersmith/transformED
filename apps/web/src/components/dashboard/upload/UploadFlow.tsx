"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { UploadCloud, CheckCircle, AlertCircle, Loader2, Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { uploadService, extractErrorMessage, MAX_UPLOAD_SIZE_BYTES } from "@/services/upload.service";
import { Button } from "@/components/ui/button";
import { ModeSelection } from "@/components/dashboard/upload/ModeSelection";
import { LEARNER_TIER_OPTIONS, LEARNER_TIER_TO_BACKEND, type LearnerTier } from "@/types/learnerMode";

const POLL_INTERVAL_MS = 5000;
const MAX_CONSECUTIVE_POLL_FAILURES = 3;
// ~20 minutes at one poll per POLL_INTERVAL_MS — chapter generation can take up to
// ~15 minutes (CLAUDE.md §9), so this is a backstop against a stuck/dead worker,
// not a realistic ceiling for a healthy pipeline run.
const MAX_POLL_ATTEMPTS = 240;

export function UploadFlow() {
    const [file, setFile] = useState<File | null>(null);
    const [dragActive, setDragActive] = useState(false);
    const [uploadState, setUploadState] = useState<'idle' | 'selecting-mode' | 'processing' | 'completed' | 'error'>('idle');
    const [statusMessage, setStatusMessage] = useState<string>('');
    const [errorMessage, setErrorMessage] = useState<string>('');
    const [lessonId, setLessonId] = useState<string>('');
    const [selectedTier, setSelectedTier] = useState<LearnerTier | null>(null);

    const router = useRouter();
    const inputRef = useRef<HTMLInputElement>(null);
    // Captures the tier at the moment processing starts, without making it a
    // reactive dependency of the upload effect below — a later selectedTier
    // change (e.g. a mis-click followed by a different card, landing during
    // the exit-animation window) must not re-trigger a second, separately
    // billed upload call (review fix).
    const selectedTierAtUploadRef = useRef<LearnerTier | null>(null);

    const handleDrag = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.type === "dragenter" || e.type === "dragover") {
            setDragActive(true);
        } else if (e.type === "dragleave") {
            setDragActive(false);
        }
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setDragActive(false);
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            handleFile(e.dataTransfer.files[0]);
        }
    };

    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        e.preventDefault();
        if (e.target.files && e.target.files[0]) {
            handleFile(e.target.files[0]);
        }
    };

    const handleFile = (selectedFile: File) => {
        if (selectedFile.size > MAX_UPLOAD_SIZE_BYTES) {
            setFile(null);
            setErrorMessage('File exceeds the 50MB limit — please upload a smaller PDF.');
            setUploadState('error');
            return;
        }
        setFile(selectedFile);
        setUploadState('selecting-mode');
    };

    const handleTierSelect = (tier: LearnerTier) => {
        selectedTierAtUploadRef.current = tier;
        setSelectedTier(tier);
        setUploadState('processing');
        setStatusMessage('Uploading...');
    };

    const handleCancelModeSelection = () => {
        setFile(null);
        setSelectedTier(null);
        // Allows re-selecting the exact same file through the native file
        // dialog afterwards — browsers don't fire a `change` event if the
        // input's FileList is unchanged from last time.
        if (inputRef.current) inputRef.current.value = '';
        setUploadState('idle');
    };

    useEffect(() => {
        if (uploadState !== 'processing' || !file) return;

        let cancelled = false;
        let timeoutHandle: ReturnType<typeof setTimeout> | undefined;
        let consecutiveFailures = 0;
        let attempts = 0;

        // Self-rescheduling (setTimeout after each poll settles) rather than
        // setInterval — guarantees polls never overlap, so a slow response can
        // never race a faster later one and clobber an already-reached terminal
        // state.
        const scheduleNextPoll = (id: string) => {
            timeoutHandle = setTimeout(() => pollStatus(id), POLL_INTERVAL_MS);
        };

        const pollStatus = async (id: string) => {
            if (cancelled) return;
            attempts += 1;

            try {
                const status = await uploadService.getLessonStatus(id);
                if (cancelled) return;
                consecutiveFailures = 0;

                if (status.status === 'ready') {
                    setUploadState('completed');
                    setLessonId(status.lesson_id);
                    return;
                }
                if (status.status === 'failed') {
                    setUploadState('error');
                    setErrorMessage(status.error ?? 'Lesson generation failed — please try again.');
                    return;
                }
                if (status.status !== 'queued' && status.status !== 'running') {
                    console.warn(`Unexpected lesson status: ${status.status}`);
                }
                if (attempts >= MAX_POLL_ATTEMPTS) {
                    setUploadState('error');
                    setErrorMessage('Lesson generation is taking longer than expected — please try again later.');
                    return;
                }
                setStatusMessage('Processing...');
                scheduleNextPoll(id);
            } catch (err) {
                if (cancelled) return;
                const httpStatus = (err as { response?: { status?: number } })?.response?.status;
                const isClientError = typeof httpStatus === 'number' && httpStatus >= 400 && httpStatus < 500;
                consecutiveFailures += 1;

                if (isClientError || consecutiveFailures >= MAX_CONSECUTIVE_POLL_FAILURES || attempts >= MAX_POLL_ATTEMPTS) {
                    setUploadState('error');
                    setErrorMessage(
                        isClientError
                            ? 'Lesson not found — please try uploading again.'
                            : 'Lost connection while checking lesson status — please try again.'
                    );
                    return;
                }
                scheduleNextPoll(id);
            }
        };

        const tierAtEntry = selectedTierAtUploadRef.current;
        uploadService
            .uploadLesson(file, tierAtEntry ? LEARNER_TIER_TO_BACKEND[tierAtEntry] : undefined)
            .then((res) => {
                if (cancelled) return;
                setStatusMessage('Processing...');
                pollStatus(res.lesson_id);
            })
            .catch((err) => {
                if (cancelled) return;
                setUploadState('error');
                setErrorMessage(extractErrorMessage(err, 'Upload failed — please try again.'));
            });

        return () => {
            cancelled = true;
            if (timeoutHandle !== undefined) clearTimeout(timeoutHandle);
        };
        // selectedTier is deliberately NOT a dependency — see selectedTierAtUploadRef above.
    }, [uploadState, file]);

    // Gated on a successful lookup, not just selectedTier being truthy — avoids
    // ever rendering an empty visible pill if the two ever desync (review fix).
    const selectedTierOption = selectedTier
        ? LEARNER_TIER_OPTIONS.find((option) => option.id === selectedTier)
        : undefined;

    return (
        <AnimatePresence mode="wait">

            {uploadState === 'idle' && (
                <motion.div
                    key="idle"
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, y: -20, filter: "blur(10px)" }}
                    transition={{ duration: 0.5 }}
                    onDragEnter={handleDrag}
                    onDragLeave={handleDrag}
                    onDragOver={handleDrag}
                    onDrop={handleDrop}
                    className={`w-full relative z-10 transition-all duration-300 rounded-[2.5rem] border-2 border-dashed ${dragActive ? 'border-[var(--accent-primary)] bg-[var(--accent-primary)]/5' : 'border-neutral-200 bg-white/60'} backdrop-blur-xl p-12 text-center shadow-[0_8px_30px_rgb(0,0,0,0.04)] hover:shadow-lg hover:border-[var(--accent-primary)]/50 group flex flex-col items-center justify-center min-h-[400px] cursor-pointer`}
                    onClick={() => inputRef.current?.click()}
                >
                    <input type="file" className="hidden" accept=".pdf" ref={inputRef} onChange={handleChange} />
                    <div className="w-20 h-20 bg-[var(--accent-primary)]/10 text-[var(--accent-primary)] rounded-full flex items-center justify-center mb-6 group-hover:scale-110 transition-transform duration-500">
                        <UploadCloud className="w-10 h-10" />
                    </div>
                    <h3 className="font-serif text-2xl font-semibold tracking-tight text-neutral-900 mb-2">
                        Drop your course material here
                    </h3>
                    <p className="text-neutral-500 max-w-sm mb-8">
                        Upload a PDF document. HIE will automatically structure it, synthesize audio narratives, and generate an interactive journey.
                    </p>
                    <Button
                        variant="primary"
                        size="md"
                        onClick={(e) => {
                            e.stopPropagation(); // the dropzone container already handles the click
                            inputRef.current?.click();
                        }}
                        className="rounded-full bg-neutral-900 text-white shadow-md hover:bg-neutral-800 group-hover:-translate-y-1"
                    >
                        Browse Files
                    </Button>
                </motion.div>
            )}

            {uploadState === 'selecting-mode' && (
                <motion.div
                    key="selecting-mode"
                    initial={{ opacity: 0, y: 20, filter: "blur(10px)" }}
                    animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                    transition={{ duration: 0.6 }}
                    className="w-full relative z-10 flex flex-col items-center"
                >
                    <h3 className="font-serif text-2xl font-semibold tracking-tight text-neutral-900 mb-2 text-center">
                        How do you want to learn this?
                    </h3>
                    <p className="text-neutral-500 max-w-md text-center mb-8">
                        Choose a pace before HIE builds your lesson.
                    </p>
                    <ModeSelection onSelect={handleTierSelect} />
                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={handleCancelModeSelection}
                        className="mt-8 text-neutral-400 hover:text-neutral-600 hover:bg-transparent"
                    >
                        Choose a different file
                    </Button>
                </motion.div>
            )}

            {uploadState === 'processing' && (
                <motion.div
                    key="processing"
                    initial={{ opacity: 0, y: 20, filter: "blur(10px)" }}
                    animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    transition={{ duration: 0.6 }}
                    // data-selected-tier is not rendered as visible text — it's a forward-compatible
                    // hook for the S2-10 tier-badge story, which decides where/how to surface it.
                    data-selected-tier={selectedTier ?? undefined}
                    className="w-full relative z-10 bg-white/80 backdrop-blur-xl rounded-[2.5rem] p-16 shadow-2xl border border-neutral-100 flex flex-col items-center justify-center min-h-[400px] text-center"
                >
                    {/* Pulsing Outer Glow + indeterminate spinner — the backend reports no percentage/stage data */}
                    <div className="relative w-40 h-40 mb-10 flex items-center justify-center">
                        <div className="absolute inset-0 bg-[var(--accent-primary)]/20 rounded-full blur-2xl animate-pulse" />
                        <Loader2 className="w-16 h-16 text-[var(--accent-primary)] animate-spin relative z-10" />
                    </div>

                    <div className="inline-flex items-center gap-3 px-4 py-2 bg-neutral-50 rounded-full border border-neutral-100 mb-5 shadow-inner">
                        <Loader2 className="w-4 h-4 text-[var(--accent-primary)] animate-spin" />
                        <span className="text-sm font-semibold text-[var(--accent-primary)] uppercase tracking-widest">{statusMessage}</span>
                    </div>

                    <h3 className="font-serif text-2xl font-semibold tracking-tight text-neutral-900 mb-3">Architecting your lesson...</h3>
                    <p className="text-neutral-500 max-w-sm leading-relaxed">
                        Establishing intelligence matrix, compiling timeline sequences, and synthesizing audio overlays.
                    </p>
                    {selectedTierOption && (
                        <span
                            data-testid="selected-tier-label"
                            className="mt-5 inline-flex items-center px-3 py-1 rounded-full bg-[var(--accent-secondary)] text-[var(--accent-primary)] text-xs font-semibold uppercase tracking-wide"
                        >
                            {selectedTierOption.label}
                        </span>
                    )}
                </motion.div>
            )}

            {uploadState === 'completed' && (
                <motion.div
                    key="completed"
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ duration: 0.6, type: "spring", bounce: 0.4 }}
                    className="w-full bg-white/90 backdrop-blur-xl rounded-[2.5rem] p-16 shadow-2xl border border-neutral-100 flex flex-col items-center justify-center min-h-[400px] text-center z-10 relative"
                >
                    <div className="relative mb-8">
                        <div className="absolute inset-0 bg-emerald-500/20 rounded-full blur-xl animate-pulse" />
                        <div className="relative w-24 h-24 bg-emerald-50 text-emerald-500 rounded-full flex items-center justify-center shadow-inner border border-emerald-100/50">
                            <CheckCircle className="w-12 h-12" />
                        </div>
                    </div>
                    <h3 className="font-serif text-3xl font-semibold tracking-tight text-neutral-900 mb-3">Generation Complete</h3>
                    <p className="text-neutral-500 text-lg mb-10 max-w-md">Your uploaded material has been successfully transformed into a dynamic, interactive lesson.</p>
                    <Button
                        variant="primary"
                        size="lg"
                        onClick={() => router.push(`/lesson/${lessonId}`)}
                        className="gap-3 rounded-2xl bg-neutral-900 text-white shadow-[0_8px_20px_-8px_rgba(0,0,0,0.3)] hover:-translate-y-1 hover:bg-neutral-800 hover:shadow-[0_12px_24px_-8px_rgba(0,0,0,0.4)]"
                    >
                        <Play className="w-5 h-5 fill-current" /> Begin Lesson
                    </Button>
                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setUploadState('idle')}
                        className="mt-6 text-neutral-400 hover:text-neutral-600 hover:bg-transparent"
                    >
                        Generate Another
                    </Button>
                </motion.div>
            )}

            {uploadState === 'error' && (
                <motion.div
                    key="error"
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className="w-full bg-white/90 backdrop-blur-xl rounded-[2.5rem] p-16 shadow-2xl border border-red-50 flex flex-col items-center justify-center min-h-[400px] text-center z-10 relative"
                >
                    <div className="w-24 h-24 bg-red-50 text-red-500 rounded-full flex items-center justify-center mb-8">
                        <AlertCircle className="w-12 h-12" />
                    </div>
                    <h3 className="font-serif text-2xl font-semibold text-neutral-900 mb-3">Generation Failed</h3>
                    <p className="text-neutral-500 mb-10 max-w-sm">{errorMessage}</p>
                    <Button
                        variant="primary"
                        size="md"
                        onClick={() => setUploadState('idle')}
                        className="rounded-2xl bg-red-500 text-white shadow-md hover:bg-red-600"
                    >
                        Try Again
                    </Button>
                </motion.div>
            )}

        </AnimatePresence>
    );
}
