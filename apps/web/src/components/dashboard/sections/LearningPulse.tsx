"use client";

import { motion } from "framer-motion";
import { Brain, Target, Compass, Flame } from "lucide-react";
import type { LearningPulse as PulseType } from "@/mocks/data/reports";

export function LearningPulse({ pulse }: { pulse: PulseType }) {
    return (
        <div className="bg-white/60 backdrop-blur-md rounded-3xl p-6 sm:p-8 border border-neutral-100 shadow-[0_8px_30px_rgb(0,0,0,0.03)] h-full">
            <div className="mb-6">
                <h3 className="text-lg font-semibold text-neutral-900 flex items-center gap-2">
                    Learning Pulse
                </h3>
                <p className="text-sm text-neutral-500">Your engagement intelligence</p>
            </div>

            <div className="space-y-6">
                {/* Metric 1 */}
                <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-xl bg-[var(--accent-primary)]/10 flex items-center justify-center flex-shrink-0">
                        <Target className="w-5 h-5 text-[var(--accent-primary)]" />
                    </div>
                    <div>
                        <div className="text-xs text-neutral-500 font-medium tracking-wide uppercase">Strongest Topic</div>
                        <div className="text-sm font-semibold text-neutral-900">{pulse.strongestTopic}</div>
                    </div>
                </div>

                {/* Metric 2 */}
                <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-xl bg-orange-50 flex items-center justify-center flex-shrink-0">
                        <Flame className="w-5 h-5 text-orange-500" />
                    </div>
                    <div>
                        <div className="text-xs text-neutral-500 font-medium tracking-wide uppercase">Current Streak</div>
                        <div className="text-sm font-semibold text-neutral-900">{pulse.streak} days learning</div>
                    </div>
                </div>

                {/* Metric 3 */}
                <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-xl bg-[var(--accent-secondary)]/15 flex items-center justify-center flex-shrink-0">
                        <Brain className="w-5 h-5 text-[var(--accent-primary)]" />
                    </div>
                    <div>
                        <div className="text-xs text-neutral-500 font-medium tracking-wide uppercase">Deep Work This Week</div>
                        <div className="text-sm font-semibold text-neutral-900">{pulse.hoursThisWeek} hours recorded</div>
                    </div>
                </div>
            </div>
        </div>
    );
}
