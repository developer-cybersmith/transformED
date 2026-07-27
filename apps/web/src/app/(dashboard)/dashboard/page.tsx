"use client";

import { HeroSection } from "@/components/dashboard/sections/HeroSection";
import { ReassessmentPrompt } from "@/components/dashboard/sections/ReassessmentPrompt";
import { ContinueLearningCard } from "@/components/dashboard/sections/ContinueLearningCard";
import { QuickActions } from "@/components/dashboard/sections/QuickActions";
import { LearningPulse } from "@/components/dashboard/sections/LearningPulse";
import { RecentLessons } from "@/components/dashboard/sections/RecentLessons";
import { useDashboard } from "@/hooks/useDashboard";

export default function DashboardPage() {
    // Client-side fetch (not a server-side call) -- api.ts's auth interceptor
    // only reads the Supabase session in the browser, so this must run here.
    const { data: dashboardData, error, isLoading } = useDashboard();

    return (
        <div className="w-full max-w-[1400px] mx-auto pt-6 flex flex-col gap-10">
            {error != null && (
                <div className="rounded-2xl border border-red-100 bg-red-50 px-5 py-3 text-sm text-red-600">
                    We couldn&apos;t load some of your dashboard data right now. Please refresh the page.
                </div>
            )}

            {/* 1. Compact Hero Section */}
            <HeroSection continueLessonId={dashboardData?.continueLearning?.lesson_id} />

            {/* 1b. Re-Assessment Prompt (self-contained, only renders when due) */}
            <ReassessmentPrompt />

            {isLoading ? (
                // Client-side fetching (unlike the prior server-rendered version) means
                // this page mounts before data resolves -- show an explicit loading state
                // instead of letting every lesson-dependent section render as if the
                // account genuinely had no lessons yet (review finding).
                <div className="flex min-h-[30vh] w-full items-center justify-center text-neutral-400">
                    <div className="animate-pulse">Loading your dashboard...</div>
                </div>
            ) : (
                <>
                    <div className="grid grid-cols-1 xl:grid-cols-3 gap-10">

                        {/* Left Column (Main Focus) */}
                        <div className="xl:col-span-2 flex flex-col gap-10">
                            {/* 2. Primary Product CTA */}
                            <ContinueLearningCard lesson={dashboardData?.continueLearning || null} />

                            {/* 3. Quick Action Access */}
                            <div>
                                <h2 className="font-serif text-xl font-semibold tracking-tight text-neutral-900 mb-6">
                                    Quick Actions
                                </h2>
                                <QuickActions />
                            </div>
                        </div>

                        {/* Right Column (Secondary/Intel) */}
                        <div className="xl:col-span-1">
                            {/* 4. Telemetry / Stats */}
                            {dashboardData?.learningPulse && (
                                <LearningPulse pulse={dashboardData.learningPulse} />
                            )}
                        </div>

                    </div>

                    {/* 5. Horizontal Modules Slider */}
                    <div className="mt-4">
                        <RecentLessons lessons={dashboardData?.recentLessons || []} />
                    </div>
                </>
            )}
        </div>
    );
}
