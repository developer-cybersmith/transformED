import { Suspense } from "react";
import { HeroSection } from "@/components/dashboard/sections/HeroSection";
import { ContinueLearningCard } from "@/components/dashboard/sections/ContinueLearningCard";
import { QuickActions } from "@/components/dashboard/sections/QuickActions";
import { LearningPulse } from "@/components/dashboard/sections/LearningPulse";
import { RecentLessons } from "@/components/dashboard/sections/RecentLessons";
import { dashboardService } from "@/services/dashboard.service";

export default function DashboardPage() {
    return (
        <Suspense fallback={
            <div className="w-full flex-1 flex items-center justify-center text-neutral-400">
                <div className="animate-pulse">Loading intelligence...</div>
            </div>
        }>
            <DashboardDataFetcher />
        </Suspense>
    );
}

export async function DashboardDataFetcher() {
    const response = await dashboardService.getDashboard();
    const dashboardData = response.data;

    if (!response.success || !dashboardData) {
        return (
            <div className="flex min-h-[40vh] w-full flex-col items-center justify-center gap-2 text-center text-neutral-400">
                <p>We couldn&apos;t load your dashboard right now.</p>
            </div>
        );
    }

    return (
        <div className="w-full max-w-[1400px] mx-auto pt-6 flex flex-col gap-10">
            {/* 1. Compact Hero Section */}
            <HeroSection continueLessonId={dashboardData?.continueLearning?.id} />

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
                <RecentLessons
                    lessons={dashboardData?.recentLessons || []}
                    error={dashboardData?.recentLessonsError ?? null}
                />
            </div>
        </div>
    );
}
