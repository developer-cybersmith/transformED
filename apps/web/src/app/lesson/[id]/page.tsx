import { Suspense } from 'react';
import { PlayerLoader, PlayerSkeleton } from '@/components/player/PlayerLoader';

export default async function LessonPage({ params }: { params: Promise<{ id: string }> }) {
    const { id } = await params;
    return (
        <main className="flex-1 flex flex-col relative z-10 h-screen">
            <Suspense fallback={<PlayerSkeleton />}>
                <PlayerLoader lessonId={id} />
            </Suspense>
        </main>
    );
}
