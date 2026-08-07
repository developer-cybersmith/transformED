'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { createClient } from '@/lib/supabase/client';
import { settingsService, type NotificationPreferences } from '@/services/settings.service';

export type { NotificationPreferences };

// Mirrors apps/api/app/modules/auth/router.py's _NOTIF_DEFAULTS exactly, and
// the migration's column DEFAULT clauses -- never invent a different default
// here, or a new user's first render would show a value the backend would
// not actually apply on their first real write.
const DEFAULT_PREFERENCES: NotificationPreferences = {
    session_report_email: true,
    lesson_ready_email: true,
    weekly_progress_email: true,
    streak_reminders: true,
};

interface UseNotificationPreferencesResult {
    preferences: NotificationPreferences;
    isLoading: boolean;
    updatePreference: (key: keyof NotificationPreferences, value: boolean) => Promise<void>;
}

/**
 * S3-07. Reads `user_notification_preferences` directly from Supabase
 * (own-row, RLS-scoped -- there is no GET endpoint) and writes via the real
 * `PATCH /api/auth/notifications` (settingsService.updateNotifications) --
 * never a direct Supabase write, since that endpoint is the documented sole
 * writer (read-merge-upsert, TOCTOU-safe via the table's PRIMARY KEY).
 */
export function useNotificationPreferences(): UseNotificationPreferencesResult {
    const { user } = useAuth();
    const userId = user?.id;
    const [preferences, setPreferences] = useState<NotificationPreferences>(DEFAULT_PREFERENCES);
    const [isLoading, setIsLoading] = useState(true);
    // AC-5: per-field request-generation counter. A stale request's rollback
    // must never overwrite a value a more recent request has since set.
    const requestGenerationRef = useRef<Partial<Record<keyof NotificationPreferences, number>>>({});

    useEffect(() => {
        if (!userId) {
            // eslint-disable-next-line react-hooks/set-state-in-effect
            setIsLoading(false);
            setPreferences(DEFAULT_PREFERENCES);
            return;
        }

        let cancelled = false;

        setIsLoading(true);

        const supabase = createClient();

        async function loadPreferences() {
            try {
                const { data, error } = await supabase
                    .from('user_notification_preferences')
                    .select('session_report_email,lesson_ready_email,weekly_progress_email,streak_reminders')
                    .eq('user_id', userId!)
                    .maybeSingle<NotificationPreferences>();
                if (cancelled) return;
                if (error) {
                    // A transient read failure must not strand the student on a
                    // permanently-loading settings tab -- degrade to the same
                    // defaults a brand-new user would see, but log it (unlike
                    // the "no row yet" case, this IS unexpected).
                    console.error('useNotificationPreferences: failed to read preferences', error);
                    setPreferences(DEFAULT_PREFERENCES);
                    return;
                }
                // No matching row is not a failure -- it just means the user has
                // never touched a toggle yet.
                setPreferences(data ?? DEFAULT_PREFERENCES);
            } catch (err) {
                if (!cancelled) {
                    console.error('useNotificationPreferences: failed to read preferences', err);
                    setPreferences(DEFAULT_PREFERENCES);
                }
            } finally {
                if (!cancelled) setIsLoading(false);
            }
        }

        void loadPreferences();

        return () => {
            cancelled = true;
        };
    }, [userId]);

    const updatePreference = useCallback(
        async (key: keyof NotificationPreferences, value: boolean) => {
            const previous = preferences[key];
            const myGeneration = (requestGenerationRef.current[key] ?? 0) + 1;
            requestGenerationRef.current[key] = myGeneration;

            setPreferences((prev) => ({ ...prev, [key]: value }));

            try {
                await settingsService.updateNotifications({ [key]: value });
            } catch (err) {
                console.error('useNotificationPreferences: failed to update preference', err);
                // Only roll back if no newer request for this same field has
                // been issued since -- otherwise this stale failure would
                // stomp a more recent (possibly already-successful) change.
                if (requestGenerationRef.current[key] === myGeneration) {
                    setPreferences((prev) => ({ ...prev, [key]: previous }));
                }
            }
        },
        [preferences]
    );

    return { preferences, isLoading, updatePreference };
}
