"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { UploadCloud, CheckCircle, AlertCircle, Loader2, Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { uploadGenerationService } from "@/services/uploadGeneration.service";

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
                if (event.type === 'status') {
                    setStatusMessage(event.status);
                } else if (event.type === 'progress') {
                    setProgress(event.progress);
                } else if (event.type === 'completed') {
                    setUploadState('completed');
                    setLessonId(event.lessonId);
                } else if (event.type === 'error') {
                    setUploadState('error');
                    setErrorMessage(event.message);
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

            return () => unsubscribe();
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
                    <h3 className="text-2xl font-semibold tracking-tight text-neutral-900 mb-2">
                        Drop your course material here
                    </h3>
                    <p className="text-neutral-500 max-w-sm mb-8">
                        Upload a PDF document. TransformED will automatically structure it, synthesize audio narratives, and generate an interactive journey.
                    </p>
                    <div className="px-6 py-3 bg-neutral-900 text-white rounded-full font-medium transition-transform group-hover:-translate-y-1 shadow-md">
                        Browse Files
                    </div>
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

                    <h3 className="text-2xl font-bold tracking-tight text-neutral-900 mb-3">Architecting your lesson...</h3>
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
                    <h3 className="text-3xl font-bold tracking-tight text-neutral-900 mb-3">Generation Complete</h3>
                    <p className="text-neutral-500 text-lg mb-10 max-w-md">Your uploaded material has been successfully transformed into a dynamic, interactive lesson.</p>
                    <button
                        onClick={() => router.push(`/lesson/${lessonId}`)}
                        className="px-8 py-4 bg-neutral-900 text-white rounded-2xl shadow-[0_8px_20px_-8px_rgba(0,0,0,0.3)] flex items-center gap-3 font-semibold hover:-translate-y-1 hover:shadow-[0_12px_24px_-8px_rgba(0,0,0,0.4)] transition-all"
                    >
                        <Play className="w-5 h-5 fill-current" /> Begin Lesson
                    </button>
                    <button
                        onClick={() => setUploadState('idle')}
                        className="mt-6 text-sm font-semibold text-neutral-400 hover:text-neutral-600 transition-colors"
                    >
                        Generate Another
                    </button>
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
                    <h3 className="text-2xl font-bold text-neutral-900 mb-3">Generation Failed</h3>
                    <p className="text-neutral-500 mb-10 max-w-sm">{errorMessage}</p>
                    <button
                        onClick={() => setUploadState('idle')}
                        className="px-8 py-3 bg-red-500 text-white rounded-2xl font-semibold hover:bg-red-600 transition-colors shadow-md"
                    >
                        Try Again
                    </button>
                </motion.div>
            )}

        </AnimatePresence>
    );
}
