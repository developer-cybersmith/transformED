"use client";

import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import Link from "next/link";

export default function FinalCTA() {
    return (
        <section className="py-20 lg:py-28 bg-white">
            <div className="max-w-4xl mx-auto px-6 lg:px-8">
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    viewport={{ once: true, margin: "-80px" }}
                    transition={{ duration: 0.5 }}
                    className="bg-foreground rounded-2xl px-8 py-14 sm:px-14 sm:py-16 text-center"
                >
                    <h2 className="text-2xl sm:text-3xl lg:text-4xl font-bold text-white font-display tracking-tight mb-4 leading-[1.15]">
                        Build the capacity to think independently.
                    </h2>
                    <p className="text-white/60 max-w-md mx-auto mb-8 text-[1.1rem] leading-relaxed">
                        Stop passively consuming content. Join the cognitive engine designed to train your focus and build self-reliance.
                    </p>

                    <div className="flex flex-wrap items-center justify-center gap-3">
                        <Link
                            href="/signup"
                            className="group inline-flex items-center gap-2 px-7 py-3 bg-white text-foreground rounded-xl text-sm font-semibold hover:bg-white/90 transition-colors"
                        >
                            Start your transformation
                            <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
                        </Link>
                        <a
                            href="#how-it-works"
                            className="inline-flex items-center px-7 py-3 text-white/60 rounded-xl text-sm font-medium hover:text-white/80 transition-colors"
                        >
                            Learn more
                        </a>
                    </div>

                    <p className="mt-6 text-xs text-white/30">
                        Free plan · No credit card · Takes 2 minutes
                    </p>
                </motion.div>
            </div>
        </section>
    );
}
