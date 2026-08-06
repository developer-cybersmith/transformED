'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { createClient } from '@/lib/supabase/client';

export type AttentionConsentStatus = 'accepted' | 'declined' | 'unknown';

interface UseAttentionConsentResult {
    consentStatus: AttentionConsentStatus;
    isLoading: boolean;
    /**
     * True only once a fresh Supabase read confirms consent is not yet
     * `true`, the read itself succeeded, and the student hasn't already been
     * asked-and-answered on this device (AC-5). NEVER the security-relevant
     * gate for whether monitoring may start (AC-4) — that must always be a
     * fresh Supabase read of its own, wherever AttentionMonitor (S3-02, not
     * built yet) ends up doing it.
     */
    showModal: boolean;
    accept: () => Promise<void>;
    decline: () => void;
}

// Tracks which version of the attention-tracking disclosure copy the
// student consented to (DPDP Act 2023 audit requirement). Bump this if the
// disclosure text in AttentionConsentModal changes materially.
const ATTENTION_CONSENT_POLICY_VERSION = '1.0';

function dismissalKey(userId: string): string {
    return `hie:attention-consent-dismissed:${userId}`;
}

function readDismissed(userId: string): boolean {
    try {
        return localStorage.getItem(dismissalKey(userId)) === '1';
    } catch {
        // Storage inaccessible -- treat as not dismissed. Worst case the
        // modal shows again; that is never worse than the alternative.
        return false;
    }
}

function writeDismissed(userId: string): void {
    try {
        localStorage.setItem(dismissalKey(userId), '1');
    } catch {
        // Storage inaccessible -- the modal may reappear next time, which is
        // the safe direction to fail in.
    }
}

/**
 * S3-01. Reads `users.attention_consent` fresh from Supabase on every mount
 * (AC-4 — never trusted from a client-only cache) and derives whether the
 * consent modal should show. `accept()` records the choice by inserting
 * directly into `public.user_consents` (RLS: insert own row) — a trigger on
 * that table syncs `users.attention_consent = true`, so no backend endpoint
 * is required. `decline()` records only a local "already asked" marker
 * (AC-5) purely to avoid re-prompting every lesson; that marker is never
 * itself read as consent, and the schema has no slot for a recorded refusal
 * (`user_consents.consent_type` only allows `'attention_tracking'` /
 * `'learner_dna'`) — accepted as-is per the 2026-08-06 review.
 */
export function useAttentionConsent(): UseAttentionConsentResult {
    const { user } = useAuth();
    const userId = user?.id;
    const [consentStatus, setConsentStatus] = useState<AttentionConsentStatus>('unknown');
    const [isLoading, setIsLoading] = useState(true);
    const [dismissed, setDismissed] = useState(false);
    const [readFailed, setReadFailed] = useState(false);
    // Guards a resolved accept() against overwriting a more recent decline()
    // (or vice versa) made while the other's async call was still in flight.
    const requestIdRef = useRef(0);

    useEffect(() => {
        if (!userId) {
            // Signed out (or not yet authenticated): nothing to check, and
            // isLoading must still resolve rather than spin forever for a
            // consumer that never becomes authenticated.
            // eslint-disable-next-line react-hooks/set-state-in-effect
            setIsLoading(false);
            setConsentStatus('unknown');
            setReadFailed(false);
            return;
        }

        let cancelled = false;

        // Deliberately synchronous: a consumer's first render after `userId`
        // changes (e.g. a fresh sign-in) must see isLoading=true immediately,
        // not a one-tick flash of a stale prior result — same pattern as
        // useLessonSocket.ts's own synchronous setStatus('connecting').
        setIsLoading(true);
        setReadFailed(false);
        setDismissed(readDismissed(userId));

        const supabase = createClient();

        async function loadConsent() {
            try {
                const { data, error } = await supabase
                    .from('users')
                    .select('attention_consent')
                    .eq('id', userId!)
                    .maybeSingle<{ attention_consent: boolean | null }>();
                if (cancelled) return;
                if (error) {
                    // AC-9: a transient read failure must not force-block the
                    // student behind a modal that can't know the real answer --
                    // degrade to NOT showing it, rather than crashing or nagging.
                    console.error('useAttentionConsent: failed to read consent status', error);
                    setReadFailed(true);
                    setConsentStatus('unknown');
                    return;
                }
                // No matching row (`data === null`) is not a read failure --
                // it just means consent isn't recorded yet, same as an
                // explicit `false`/`null` value on an existing row.
                setReadFailed(false);
                setConsentStatus(data?.attention_consent === true ? 'accepted' : 'unknown');
            } catch (err) {
                if (!cancelled) {
                    console.error('useAttentionConsent: failed to read consent status', err);
                    setReadFailed(true);
                    setConsentStatus('unknown');
                }
            } finally {
                if (!cancelled) setIsLoading(false);
            }
        }

        void loadConsent();

        return () => {
            cancelled = true;
        };
        // Keyed on the primitive id, not the `user` object: AuthContext
        // rebuilds a new `user` object literal on every TOKEN_REFRESHED
        // event even when the id hasn't changed, which would otherwise
        // re-fire this read on every token refresh, not just real sign-in.
    }, [userId]);

    const markDismissed = useCallback(() => {
        if (!userId) return;
        writeDismissed(userId);
        setDismissed(true);
    }, [userId]);

    const accept = useCallback(async () => {
        if (!userId) return;
        const requestId = ++requestIdRef.current;
        try {
            const supabase = createClient();
            const { error } = await supabase.from('user_consents').insert({
                user_id: userId,
                consent_type: 'attention_tracking',
                policy_version: ATTENTION_CONSENT_POLICY_VERSION,
            });
            if (error) throw error;
        } catch (err) {
            console.error('useAttentionConsent: failed to record consent', err);
            throw err;
        }
        // A decline() made while this insert was in flight is the student's
        // most recent, authoritative choice -- do not overwrite it.
        if (requestId !== requestIdRef.current) return;
        setConsentStatus('accepted');
        markDismissed();
    }, [userId, markDismissed]);

    const decline = useCallback(() => {
        // No API call: there is nothing to accept, and there is no backend
        // field for "declined" to write (Dev Notes -- do not invent one).
        // Invalidates any in-flight accept() so its resolution can't
        // silently overwrite this more recent choice.
        requestIdRef.current += 1;
        setConsentStatus('declined');
        markDismissed();
    }, [markDismissed]);

    const showModal =
        !!userId && !isLoading && !readFailed && consentStatus === 'unknown' && !dismissed;

    return { consentStatus, isLoading, showModal, accept, decline };
}
