import { dashboardApi } from '../mocks/api';
import { lessonsService } from './lessons.service';
import { createSuccessResponse, ApiResponse } from '../mocks/utils/response';
import type { MockLesson } from '../mocks/data/lessons';
import type { LearningPulse } from '../mocks/data/reports';
import type { LessonStatusResponse } from './upload.service';

export interface DashboardData {
    continueLearning: MockLesson | null;
    learningPulse: LearningPulse | null;
    recentLessons: LessonStatusResponse[];
    recentLessonsError: string | null;
}

const RECENT_LESSONS_LIMIT = 5;

export const dashboardService = {
    getDashboard: async (): Promise<ApiResponse<DashboardData>> => {
        // Both fetches are independent of each other, so they run concurrently
        // via Promise.allSettled — sequential awaits here would stack their
        // latencies instead of overlapping them, and (more importantly) a
        // rejection from either one must not take down the other's data or
        // the dashboard as a whole.
        const [mockResult, lessonsResult] = await Promise.allSettled([
            dashboardApi.getDashboardData(),
            lessonsService.listLessons({ limit: RECENT_LESSONS_LIMIT }),
        ]);

        // continueLearning / learningPulse: still mocked — no backend endpoint
        // exists for "latest session" or streak/mastery data (see S1-09).
        let continueLearning: MockLesson | null = null;
        let learningPulse: LearningPulse | null = null;
        if (mockResult.status === 'fulfilled' && mockResult.value.success && mockResult.value.data) {
            continueLearning = mockResult.value.data.continueLearning ?? null;
            learningPulse = mockResult.value.data.learningPulse ?? null;
        } else {
            const reason = mockResult.status === 'rejected' ? mockResult.reason : 'response had success:false or no data';
            console.error("Failed to fetch dashboard summary data:", reason);
        }

        let recentLessons: LessonStatusResponse[] = [];
        let recentLessonsError: string | null = null;
        if (lessonsResult.status === 'fulfilled' && Array.isArray(lessonsResult.value)) {
            recentLessons = lessonsResult.value;
        } else {
            const reason = lessonsResult.status === 'rejected'
                ? lessonsResult.reason
                : new Error('Unexpected (non-array) response shape from lessonsService.listLessons');
            console.error("Failed to fetch recent lessons for dashboard:", reason);
            recentLessonsError = "We couldn't load your recent lessons right now.";
        }

        // Non-blocking by design: the top-level response always succeeds.
        // Hero / Continue-Learning / Quick Actions / Learning Pulse render
        // from continueLearning/learningPulse above (null-safe fallbacks if
        // that fetch failed); Recent Lessons renders its own inline error via
        // recentLessonsError if only that fetch failed.
        return createSuccessResponse(
            { continueLearning, learningPulse, recentLessons, recentLessonsError },
            "Dashboard data retrieved successfully"
        );
    },
};
