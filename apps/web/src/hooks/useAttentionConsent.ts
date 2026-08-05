'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { createClient } from '@/lib/supabase/client';
import { usersService } from '@/services/users.service';

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
 * consent modal should show. `accept()`/`decline()` both record a local
 * "already asked" marker (AC-5) purely to avoid re-prompting every lesson;
 * that marker is never itself read as consent.
 */
export function useAttentionConsent(): UseAttentionConsentResult {
    const { user } = useAuth();
    const [consentStatus, setConsentStatus] = useState<AttentionConsentStatus>('unknown');
    const [isLoading, setIsLoading] = useState(true);
    const [dismissed, setDismissed] = useState(false);
    const [readFailed, setReadFailed] = useState(false);

    useEffect(() => {
        if (!user) return;
        let cancelled = false;

        // Deliberately synchronous: a consumer's first render after `user`
        // changes (e.g. a fresh sign-in) must see isLoading=true immediately,
        // not a one-tick flash of a stale prior result — same pattern as
        // useLessonSocket.ts's own synchronous setStatus('connecting').
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setIsLoading(true);
        setDismissed(readDismissed(user.id));

        const supabase = createClient();

        async function loadConsent() {
            try {
                const { data, error } = await supabase
                    .from('users')
                    .select('attention_consent')
                    .eq('id', user!.id)
                    .maybeSingle<{ attention_consent: boolean | null }>();
                if (cancelled) return;
                if (error || !data) {
                    // AC-9: a transient read failure must not force-block the
                    // student behind a modal that can't know the real answer --
                    // degrade to NOT showing it, rather than crashing or nagging.
                    setReadFailed(true);
                    setConsentStatus('unknown');
                    return;
                }
                setReadFailed(false);
                setConsentStatus(data.attention_consent === true ? 'accepted' : 'unknown');
            } catch {
                if (!cancelled) {
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
    }, [user]);

    const markDismissed = useCallback(() => {
        if (!user) return;
        writeDismissed(user.id);
        setDismissed(true);
    }, [user]);

    const accept = useCallback(async () => {
        await usersService.setAttentionConsent(true);
        setConsentStatus('accepted');
        markDismissed();
    }, [markDismissed]);

    const decline = useCallback(() => {
        // No API call: there is nothing to accept, and there is no backend
        // field for "declined" to write (Dev Notes -- do not invent one).
        setConsentStatus('declined');
        markDismissed();
    }, [markDismissed]);

    const showModal =
        !isLoading && !readFailed && consentStatus === 'unknown' && !dismissed;

    return { consentStatus, isLoading, showModal, accept, decline };
}
