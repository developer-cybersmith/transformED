import { randomDelay } from '../utils/delay';
import { createSuccessResponse, ApiResponse } from '../utils/response';
import { mockUser, UserProfile, LearningPreferences, NotificationSettings } from '../data/users';

export const getUserProfile = async (): Promise<ApiResponse<UserProfile>> => {
    await randomDelay(200, 500);
    return createSuccessResponse(mockUser.profile, "Profile retrieved");
};

export const getLearningPreferences = async (): Promise<ApiResponse<LearningPreferences>> => {
    await randomDelay(200, 500);
    return createSuccessResponse(mockUser.preferences, "Preferences retrieved");
};

export const getNotificationSettings = async (): Promise<ApiResponse<NotificationSettings>> => {
    await randomDelay(200, 500);
    return createSuccessResponse(mockUser.notifications, "Settings retrieved");
};

export const updateLearningPreferences = async (updates: Partial<LearningPreferences>): Promise<ApiResponse<LearningPreferences>> => {
    await randomDelay(400, 800);
    mockUser.preferences = { ...mockUser.preferences, ...updates };
    return createSuccessResponse(mockUser.preferences, "Preferences updated successfully");
};
