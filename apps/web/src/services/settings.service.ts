import { settingsApi } from '../mocks/api';

export const settingsService = {
    getProfile: () => settingsApi.getUserProfile(),
    getPreferences: () => settingsApi.getLearningPreferences(),
    getNotifications: () => settingsApi.getNotificationSettings(),
    updatePreferences: (updates: Parameters<typeof settingsApi.updateLearningPreferences>[0]) =>
        settingsApi.updateLearningPreferences(updates)
};
