import { randomDelay } from '../utils/delay';
import { createSuccessResponse, ApiResponse } from '../utils/response';
import { mockUser, UserProfile, LearningPreferences, NotificationSettings, PrivacySettings } from '../data/users';

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

export const updateNotificationSettings = async (updates: Partial<NotificationSettings>): Promise<ApiResponse<NotificationSettings>> => {
    await randomDelay(400, 800);
    mockUser.notifications = { ...mockUser.notifications, ...updates };
    return createSuccessResponse(mockUser.notifications, "Notification settings updated successfully");
};

export const getPrivacySettings = async (): Promise<ApiResponse<PrivacySettings>> => {
    await randomDelay(200, 500);
    return createSuccessResponse(mockUser.privacy, "Privacy settings retrieved");
};

export const updatePrivacySettings = async (updates: Partial<PrivacySettings>): Promise<ApiResponse<PrivacySettings>> => {
    await randomDelay(400, 800);
    mockUser.privacy = { ...mockUser.privacy, ...updates };
    return createSuccessResponse(mockUser.privacy, "Privacy settings updated successfully");
};
