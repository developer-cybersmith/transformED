'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { createClient } from '@/lib/supabase/client';
import { settingsService, singleFieldPatch, type NotificationPreferences } from '@/services/settings.service';

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
    updatePreference: (key: keyof NotificationPreferences, value: boolean) => void;
}

interface QueuedWrite {
    value: boolean;
    /** What to revert to if this specific request fails and nothing newer is queued behind it. */
    rollbackTo: boolean;
}

/**
 * S3-07. Reads `user_notification_preferences` directly from Supabase
 * (own-row, RLS-scoped -- there is no GET endpoint) and writes via the real
 * `PATCH /api/auth/notifications` (settingsService.updateNotifications) --
 * never a direct Supabase write, since that endpoint is the documented sole
 * writer (read-merge-upsert, TOCTOU-safe via the table's PRIMARY KEY).
 *
 * Per-field write serialization (AC-5): the backend's own PATCH handler is
 * last-writer-wins with no version/ETag to reject a conflicting write, so a
 * client-side counter checked only after the fact CANNOT reliably detect
 * which of two already-in-flight requests for the SAME field committed last
 * on the server -- response arrival order does not have to match DB commit
 * order under real network jitter. The only guarantee a pure client can
 * actually make is to never have more than one in-flight request per field:
 * a newer value that arrives while one is in flight is queued, not sent
 * concurrently, and is always sent immediately after the current one
 * settles -- so the LAST value the student chose is always the LAST request
 * made for that field, with no possible reordering.
 */
export function useNotificationPreferences(): UseNotificationPreferencesResult {
    const { user } = useAuth();
    const userId = user?.id;
    const [preferences, setPreferences] = useState<NotificationPreferences>(DEFAULT_PREFERENCES);
    const [isLoading, setIsLoading] = useState(true);
    const mountedRef = useRef(true);
    // Snapshot of the CURRENT user -- lets an in-flight request started under
    // a previous user recognize, once it settles, that it is no longer
    // current (see sendUpdate below). Synced via effect, not during render:
    // updatePreference/sendUpdate only ever run from a user-triggered event,
    // which always happens after mount effects have already flushed.
    const userIdRef = useRef(userId);
    useEffect(() => {
        userIdRef.current = userId;
    }, [userId]);
    // The user's most recently REQUESTED value per field, updated the instant
    // updatePreference is called -- unlike `preferences` state (which only
    // updates on the next render commit), this is correct even when two
    // clicks happen synchronously in the same batch, which the no-op guard
    // below depends on.
    const lastIntentRef = useRef<NotificationPreferences>(DEFAULT_PREFERENCES);
    // Per-field: is a request currently in flight, and what's queued to send
    // once it settles (if any newer click arrived meanwhile).
    const inFlightRef = useRef<Partial<Record<keyof NotificationPreferences, boolean>>>({});
    const pendingRef = useRef<Partial<Record<keyof NotificationPreferences, QueuedWrite>>>({});

    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
        };
    }, []);

    useEffect(() => {
        // A previous user's queued/in-flight writes must never touch a newly
        // signed-in user's state.
        inFlightRef.current = {};
        pendingRef.current = {};

        if (!userId) {
            // eslint-disable-next-line react-hooks/set-state-in-effect
            setIsLoading(false);
            setPreferences(DEFAULT_PREFERENCES);
            lastIntentRef.current = DEFAULT_PREFERENCES;
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
                    lastIntentRef.current = DEFAULT_PREFERENCES;
                    return;
                }
                // No matching row is not a failure -- it just means the user has
                // never touched a toggle yet.
                const loaded = data ?? DEFAULT_PREFERENCES;
                setPreferences(loaded);
                lastIntentRef.current = loaded;
            } catch (err) {
                if (!cancelled) {
                    console.error('useNotificationPreferences: failed to read preferences', err);
                    setPreferences(DEFAULT_PREFERENCES);
                    lastIntentRef.current = DEFAULT_PREFERENCES;
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

    // Drains the pending queue for one field, one request at a time, until
    // nothing is left queued. A loop rather than a self-recursive callback --
    // both send the same one-request-at-a-time guarantee, but a loop needs no
    // reference to its own (still-being-assigned) binding.
    const sendUpdate = useCallback(async (key: keyof NotificationPreferences) => {
        if (inFlightRef.current[key]) return; // already draining -- that call owns the queue now

        for (;;) {
            const queued = pendingRef.current[key];
            if (!queued) return;
            delete pendingRef.current[key];
            inFlightRef.current[key] = true;
            // Captured now, before the await -- but the actual check must run
            // AGAIN after the await, reading userIdRef.current fresh. A
            // snapshot taken now and never re-read would defeat the whole
            // guard: the point is to detect a user switch that happens WHILE
            // this request is in flight, not to record who was current when
            // it started.
            const requestUserId = userIdRef.current;

            try {
                const record = await settingsService.updateNotifications(singleFieldPatch(key, queued.value));
                if (mountedRef.current && userIdRef.current === requestUserId) {
                    // Reconcile with the server's authoritative value rather
                    // than just trusting the optimistic guess.
                    setPreferences((prev) => ({ ...prev, [key]: record[key] }));
                    lastIntentRef.current = { ...lastIntentRef.current, [key]: record[key] };
                }
            } catch (err) {
                console.error('useNotificationPreferences: failed to update preference', err);
                // Only roll back if the student hasn't already chosen a newer
                // value while this request was in flight -- that newer value
                // is about to be sent regardless, so reverting now would just
                // be an extra visible flicker before it self-corrects.
                if (mountedRef.current && userIdRef.current === requestUserId && !pendingRef.current[key]) {
                    setPreferences((prev) => ({ ...prev, [key]: queued.rollbackTo }));
                    lastIntentRef.current = { ...lastIntentRef.current, [key]: queued.rollbackTo };
                }
            }

            inFlightRef.current[key] = false;
            // Loop back around: if a newer value was queued while this
            // request was in flight, send it next; otherwise the `return`
            // above ends the loop on the next iteration.
        }
    }, []);

    const updatePreference = useCallback(
        (key: keyof NotificationPreferences, value: boolean) => {
            if (!userId) return;
            const currentIntent = lastIntentRef.current[key];
            if (currentIntent === value) return;
            lastIntentRef.current = { ...lastIntentRef.current, [key]: value };
            setPreferences((prev) => ({ ...prev, [key]: value }));
            pendingRef.current[key] = { value, rollbackTo: currentIntent };
            void sendUpdate(key);
        },
        [userId, sendUpdate]
    );

    return { preferences, isLoading, updatePreference };
}
