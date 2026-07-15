import { dashboardApi } from '../mocks/api';
import { lessonsService } from './lessons.service';
import { createSuccessResponse, ApiResponse } from '../mocks/utils/response';
import type { MockLesson } from '../mocks/data/lessons';
import type { LearningPulse } from '../mocks/data/reports';
import type { LessonStatusResponse } from './upload.service';

export interface DashboardData {
    continueLearning: MockLesson | null;
    learningPulse: LearningPulse;
    recentLessons: LessonStatusResponse[];
    recentLessonsError: string | null;
}

const RECENT_LESSONS_LIMIT = 5;

export const dashboardService = {
    getDashboard: async (): Promise<ApiResponse<DashboardData>> => {
        // continueLearning / learningPulse: still mocked — no backend endpoint
        // exists for "latest session" or streak/mastery data (see S1-09).
        const mockResponse = await dashboardApi.getDashboardData();
        const continueLearning = mockResponse.data?.continueLearning ?? null;
        const learningPulse = mockResponse.data?.learningPulse as LearningPulse;

        try {
            const recentLessons = await lessonsService.listLessons({ limit: RECENT_LESSONS_LIMIT });
            return createSuccessResponse(
                { continueLearning, learningPulse, recentLessons, recentLessonsError: null },
                "Dashboard data retrieved successfully"
            );
        } catch (err) {
            console.error("Failed to fetch recent lessons for dashboard:", err);
            // Non-blocking: the rest of the dashboard (Hero, Continue-Learning,
            // Quick Actions, Learning Pulse) still renders from the mocked
            // fetch above — only the Recent Lessons widget degrades.
            return createSuccessResponse(
                {
                    continueLearning,
                    learningPulse,
                    recentLessons: [],
                    recentLessonsError: "We couldn't load your recent lessons right now.",
                },
                "Dashboard data retrieved successfully"
            );
        }
    },
};
