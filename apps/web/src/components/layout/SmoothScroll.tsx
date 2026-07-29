"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import Lenis from "lenis";

export default function SmoothScroll({
    children,
}: {
    children: React.ReactNode;
}) {
    const lenisRef = useRef<Lenis | null>(null);
    const pathname = usePathname();

    useEffect(() => {
        const lenis = new Lenis({
            duration: 1.2,
            easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)), // expoOut easing
            orientation: "vertical",
            gestureOrientation: "vertical",
            smoothWheel: true,
            wheelMultiplier: 1,
            touchMultiplier: 2,
        });

        lenisRef.current = lenis;

        function raf(time: number) {
            lenis.raf(time);
            requestAnimationFrame(raf);
        }

        requestAnimationFrame(raf);

        // Lenis only measures scrollable height at init (and when we call
        // resize() below on route change) -- it does NOT observe DOM
        // mutations on its own. Any page whose content grows after mount
        // (SWR-fetched dashboard sections, images, async lists, etc.) leaves
        // Lenis's cached scroll bounds stale: the mouse wheel gets "stuck" at
        // the old (shorter) height while a native scrollbar drag -- which
        // reads the real DOM directly, bypassing Lenis -- still works fine.
        // This is exactly that symptom, recurring on whichever page loads
        // content asynchronously. Observing document.body's size and calling
        // resize() on every change fixes it generally, not just for one page.
        let rafId: number | null = null;
        const resizeObserver = new ResizeObserver(() => {
            if (rafId !== null) return; // coalesce bursts of mutations into one resize
            rafId = requestAnimationFrame(() => {
                lenis.resize();
                rafId = null;
            });
        });
        resizeObserver.observe(document.body);

        return () => {
            resizeObserver.disconnect();
            if (rafId !== null) cancelAnimationFrame(rafId);
            lenis.destroy();
        };
    }, []);

    // Reset scroll and force recalculation on route changes
    useEffect(() => {
        if (lenisRef.current) {
            lenisRef.current.scrollTo(0, { immediate: true });
            setTimeout(() => {
                window.dispatchEvent(new Event("resize"));
                lenisRef.current?.resize();
            }, 100);
        }
    }, [pathname]);

    return <>{children}</>;
}
