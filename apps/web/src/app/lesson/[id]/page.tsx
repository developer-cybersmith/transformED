import { PlayerLoader } from '@/components/player/PlayerLoader';

export default async function LessonPage({ params }: { params: Promise<{ id: string }> }) {
    const { id } = await params;
    return (
        <main className="flex-1 flex flex-col relative z-10 h-screen">
            <PlayerLoader lessonId={id} />
        </main>
    );
}
