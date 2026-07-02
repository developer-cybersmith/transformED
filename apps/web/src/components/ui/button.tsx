"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { HTMLMotionProps, motion } from "framer-motion";

export interface ButtonProps extends Omit<HTMLMotionProps<"button">, "ref"> {
    variant?: "primary" | "secondary" | "outline" | "ghost";
    size?: "sm" | "md" | "lg";
    isLoading?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
    ({ className, variant = "primary", size = "md", isLoading, children, ...props }, ref) => {

        // Using motion button for subtle scaling
        return (
            <motion.button
                whileHover={{ scale: 1.01 }}
                whileTap={{ scale: 0.98 }}
                className={cn(
                    "inline-flex items-center justify-center rounded-2xl text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--accent-primary)]/20 disabled:pointer-events-none disabled:opacity-50",
                    {
                        "bg-[var(--accent-secondary)] text-[var(--accent-primary)] shadow-lg shadow-[var(--accent-secondary)]/30 hover:shadow-[var(--accent-secondary)]/50 hover:brightness-105": variant === "primary",
                        "bg-white text-neutral-800 border border-neutral-200/50 hover:bg-neutral-50 shadow-sm": variant === "secondary",
                        "border border-neutral-200 bg-transparent hover:bg-neutral-50 text-neutral-800": variant === "outline",
                        "hover:bg-neutral-100 text-neutral-600 hover:text-neutral-900": variant === "ghost",
                        "h-9 px-4 py-2": size === "sm",
                        "h-12 px-8 py-3": size === "md",
                        "h-14 px-10 py-4 text-base": size === "lg"
                    },
                    className
                )}
                ref={ref}
                disabled={isLoading || props.disabled}
                {...props}
            >
                {isLoading ? (
                    <div className="flex items-center gap-2">
                        <svg className="animate-spin h-5 w-5 text-current" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                        </svg>
                        Loading...
                    </div>
                ) : (
                    children
                )}
            </motion.button>
        );
    }
);
Button.displayName = "Button";

export { Button };
