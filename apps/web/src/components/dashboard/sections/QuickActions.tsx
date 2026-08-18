"use client";

import { motion } from "framer-motion";
import { UploadCloud, BookOpen, ArrowUpRight } from "lucide-react";
import Link from "next/link";

const actions = [
    {
        id: "upload",
        title: "Upload PDF",
        description: "Analyze and structure a new document.",
        icon: UploadCloud,
        color: "text-[var(--accent-primary)]",
        bg: "bg-[var(--color-light-bg)] border-[var(--color-border-soft)]",
        href: "/upload",
    },
    {
        // Story 2-47 (S4-06): this card used to be titled My Library and link
        // to the Library route. Library's one unique capability (reaching a
        // non-latest lesson) folded into Books, and the standalone page was
        // removed. This card points at Books now.
        id: "books",
        title: "My Books",
        description: "Browse your uploaded books and chapters.",
        icon: BookOpen,
        color: "text-purple-500",
        bg: "bg-purple-50 border-purple-100",
        href: "/books",
    },
    // "Reports" removed 2026-07-29 (Sprint 2 audit finding) -- it pointed at
    // "/reports", which has never been a real route (the real route is
    // session-scoped: "/reports/[sessionId]", reached from the player after
    // a lesson ends). There is no session-history/index page yet to send
    // this card to -- add it back once one exists, don't repoint to a guess.
];

export function QuickActions() {
    return (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {actions.map((action, index) => (
                <Link href={action.href} key={action.id} className="block">
                    <motion.div
                        initial={{ opacity: 0, y: 15 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.4, delay: index * 0.1 }}
                        whileHover={{ y: -4 }}
                        className="group relative bg-white/80 backdrop-blur-xl border border-neutral-100 rounded-3xl p-6 shadow-sm hover:shadow-lg transition-all duration-300 cursor-pointer overflow-hidden h-full"
                    >
                        <div className="absolute top-4 right-4 text-neutral-300 group-hover:text-neutral-500 transition-colors">
                            <ArrowUpRight className="w-5 h-5 flex-shrink-0" />
                        </div>

                        <div className={`w-12 h-12 rounded-2xl flex items-center justify-center mb-5 ${action.bg}`}>
                            <action.icon className={`w-6 h-6 ${action.color}`} />
                        </div>

                        <h3 className="text-lg font-semibold text-neutral-900 mb-1">
                            {action.title}
                        </h3>
                        <p className="text-sm text-neutral-500 leading-relaxed pr-6">
                            {action.description}
                        </p>
                    </motion.div>
                </Link>
            ))}
        </div>
    );
}
