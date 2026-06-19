import { lessonService } from "@/services/lesson.service";
import { InteractivePlayer } from "@/components/lesson/InteractivePlayer";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

export default async function LessonPage({ params }: { params: Promise<{ id: string }> }) {
    const resolvedParams = await params;
    const response = await lessonService.getLesson(resolvedParams.id);
    const lesson = response.data;

    // A robust dark-mode UI skeleton if the lesson fails to load
    if (!lesson) {
        return (
            <div className="flex-1 flex flex-col items-center justify-center relative z-10 p-6 text-center">
                <h1 className="text-3xl font-bold text-white mb-4">Lesson Unavailable</h1>
                <p className="text-neutral-400 max-w-md mb-8">We could not retrieve this generated lesson. The Mock API may have reset.</p>
                <Link href="/dashboard" className="px-6 py-3 bg-[var(--accent-primary)] rounded-full text-white font-medium hover:scale-105 transition-transform flex items-center gap-2">
                    <ArrowLeft className="w-4 h-4" /> Return to Dashboard
                </Link>
            </div>
        );
    }

    return (
        <main className="flex-1 flex flex-col relative z-10 h-screen">
            <InteractivePlayer initialLesson={lesson} />
        </main>
    );
}
