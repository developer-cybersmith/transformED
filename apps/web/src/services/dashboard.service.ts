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
        const [{ data: lessons }, mockResponse] = await Promise.all([
            api.get<LessonStatusResponse[]>('content/lessons', { params: { limit: 6 } }),
            dashboardApi.getDashboardData(),
        ]);

        return {
            // list_lessons already orders by created_at desc -- the first
            // ready entry is the most recently generated one.
            continueLearning: lessons.find((l) => l.status === 'ready') ?? null,
            recentLessons: lessons.slice(0, 5),
            learningPulse: mockResponse.data?.learningPulse,
        };
    },
};
