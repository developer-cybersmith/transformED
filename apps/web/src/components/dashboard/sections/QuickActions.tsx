"use client";

import { motion } from "framer-motion";
import { UploadCloud, Library, PieChart, ArrowUpRight } from "lucide-react";
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
        id: "library",
        title: "My Library",
        description: "Access your 12 processed materials.",
        icon: Library,
        color: "text-purple-500",
        bg: "bg-purple-50 border-purple-100",
        href: "/library",
    },
    {
        id: "reports",
        title: "Reports",
        description: "View your learning progression.",
        icon: PieChart,
        color: "text-emerald-500",
        bg: "bg-emerald-50 border-emerald-100",
        href: "/reports",
    },
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
