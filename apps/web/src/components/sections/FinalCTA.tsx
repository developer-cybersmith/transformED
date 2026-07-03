"use client";

import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import Link from "next/link";

export default function FinalCTA() {
    return (
        <section className="relative overflow-hidden bg-primary py-24 lg:py-32">
            {/* Ambient glow, echoes the hero's */}
            <div
                className="absolute inset-0 pointer-events-none"
                style={{
                    background:
                        "radial-gradient(760px 460px at 15% 100%, rgba(198,164,92,0.14), transparent 62%)",
                }}
            />

            <div className="relative z-10 max-w-3xl mx-auto px-6 lg:px-8 text-center">
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    viewport={{ once: true, margin: "-80px" }}
                    transition={{ duration: 0.6 }}
                >
                    <div className="flex items-center justify-center gap-2 mb-6">
                        <span className="w-6 h-px bg-[var(--accent-secondary)]" />
                        <span className="text-[0.75rem] font-mono uppercase tracking-[0.14em] text-[var(--accent-secondary)]">
                            One last thing
                        </span>
                        <span className="w-6 h-px bg-[var(--accent-secondary)]" />
                    </div>

                    <h2 className="font-serif text-white mb-5">
                        <span className="block font-semibold text-[2.4rem] sm:text-[3rem] lg:text-[3.4rem] leading-[1.05] tracking-tight">
                            You know how to study smarter now.
                        </span>
                        <span className="block italic font-normal text-white/60 text-[1.5rem] sm:text-[1.8rem] lg:text-[2.05rem] leading-[1.15] mt-1">
                            The <span className="text-[var(--accent-secondary)]">alone</span> part is up to you.
                        </span>
                    </h2>

                    <p className="text-white/55 max-w-md mx-auto mb-9 text-[1.05rem] leading-relaxed">
                        Upload a chapter, get a guided lesson, and find out how far you&apos;ve actually come.
                    </p>

                    <div className="flex flex-wrap items-center justify-center gap-4">
                        <Link
                            href="/signup"
                            className="group inline-flex items-center gap-2.5 px-7 py-3.5 bg-[var(--accent-secondary)] text-primary rounded-xl text-[0.95rem] font-semibold shadow-[0_8px_24px_rgba(198,164,92,0.3)] hover:shadow-[0_8px_30px_rgba(198,164,92,0.45)] transition-shadow"
                        >
                            Start your transformation
                            <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
                        </Link>
                        <a
                            href="#how-it-works"
                            className="inline-flex items-center px-7 py-3.5 text-white/55 rounded-xl text-[0.95rem] font-medium hover:text-white/80 transition-colors"
                        >
                            Learn more
                        </a>
                    </div>

                    <p className="mt-7 text-xs text-white/30 font-mono">
                        Free plan · No credit card · Takes 2 minutes
                    </p>
                </motion.div>
            </div>
        </section>
    );
}
