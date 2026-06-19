"use client";

import { motion } from "framer-motion";
import { ArrowRight, UploadCloud, BookOpen } from "lucide-react";
import { Button } from "@/components/ui/button";

export function HeroSection() {
    return (
        <motion.section
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: "easeOut" }}
            className="relative w-full rounded-[32px] overflow-hidden bg-white shadow-sm border border-neutral-100 flex flex-col md:flex-row min-h-[240px] mb-12"
        >
            {/* Decorative background gradients */}
            <div className="absolute top-0 right-0 w-full md:w-1/2 h-full bg-gradient-to-l from-[var(--accent-primary)]/5 to-transparent pointer-events-none" />
            <div className="absolute -top-24 -right-24 w-64 h-64 bg-[var(--accent-primary)]/10 blur-[60px] rounded-full pointer-events-none" />

            {/* Left Content */}
            <div className="flex-1 flex flex-col justify-center p-8 md:p-12 relative z-10">
                <motion.div
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.5, delay: 0.1 }}
                >
                    <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-50 border border-emerald-100 text-emerald-600 text-xs font-medium mb-4 shadow-sm">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                        Optimal Learning State
                    </div>

                    <h1 className="text-3xl lg:text-4xl font-semibold tracking-tight text-neutral-900 mb-3">
                        Good evening, Robert 👋
                    </h1>

                    <p className="text-neutral-500 max-w-md leading-relaxed mb-8">
                        Your last session showed strong understanding in Web Security. Continue building your capacity to think independently.
                    </p>

                    <div className="flex items-center gap-4">
                        <Button size="md" className="group rounded-2xl">
                            Resume Journey
                            <ArrowRight className="w-4 h-4 ml-2 group-hover:translate-x-1 transition-transform" />
                        </Button>
                        <Button variant="outline" size="md" className="rounded-2xl border-neutral-200">
                            <UploadCloud className="w-4 h-4 mr-2 text-neutral-500" />
                            Upload PDF
                        </Button>
                    </div>
                </motion.div>
            </div>

            {/* Right Abstract Visual */}
            <div className="hidden md:flex w-[40%] relative items-center justify-center p-8">
                <div className="w-full max-w-[280px] aspect-square relative flex items-center justify-center">
                    {/* Conceptual intelligence visual */}
                    <div className="absolute inset-0 rounded-full border border-[var(--accent-primary)]/20 animate-[spin_60s_linear_infinite]" />
                    <div className="absolute inset-4 rounded-full border border-[var(--accent-secondary)]/10 animate-[spin_40s_linear_infinite_reverse]" />

                    <div className="w-24 h-24 rounded-2xl bg-white shadow-xl rotate-12 flex items-center justify-center relative z-10 border border-neutral-100">
                        <BookOpen className="w-10 h-10 text-[var(--accent-primary)]" />
                    </div>
                    <div className="w-20 h-20 rounded-2xl bg-white/60 backdrop-blur shadow-lg -rotate-12 absolute right-8 bottom-12 border border-neutral-100 justify-center flex items-center">
                        <span className="text-[var(--accent-secondary)] font-bold text-xl">94%</span>
                    </div>
                </div>
            </div>
        </motion.section>
    );
}
