"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { UploadCloud, CheckCircle, AlertCircle, Loader2, BookOpen } from "lucide-react";
import { useRouter } from "next/navigation";
import { uploadService, extractErrorMessage, MAX_UPLOAD_SIZE_BYTES } from "@/services/upload.service";
import type { BookResponse } from "@/services/upload.service";
import { nextPollInterval } from "@/lib/lessonStatusPoll";
import { Button } from "@/components/ui/button";

const MAX_CONSECUTIVE_POLL_FAILURES = 3;
// Absolute backstop on the number of polls, independent of the wall-clock
// ceiling that `nextPollInterval` enforces (MAX_POLL_DURATION_MS, ~20 minutes).
// Belt and braces: the wall-clock cap is the one that fires in practice, this
// one still terminates the loop if Date.now() never advances.
const MAX_POLL_ATTEMPTS = 240;

// Ingestion is fast — 90.3 s end-to-end for a 1,151-page book (58.0 s of that
// the upload itself). It is NOT the "~15 minutes" figure that used to be quoted
// here: that is chapter GENERATION (CLAUDE.md §9), which now happens later, per
// chapter, from the book page.
export function UploadFlow() {
    const [file, setFile] = useState<File | null>(null);
    const [dragActive, setDragActive] = useState(false);
    const [uploadState, setUploadState] = useState<'idle' | 'processing' | 'completed' | 'error'>('idle');
    const [statusMessage, setStatusMessage] = useState<string>('');
    const [errorMessage, setErrorMessage] = useState<string>('');
    const [bookId, setBookId] = useState<string>('');
    // Latest polled book row — drives the honest progress readout (chapters
    // actually detected so far) instead of a fabricated percentage.
    const [book, setBook] = useState<BookResponse | null>(null);

    const router = useRouter();
    const inputRef = useRef<HTMLInputElement>(null);

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

    // Straight to 'processing' — there is no tier to choose at upload time any
    // more. A book has no tier; the tier is picked per chapter, later.
    const handleFile = (selectedFile: File) => {
        if (selectedFile.size > MAX_UPLOAD_SIZE_BYTES) {
            setFile(null);
            setErrorMessage('File exceeds the 50MB limit — please upload a smaller PDF.');
            setUploadState('error');
            return;
        }
        setBook(null);
        setBookId('');
        setFile(selectedFile);
        setStatusMessage('Uploading...');
        setUploadState('processing');
    };

    // Clears the input's FileList so re-selecting the SAME file through the
    // native dialog still fires a `change` event.
    const resetToIdle = () => {
        setFile(null);
        setBook(null);
        setBookId('');
        setErrorMessage('');
        setStatusMessage('');
        if (inputRef.current) inputRef.current.value = '';
        setUploadState('idle');
    };

    useEffect(() => {
        if (uploadState !== 'processing' || !file) return;

        let cancelled = false;
        let timeoutHandle: ReturnType<typeof setTimeout> | undefined;
        let consecutiveFailures = 0;
        let attempts = 0;
        // Owned by this effect run, so a later upload starts a fresh 20-minute
        // window rather than inheriting an expired one.
        const pollWindowRef: { current: number | null } = { current: null };

        // Self-rescheduling (setTimeout after each poll settles) rather than
        // setInterval — guarantees polls never overlap, so a slow response can
        // never race a faster later one and clobber an already-reached terminal
        // state.
        const scheduleNextPoll = (id: string): boolean => {
            const delay = nextPollInterval(true, pollWindowRef);
            if (delay === 0 || attempts >= MAX_POLL_ATTEMPTS) return false;
            timeoutHandle = setTimeout(() => pollStatus(id), delay);
            return true;
        };

        const giveUpSlow = () => {
            setUploadState('error');
            setErrorMessage('Processing is taking longer than expected — please try uploading again.');
        };

        const pollStatus = async (id: string) => {
            if (cancelled) return;
            attempts += 1;

            try {
                // Book vocabulary: processing | ready | failed. Deliberately not
                // routed through `isLessonProcessing`, which tests queued/running
                // and would be false for every book, forever.
                const status = await uploadService.getBookStatus(id);
                if (cancelled) return;
                consecutiveFailures = 0;
                setBook(status);

                if (status.status === 'ready') {
                    setUploadState('completed');
                    return;
                }
                if (status.status === 'failed') {
                    setUploadState('error');
                    setErrorMessage(
                        "We couldn't read this PDF — it may be scanned, password-protected or corrupted. Please try a different file."
                    );
                    return;
                }
                if (status.status !== 'processing') {
                    console.warn(`Unexpected book status: ${status.status}`);
                }
                setStatusMessage(
                    status.chapter_count > 0
                        ? `${status.chapter_count} chapters found`
                        : 'Reading your book...'
                );
                if (!scheduleNextPoll(id)) giveUpSlow();
            } catch (err) {
                if (cancelled) return;
                const httpStatus = (err as { response?: { status?: number } })?.response?.status;
                const isClientError = typeof httpStatus === 'number' && httpStatus >= 400 && httpStatus < 500;
                consecutiveFailures += 1;

                if (isClientError || consecutiveFailures >= MAX_CONSECUTIVE_POLL_FAILURES) {
                    setUploadState('error');
                    setErrorMessage(
                        isClientError
                            ? 'Book not found — please try uploading again.'
                            : 'Lost connection while checking your book — please try again.'
                    );
                    return;
                }
                if (!scheduleNextPoll(id)) giveUpSlow();
            }
        };

        uploadService
            .uploadLesson(file)
            .then((res) => {
                if (cancelled) return;
                setBookId(res.book_id);
                setStatusMessage('Reading your book...');
                pollStatus(res.book_id);
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
    }, [uploadState, file]);

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
                        Drop your textbook here
                    </h3>
                    <p className="text-neutral-500 max-w-sm mb-8">
                        Upload a PDF. HIE splits it into chapters so you can pick one to study — this usually takes a minute or two.
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

            {uploadState === 'processing' && (
                <motion.div
                    key="processing"
                    initial={{ opacity: 0, y: 20, filter: "blur(10px)" }}
                    animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    transition={{ duration: 0.6 }}
                    className="w-full relative z-10 bg-white/80 backdrop-blur-xl rounded-[2.5rem] p-16 shadow-2xl border border-neutral-100 flex flex-col items-center justify-center min-h-[400px] text-center"
                >
                    {/* Indeterminate spinner: the backend reports no percentage, and
                        inventing one would be a lie. Real progress is the chapter
                        count below, which only moves when chapters actually exist. */}
                    <div className="relative w-40 h-40 mb-10 flex items-center justify-center">
                        <div className="absolute inset-0 bg-[var(--accent-primary)]/20 rounded-full blur-2xl animate-pulse" />
                        <Loader2 className="w-16 h-16 text-[var(--accent-primary)] animate-spin relative z-10" />
                    </div>

                    <div className="inline-flex items-center gap-3 px-4 py-2 bg-neutral-50 rounded-full border border-neutral-100 mb-5 shadow-inner">
                        <Loader2 className="w-4 h-4 text-[var(--accent-primary)] animate-spin" />
                        <span className="text-sm font-semibold text-[var(--accent-primary)] uppercase tracking-widest">{statusMessage}</span>
                    </div>

                    <h3 className="font-serif text-2xl font-semibold tracking-tight text-neutral-900 mb-3">
                        Finding the chapters...
                    </h3>
                    <p className="text-neutral-500 max-w-sm leading-relaxed">
                        {book && book.page_count
                            ? `Reading ${book.page_count.toLocaleString()} pages and detecting where each chapter starts.`
                            : 'Reading your PDF and detecting where each chapter starts.'}
                    </p>
                    {book && book.chapter_count > 0 && (
                        <span
                            data-testid="chapter-count-progress"
                            className="mt-5 inline-flex items-center px-3 py-1 rounded-full bg-[var(--accent-secondary)] text-[var(--accent-primary)] text-xs font-semibold uppercase tracking-wide"
                        >
                            {book.chapter_count} chapters so far
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
                    <h3 className="font-serif text-3xl font-semibold tracking-tight text-neutral-900 mb-3">
                        {book ? `${book.chapter_count} chapters ready` : 'Your book is ready'}
                    </h3>
                    <p className="text-neutral-500 text-lg mb-10 max-w-md">
                        {book && book.page_count
                            ? `We read all ${book.page_count.toLocaleString()} pages. Pick a chapter to turn into a lesson — you choose the pace on the chapter itself.`
                            : 'Pick a chapter to turn into a lesson — you choose the pace on the chapter itself.'}
                    </p>
                    <Button
                        variant="primary"
                        size="lg"
                        onClick={() => router.push(`/books/${bookId}`)}
                        className="gap-3 rounded-2xl bg-neutral-900 text-white shadow-[0_8px_20px_-8px_rgba(0,0,0,0.3)] hover:-translate-y-1 hover:bg-neutral-800 hover:shadow-[0_12px_24px_-8px_rgba(0,0,0,0.4)]"
                    >
                        <BookOpen className="w-5 h-5" /> Choose a chapter
                    </Button>
                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={resetToIdle}
                        className="mt-6 text-neutral-400 hover:text-neutral-600 hover:bg-transparent"
                    >
                        Upload another book
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
                    <h3 className="font-serif text-2xl font-semibold text-neutral-900 mb-3">Upload Failed</h3>
                    <p className="text-neutral-500 mb-10 max-w-sm">{errorMessage}</p>
                    <Button
                        variant="primary"
                        size="md"
                        onClick={resetToIdle}
                        className="rounded-2xl bg-red-500 text-white shadow-md hover:bg-red-600"
                    >
                        Try Again
                    </Button>
                </motion.div>
            )}

        </AnimatePresence>
    );
}
