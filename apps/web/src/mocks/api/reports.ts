import { randomDelay } from '../utils/delay';
import { createSuccessResponse, ApiResponse } from '../utils/response';
import { mockReports, MockReports } from '../data/reports';

export const getReports = async (): Promise<ApiResponse<MockReports>> => {
    // Simulate analytical query latency
    await randomDelay(600, 1200);

    return createSuccessResponse(mockReports, "Reports retrieved successfully");
};
