"use client";

import { motion } from "framer-motion";
import { SettingsTabs } from "@/components/settings/SettingsTabs";
import { Sparkles } from "lucide-react";

export default function SettingsPage() {
    return (
        <div className="w-full flex flex-col gap-10 py-6">
            {/* Header Area */}
            <div className="flex flex-col gap-3">
                <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="flex items-center gap-3"
                >
                    <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[var(--accent-secondary)] text-[var(--accent-primary)] text-xs font-medium">
                        <Sparkles className="w-3.5 h-3.5" />
                        <span>Scholar Journey: Guided Learner</span>
                    </div>
                </motion.div>

                <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.1 }}
                >
                    <h1 className="text-4xl font-semibold tracking-tight text-neutral-900 mb-2">
                        Settings
                    </h1>
                    <p className="text-neutral-500 text-lg">
                        Personalize how HIE guides your learning journey.
                    </p>
                </motion.div>
            </div>

            {/* Main Tabs Area */}
            <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
            >
                <SettingsTabs />
            </motion.div>
        </div>
    );
}
