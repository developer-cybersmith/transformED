"use client";

import { useEffect, useState } from "react";
import { motion, useMotionValue, useSpring } from "framer-motion";

export default function MouseAmbientGlow() {
    const [isMounted, setIsMounted] = useState(false);

    // Only initialized on client. Defaults to center of screen usually.
    const mouseX = useMotionValue(typeof window !== "undefined" ? window.innerWidth / 2 : 0);
    const mouseY = useMotionValue(typeof window !== "undefined" ? window.innerHeight / 2 : 0);

    // Highly damped spring for floaty, organic, slow movement
    const smoothX = useSpring(mouseX, { damping: 100, stiffness: 20, mass: 3 });
    const smoothY = useSpring(mouseY, { damping: 100, stiffness: 20, mass: 3 });

    useEffect(() => {
        // SSR-hydration-safe mount flag: server and pre-hydration client render
        // must both produce `null` (window is undefined server-side), then this
        // flips to true post-hydration to reveal the client-only glow. This is
        // the standard mount-detection idiom and genuinely requires a setState
        // call in an effect — there is no render-time equivalent.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setIsMounted(true);
        if (typeof window !== "undefined") {
            mouseX.set(window.innerWidth / 2);
            mouseY.set(window.innerHeight / 2);
        }

        const handleMouseMove = (e: MouseEvent) => {
            mouseX.set(e.clientX);
            mouseY.set(e.clientY);
        };

        window.addEventListener("mousemove", handleMouseMove);
        return () => window.removeEventListener("mousemove", handleMouseMove);
    }, [mouseX, mouseY]);

    if (!isMounted) return null;

    return (
        <div className="fixed inset-0 pointer-events-none overflow-hidden hidden md:block -z-10">
            <motion.div
                className="absolute w-[800px] h-[800px] -ml-[400px] -mt-[400px] rounded-full blur-[80px] bg-[radial-gradient(circle_at_center,rgba(7,23,44,0.12)_0%,transparent_60%)]"
                style={{
                    x: smoothX,
                    y: smoothY,
                }}
            />
        </div>
    );
}
