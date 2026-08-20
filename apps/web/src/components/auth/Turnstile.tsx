"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import Script from "next/script";

declare global {
    interface Window {
        turnstile?: {
            render: (container: HTMLElement, options: Record<string, unknown>) => string;
            reset: (widgetId: string) => void;
            remove: (widgetId: string) => void;
        };
    }
}

interface TurnstileWidgetProps {
    onVerify: (token: string) => void;
    onExpire: () => void;
}

export interface TurnstileHandle {
    reset: () => void;
}

// Renders Cloudflare's hosted widget directly (no wrapper npm package) --
// see https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/
export const TurnstileWidget = forwardRef<TurnstileHandle, TurnstileWidgetProps>(
    function TurnstileWidget({ onVerify, onExpire }, ref) {
        const containerRef = useRef<HTMLDivElement>(null);
        const widgetIdRef = useRef<string | null>(null);

        const render = () => {
            if (!window.turnstile || !containerRef.current || widgetIdRef.current) return;
            widgetIdRef.current = window.turnstile.render(containerRef.current, {
                sitekey: process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY,
                callback: onVerify,
                "expired-callback": onExpire,
                "error-callback": onExpire
            });
        };

        useImperativeHandle(ref, () => ({
            reset: () => {
                if (widgetIdRef.current) {
                    window.turnstile?.reset(widgetIdRef.current);
                }
            }
        }));

        useEffect(() => {
            return () => {
                if (widgetIdRef.current) {
                    window.turnstile?.remove(widgetIdRef.current);
                    widgetIdRef.current = null;
                }
            };
        }, []);

        return (
            <>
                {/* onReady fires on every mount, including when the script
                    is already cached from a prior page -- Next.js guarantees
                    this for next/script, so no separate "already loaded" check
                    is needed here. */}
                <Script
                    src="https://challenges.cloudflare.com/turnstile/v0/api.js"
                    strategy="afterInteractive"
                    onReady={render}
                />
                <div ref={containerRef} />
            </>
        );
    }
);
