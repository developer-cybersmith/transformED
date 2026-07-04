"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { UploadCloud, CheckCircle, AlertCircle, Loader2, Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { uploadGenerationService } from "@/services/uploadGeneration.service";
import { Button } from "@/components/ui/button";

export function UploadFlow() {
    const [file, setFile] = useState<File | null>(null);
    const [dragActive, setDragActive] = useState(false);
    const [uploadState, setUploadState] = useState<'idle' | 'processing' | 'completed' | 'error'>('idle');
    const [statusMessage, setStatusMessage] = useState<string>('');
    const [progress, setProgress] = useState<number>(0);
    const [errorMessage, setErrorMessage] = useState<string>('');
    const [lessonId, setLessonId] = useState<string>('');

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

    const handleFile = (selectedFile: File) => {
        setFile(selectedFile);
        setUploadState('processing');
        setStatusMessage('Initializing synthesis matrix...');
        setProgress(0);
    };

    useEffect(() => {
        if (uploadState === 'processing' && file) {
            // Initiate backend socket link
            uploadGenerationService.connect();

            const unsubscribe = uploadGenerationService.subscribe((event) => {
                if (event.type === 'generation_progress') {
                    setStatusMessage(event.payload.message);
                    setProgress(event.payload.progress);
                } else if (event.type === 'lesson_ready') {
                    setUploadState('completed');
                    setLessonId(event.payload.lesson_id);
                } else if (event.type === 'error') {
                    setUploadState('error');
                    setErrorMessage(event.payload.message);
                }
            });

            // Start Mock Engine - we catch any immediate synchronous throws but 
            // the pipeline will mostly emit errors over the socket event bus.
            uploadGenerationService.startGeneration(file).catch(err => {
                setUploadState(prev => {
                    if (prev !== 'error' && prev !== 'completed') {
                        setErrorMessage(err.message);
                        return 'error';
                    }
                    return prev;
                });
            });

            // Tear down the connection too, not just this subscription — the
            // singleton's generation loop otherwise keeps running in the
            // background after navigating away mid-generation.
            return () => {
                unsubscribe();
                uploadGenerationService.disconnect();
            };
        }
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

            {uploadState === 'processing' && (
                <motion.div
                    key="processing"
                    initial={{ opacity: 0, y: 20, filter: "blur(10px)" }}
                    animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    transition={{ duration: 0.6 }}
                    className="w-full relative z-10 bg-white/80 backdrop-blur-xl rounded-[2.5rem] p-16 shadow-2xl border border-neutral-100 flex flex-col items-center justify-center min-h-[400px] text-center"
                >
                    {/* Pulsing Outer Glow */}
                    <div className="relative w-40 h-40 mb-10 flex items-center justify-center">
                        <div className="absolute inset-0 bg-[var(--accent-primary)]/20 rounded-full blur-2xl animate-pulse" />
                        <svg className="w-full h-full -rotate-90 relative z-10" viewBox="0 0 100 100">
                            <circle className="text-neutral-100" strokeWidth="4" stroke="currentColor" fill="transparent" r="46" cx="50" cy="50" />
                            <circle
                                className="text-[var(--accent-primary)] transition-all duration-700 ease-out"
                                strokeWidth="4" strokeDasharray={289} strokeDashoffset={289 - (progress / 100) * 289}
                                strokeLinecap="round" stroke="currentColor" fill="transparent" r="46" cx="50" cy="50"
                            />
                        </svg>
                        <div className="absolute inset-0 flex flex-col items-center justify-center z-20">
                            <span className="text-3xl font-bold text-neutral-900">{progress}%</span>
                        </div>
                    </div>

                    <div className="inline-flex items-center gap-3 px-4 py-2 bg-neutral-50 rounded-full border border-neutral-100 mb-5 shadow-inner">
                        <Loader2 className="w-4 h-4 text-[var(--accent-primary)] animate-spin" />
                        <span className="text-sm font-semibold text-[var(--accent-primary)] uppercase tracking-widest">{statusMessage}</span>
                    </div>

                    <h3 className="font-serif text-2xl font-semibold tracking-tight text-neutral-900 mb-3">Architecting your lesson...</h3>
                    <p className="text-neutral-500 max-w-sm leading-relaxed">
                        Establishing intelligence matrix, compiling timeline sequences, and synthesizing audio overlays.
                    </p>
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
