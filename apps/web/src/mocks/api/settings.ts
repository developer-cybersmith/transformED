import { randomDelay } from '../utils/delay';
import { createSuccessResponse, ApiResponse } from '../utils/response';
import { mockUser, UserProfile, LearningPreferences, PrivacySettings } from '../data/users';

export const getUserProfile = async (): Promise<ApiResponse<UserProfile>> => {
    await randomDelay(200, 500);
    return createSuccessResponse(mockUser.profile, "Profile retrieved");
};

export const getLearningPreferences = async (): Promise<ApiResponse<LearningPreferences>> => {
    await randomDelay(200, 500);
    return createSuccessResponse(mockUser.preferences, "Preferences retrieved");
};

export const updateLearningPreferences = async (updates: Partial<LearningPreferences>): Promise<ApiResponse<LearningPreferences>> => {
    await randomDelay(400, 800);
    mockUser.preferences = { ...mockUser.preferences, ...updates };
    return createSuccessResponse(mockUser.preferences, "Preferences updated successfully");
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
