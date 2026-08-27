'use client';

import Script from 'next/script';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { useRazorpayCheckout } from '@/hooks/useRazorpayCheckout';

interface RazorpayCheckoutButtonProps {
    lessonId: string;
}

const STATUS_LABEL: Record<string, string> = {
    creating_order: 'Starting checkout…',
    awaiting_payment: 'Waiting for payment…',
    confirming: 'Confirming payment…',
};

/**
 * Story 2-53 (S4-02). Renders "Buy Lesson", opens Razorpay's own hosted
 * checkout overlay (no custom card form -- card/UPI data never touches this
 * app), and redirects to the lesson player once payment is confirmed.
 *
 * checkout.js is loaded via next/script with strategy="afterInteractive" --
 * Next.js dedupes by `src` across every mounted instance of this component,
 * so it is fetched exactly once per page regardless of how many buttons
 * render (AC-2), same guarantee Turnstile.tsx already relies on for
 * Cloudflare's script.
 */
export function RazorpayCheckoutButton({ lessonId }: RazorpayCheckoutButtonProps) {
    const [scriptReady, setScriptReady] = useState(false);
    // Review finding (Blind Hunter, Edge Case Hunter, Scale & Load Hunter):
    // `onReady` alone left the button disabled forever with zero feedback if
    // checkout.js failed to load (ad-blocker, CDN outage) -- `scriptReady`
    // would just never flip true. This surfaces that failure explicitly
    // instead of a silent-forever-disabled button.
    const [scriptError, setScriptError] = useState(false);
    const { status, errorMessage, start } = useRazorpayCheckout(lessonId);

    const busy = status === 'creating_order' || status === 'awaiting_payment' || status === 'confirming';

    return (
        <div>
            <Script
                src="https://checkout.razorpay.com/v1/checkout.js"
                strategy="afterInteractive"
                onReady={() => setScriptReady(true)}
                onError={() => setScriptError(true)}
            />
            <Button onClick={start} disabled={busy || !scriptReady || scriptError} isLoading={busy}>
                {STATUS_LABEL[status] ?? 'Buy Lesson'}
            </Button>
            {scriptError && (
                <p role="alert" className="mt-2 text-sm text-red-600">
                    Could not load the payment provider. Please check your connection (or
                    disable any ad-blocker) and refresh the page.
                </p>
            )}
            {status === 'error' && errorMessage && (
                <p role="alert" className="mt-2 text-sm text-red-600">
                    {errorMessage}
                </p>
            )}
            {status === 'timeout' && (
                <p role="alert" className="mt-2 text-sm text-amber-600">
                    Still confirming your payment — this is taking longer than expected. If
                    this persists, please contact support with your payment reference.
                </p>
            )}
        </div>
    );
}
