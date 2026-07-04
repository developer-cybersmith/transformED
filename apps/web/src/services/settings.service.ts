import { settingsApi } from '../mocks/api';

export const settingsService = {
    getProfile: () => settingsApi.getUserProfile(),
    getPreferences: () => settingsApi.getLearningPreferences(),
    getNotifications: () => settingsApi.getNotificationSettings(),
    getPrivacy: () => settingsApi.getPrivacySettings(),
    updatePreferences: (updates: Parameters<typeof settingsApi.updateLearningPreferences>[0]) =>
        settingsApi.updateLearningPreferences(updates),
    updateNotifications: (updates: Parameters<typeof settingsApi.updateNotificationSettings>[0]) =>
        settingsApi.updateNotificationSettings(updates),
    updatePrivacy: (updates: Parameters<typeof settingsApi.updatePrivacySettings>[0]) =>
        settingsApi.updatePrivacySettings(updates)
};
