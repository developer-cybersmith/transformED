import { PlayerLoader } from '@/components/player/PlayerLoader';

export default async function LessonPage({ params }: { params: Promise<{ id: string }> }) {
    const { id } = await params;
    return (
        <main className="flex-1 flex flex-col relative z-10 h-screen">
            {/* S4-11: keys PlayerLoader itself by lessonId, not just the
                downstream <Player> -- otherwise navigating between two
                still-generating lessons without an unmount would carry over
                useLesson's poll-ceiling/pollTimedOut state from the old
                lessonId. */}
            <PlayerLoader key={id} lessonId={id} />
        </main>
    );
}
