"use client";

import { motion } from "framer-motion";
import clsx from "clsx";

interface ToggleProps {
    enabled: boolean;
    onChange: (enabled: boolean) => void;
}

export function Toggle({ enabled, onChange }: ToggleProps) {
    return (
        <button
            onClick={() => onChange(!enabled)}
            className={clsx(
                "w-11 h-6 flex items-center rounded-full px-1 transition-colors outline-none",
                enabled ? "bg-[var(--accent-primary)]" : "bg-neutral-200"
            )}
        >
            <motion.div
                className="w-4 h-4 bg-white rounded-full shadow-sm"
                layout
                animate={{ x: enabled ? 20 : 0 }}
                transition={{ type: "spring", stiffness: 500, damping: 30 }}
            />
        </button>
    );
}
