'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { paymentService } from '@/services/payment.service';
import type { RazorpayHandlerResponse } from '@/types/payment';

// checkout.js's own global constructor. Declared locally (not in a shared
// global.d.ts) since this hook is the only consumer, same convention as
// Turnstile.tsx's window.turnstile augmentation.
declare global {
    interface Window {
        Razorpay?: new (options: RazorpayOptions) => { open: () => void };
    }
}

interface RazorpayOptions {
    key: string;
    order_id: string;
    amount: number;
    currency: string;
    handler: (response: RazorpayHandlerResponse) => void;
    modal?: { ondismiss?: () => void };
}

export type CheckoutStatus =
    | 'idle'
    | 'creating_order'
    | 'awaiting_payment'
    | 'confirming'
    | 'error'
    | 'timeout';

// Scale & Load Q2: an explicit ceiling, not silent-forever polling.
// Deliberately NOT lessonStatusPoll.ts's 8s/20min constants -- those are
// sized for a multi-minute LLM pipeline, this is a payment webhook that
// Razorpay typically delivers in well under a second.
export const PAYMENT_ACCESS_POLL_INTERVAL_MS = 2000;
export const PAYMENT_ACCESS_POLL_CEILING_MS = 60_000;

function extractErrorMessage(err: unknown): string {
    const status = (err as { response?: { status?: number } })?.response?.status;
    if (status === 404) {
        return 'This lesson could not be found. Please refresh and try again.';
    }
    return 'Could not start checkout. Please try again in a moment.';
}

// Plain module-level recursive function, not a self-referencing useCallback
// (react-hooks/immutability rejects a useCallback body that calls its own
// not-yet-fully-declared binding for a recursive setTimeout reschedule) --
// takes every dependency as a parameter instead of closing over hook state.
function schedulePoll(
    lessonId: string,
    startedAt: number,
    pollTimeoutRef: { current: ReturnType<typeof setTimeout> | null },
    mountedRef: { current: boolean },
    onAccessGranted: (lessonId: string) => void,
    onTimeout: () => void,
    onError: () => void
): void {
    paymentService
        .checkAccess(lessonId)
        .then((res) => {
            if (!mountedRef.current) return;
            if (res.has_access) {
                onAccessGranted(lessonId);
                return;
            }
            const elapsed = Date.now() - startedAt;
            if (elapsed >= PAYMENT_ACCESS_POLL_CEILING_MS) {
                onTimeout();
                return;
            }
            pollTimeoutRef.current = setTimeout(
                () =>
                    schedulePoll(
                        lessonId,
                        startedAt,
                        pollTimeoutRef,
                        mountedRef,
                        onAccessGranted,
                        onTimeout,
                        onError
                    ),
                PAYMENT_ACCESS_POLL_INTERVAL_MS
            );
        })
        .catch(() => {
            if (!mountedRef.current) return;
            onError();
        });
}

interface UseRazorpayCheckoutResult {
    status: CheckoutStatus;
    errorMessage: string | null;
    start: () => void;
}

/**
 * Story 2-53 (S4-02). Owns the full checkout state machine: create-order ->
 * open Razorpay's hosted modal -> on success, poll for access (D136: mocked
 * until GET /api/payments/access exists) -> redirect to the lesson player.
 * `RazorpayCheckoutButton` is a thin presentational wrapper around this.
 */
export function useRazorpayCheckout(lessonId: string): UseRazorpayCheckoutResult {
    const router = useRouter();
    const [status, setStatus] = useState<CheckoutStatus>('idle');
    const [errorMessage, setErrorMessage] = useState<string | null>(null);
    const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const mountedRef = useRef(true);

    useEffect(
        () => () => {
            mountedRef.current = false;
            if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);
        },
        []
    );

    const pollAccess = useCallback(
        (startedAt: number) => {
            schedulePoll(
                lessonId,
                startedAt,
                pollTimeoutRef,
                mountedRef,
                (id) => router.push(`/lesson/${id}`),
                () => setStatus('timeout'),
                () => {
                    setStatus('error');
                    setErrorMessage(
                        'Could not confirm your payment. Please contact support if you were charged.'
                    );
                }
            );
        },
        [lessonId, router]
    );

    const start = useCallback(() => {
        setStatus('creating_order');
        setErrorMessage(null);

        paymentService
            .createOrder(lessonId)
            .then((order) => {
                if (!mountedRef.current) return;
                if (typeof window === 'undefined' || !window.Razorpay) {
                    setStatus('error');
                    setErrorMessage('Payment could not start — please refresh and try again.');
                    return;
                }
                setStatus('awaiting_payment');
                const rzp = new window.Razorpay({
                    key: order.key_id,
                    order_id: order.order_id,
                    amount: order.price_paise,
                    currency: 'INR',
                    handler: () => {
                        if (!mountedRef.current) return;
                        setStatus('confirming');
                        pollAccess(Date.now());
                    },
                    modal: {
                        ondismiss: () => {
                            // Student closed the modal without paying (AC-5:
                            // no dedicated cancel page) -- just return to the
                            // pre-click state so they can retry.
                            if (mountedRef.current) setStatus('idle');
                        },
                    },
                });
                rzp.open();
            })
            .catch((err: unknown) => {
                if (!mountedRef.current) return;
                setStatus('error');
                setErrorMessage(extractErrorMessage(err));
            });
    }, [lessonId, pollAccess]);

    return { status, errorMessage, start };
}
