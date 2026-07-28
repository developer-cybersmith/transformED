import { api } from '@/lib/api';
import { dashboardApi } from '@/mocks/api';
import type { LessonStatusResponse } from './upload.service';
import type { LearningPulse } from '@/mocks/data/reports';

export interface DashboardData {
    continueLearning: LessonStatusResponse | null;
    recentLessons: LessonStatusResponse[];
    // Dev 3's analytics domain -- unrelated to lesson data, stays mocked
    // until that endpoint exists.
    learningPulse: LearningPulse | undefined;
}

export const dashboardService = {
    getDashboard: async (): Promise<DashboardData> => {
        // A wider window than "recent" needs alone -- generation takes 5-15
        // minutes, so the newest few lessons are often still queued/running.
        // Without this, continueLearning would go missing whenever the most
        // recent handful haven't finished yet, even if an older one is ready.
        const { data: lessons } = await api.get<LessonStatusResponse[]>('content/lessons', {
            params: { limit: 20 },
        });

        // The mock analytics call is a separate, unrelated concern (Dev 3's
        // domain) -- its failure must never take down real lesson data.
        let learningPulse: LearningPulse | undefined;
        try {
            const mockResponse = await dashboardApi.getDashboardData();
            learningPulse = mockResponse.data?.learningPulse;
        } catch {
            learningPulse = undefined;
        }

        // list_lessons already orders by created_at desc -- the first ready
        // entry is the most recently generated one.
        const continueLearning = lessons.find((l) => l.status === 'ready') ?? null;
        const recentPool = continueLearning
            ? lessons.filter((l) => l.lesson_id !== continueLearning.lesson_id)
            : lessons;

        return {
            continueLearning,
            recentLessons: recentPool.slice(0, 5),
            learningPulse,
        };
    },
};
