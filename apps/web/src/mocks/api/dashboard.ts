import { randomDelay } from '../utils/delay';
import { createSuccessResponse, ApiResponse } from '../utils/response';
import { mockLessons, MockLesson } from '../data/lessons';
import { mockReports, LearningPulse } from '../data/reports';

export interface DashboardData {
    continueLearning: MockLesson | null;
    learningPulse: LearningPulse;
    recentLessons: MockLesson[];
}

export const getDashboardData = async (): Promise<ApiResponse<DashboardData>> => {
    // Simulate 300ms - 700ms latency
    await randomDelay(300, 700);

    const inProgressLessons = mockLessons.filter(l => l.status === 'in_progress');
    const continueLearning = inProgressLessons.length > 0 ? inProgressLessons[0] : null;

    // We want to return exactly 5 realistic lessons for recent
    const recentLessons = mockLessons.slice(0, 5);

    const data: DashboardData = {
        continueLearning,
        learningPulse: mockReports.pulse,
        recentLessons
    };

    return createSuccessResponse(data, "Dashboard data retrieved successfully");
};
