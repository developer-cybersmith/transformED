import { settingsApi } from '../mocks/api';
import { api } from '@/lib/api';

// Matches apps/api/app/modules/auth/router.py::NotificationPatchRequest /
// NotificationPreferencesResponse exactly (Story 4-23 / D60) -- snake_case,
// not remapped to camelCase, so the wire shape and the type never drift.
export interface NotificationPreferences {
    session_report_email: boolean;
    lesson_ready_email: boolean;
    weekly_progress_email: boolean;
    streak_reminders: boolean;
}

// A union of single-key objects, not Partial<T> -- Partial<T> permits `{}`,
// which the backend 422s on (AC-7: "at least one field required"). This
// makes an empty or multi-field patch a compile error, not just a
// call-site convention to remember.
type AtLeastOneKey<T> = { [K in keyof T]: Pick<T, K> }[keyof T];
export type NotificationPreferencesPatch = AtLeastOneKey<NotificationPreferences>;

// The only way to construct a NotificationPreferencesPatch -- a computed-key
// object literal (`{ [key]: value }`) can't be proven single-field by the
// compiler, so the one cast needed lives here, justified by this function's
// own signature, instead of being repeated at every call site.
export function singleFieldPatch<K extends keyof NotificationPreferences>(
    key: K,
    value: NotificationPreferences[K]
): NotificationPreferencesPatch {
    return { [key]: value } as NotificationPreferencesPatch;
}

export interface NotificationPreferencesRecord extends NotificationPreferences {
    user_id: string;
    updated_at: string;
}

export const settingsService = {
    getProfile: () => settingsApi.getUserProfile(),
    getPreferences: () => settingsApi.getLearningPreferences(),
    getPrivacy: () => settingsApi.getPrivacySettings(),
    updatePreferences: (updates: Parameters<typeof settingsApi.updateLearningPreferences>[0]) =>
        settingsApi.updateLearningPreferences(updates),
    // PATCH /api/auth/notifications is the real, sole writer for notification
    // preferences (Story 4-23) -- there is no GET; reads happen via a direct
    // Supabase own-row query (see useNotificationPreferences.ts).
    updateNotifications: (patch: NotificationPreferencesPatch): Promise<NotificationPreferencesRecord> =>
        api.patch<NotificationPreferencesRecord>('auth/notifications', patch).then((r) => r.data),
    updatePrivacy: (updates: Parameters<typeof settingsApi.updatePrivacySettings>[0]) =>
        settingsApi.updatePrivacySettings(updates)
};
