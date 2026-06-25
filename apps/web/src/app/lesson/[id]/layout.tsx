import type { Metadata } from "next";

export const metadata: Metadata = {
    title: "Lesson Player - HIE",
    description: "Immersive learning environment.",
};

export default function LessonLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <div className="w-full bg-neutral-950 min-h-screen text-slate-50 selection:bg-[var(--accent-primary)]/30 selection:text-white flex flex-col font-sans overflow-hidden">
            <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-[0.03] pointer-events-none mix-blend-overlay z-0"></div>
            {children}
        </div>
    );
}
