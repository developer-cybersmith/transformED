import { HeroSection } from "@/components/dashboard/sections/HeroSection";
import { ReassessmentPrompt } from "@/components/dashboard/sections/ReassessmentPrompt";
import { ContinueLearningCard } from "@/components/dashboard/sections/ContinueLearningCard";
import { QuickActions } from "@/components/dashboard/sections/QuickActions";
import { LearningPulse } from "@/components/dashboard/sections/LearningPulse";
import { RecentLessons } from "@/components/dashboard/sections/RecentLessons";
import { dashboardService, type DashboardData } from "@/services/dashboard.service";

export default async function DashboardPage() {
    let dashboardData: DashboardData | null = null;
    let loadFailed = false;
    try {
        dashboardData = await dashboardService.getDashboard();
    } catch (error) {
        // Real API unavailable -- degrade to empty sections rather than a hard crash,
        // but still surface a real message instead of silently looking like a new,
        // lesson-less account.
        loadFailed = true;
        console.error("DashboardPage: failed to load dashboard data", error);
    }

    return (
        <div className="w-full max-w-[1400px] mx-auto pt-6 flex flex-col gap-10">
            {loadFailed && (
                <div className="rounded-2xl border border-red-100 bg-red-50 px-5 py-3 text-sm text-red-600">
                    We couldn&apos;t load some of your dashboard data right now. Please refresh the page.
                </div>
            )}

            {/* 1. Compact Hero Section */}
            <HeroSection continueLessonId={dashboardData?.continueLearning?.lesson_id} />

            {/* 1b. Re-Assessment Prompt (self-contained, only renders when due) */}
            <ReassessmentPrompt />

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
        </div>
    );
}
