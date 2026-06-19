"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export interface InputProps
    extends React.InputHTMLAttributes<HTMLInputElement> {
    icon?: React.ReactNode;
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
    ({ className, type, icon, ...props }, ref) => {
        return (
            <div className="relative group">
                {icon && (
                    <div className="absolute left-4 top-1/2 -translate-y-1/2 text-neutral-800/100 group-focus-within:text-[var(--accent-primary)] transition-colors duration-300 pointer-events-none z-10">
                        {icon}
                    </div>
                )}
                <input
                    type={type}
                    className={cn(
                        "flex h-12 w-full rounded-2xl border border-neutral-200/50 bg-white/50 px-4 py-2 text-sm text-neutral-800 shadow-[0_2px_10px_-4px_rgba(0,0,0,0.05)] backdrop-blur-sm transition-all duration-300",
                        "file:border-0 file:bg-transparent file:text-sm file:font-medium",
                        "placeholder:text-neutral-400",
                        "focus-visible:outline-none focus-visible:border-[var(--accent-primary)] focus-visible:ring-4 focus-visible:ring-[var(--accent-primary)]/10 focus-visible:bg-white",
                        "disabled:cursor-not-allowed disabled:opacity-50",
                        icon && "pl-11",
                        className
                    )}
                    ref={ref}
                    {...props}
                />
            </div>
        );
    }
);
Input.displayName = "Input";

export { Input };
