import { randomDelay } from '../utils/delay';
import { createSuccessResponse, createErrorResponse, ApiResponse } from '../utils/response';
import { mockUser, UserProfile } from '../data/users';

export const getAuthSession = async (): Promise<ApiResponse<UserProfile>> => {
    await randomDelay(100, 300);
    return createSuccessResponse(mockUser.profile, "Session retrieved");
};
