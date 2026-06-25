import type { Metadata } from "next";
import { Sidebar } from "@/components/dashboard/shell/Sidebar";
import { TopUtilityBar } from "@/components/dashboard/shell/TopUtilityBar";

export const metadata: Metadata = {
    title: "Settings - HIE",
    description: "Personalize how HIE guides your learning journey.",
};

export default function SettingsLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <div className="flex bg-[#F8FAFC] min-h-screen text-neutral-900 selection:bg-[var(--accent-primary)]/20 selection:text-[var(--accent-primary)]">
            <div className="fixed inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-[0.015] pointer-events-none mix-blend-overlay z-0"></div>
            <div className="fixed top-0 left-0 w-[500px] h-[500px] bg-[var(--accent-primary)]/5 rounded-full blur-[150px] -translate-x-[20%] -translate-y-[20%] pointer-events-none"></div>

            <div className="sticky top-0 h-screen flex-shrink-0 z-50 flex items-start">
                <Sidebar />
            </div>

            <main className="flex-1 flex flex-col min-w-0 relative z-10">
                <TopUtilityBar />

                <div className="px-4 sm:px-8 lg:px-12 pb-24 w-full max-w-7xl mx-auto">
                    {children}
                </div>
            </main>
        </div>
    );
}
