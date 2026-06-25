"use client";

import { motion } from "framer-motion";
import clsx from "clsx";

export interface SegmentedControlProps {
    options: { value: string; label: string }[];
    value: string;
    onChange: (val: string) => void;
}

export function SegmentedControl({ options, value, onChange }: SegmentedControlProps) {
    return (
        <div className="flex bg-neutral-100/80 p-1 rounded-xl w-fit relative border border-neutral-200/50">
            {options.map((option) => {
                const isActive = value === option.value;
                return (
                    <button
                        key={option.value}
                        onClick={() => onChange(option.value)}
                        className={clsx(
                            "relative px-4 py-2 text-sm font-medium rounded-lg transition-colors outline-none z-10",
                            isActive ? "text-neutral-900" : "text-neutral-500 hover:text-neutral-700"
                        )}
                        style={{ WebkitTapHighlightColor: "transparent" }}
                    >
                        {isActive && (
                            <motion.div
                                layoutId={`segmented-control-${options.map(o => o.value).join("-")}`}
                                className="absolute inset-0 bg-white rounded-lg shadow-sm border border-neutral-200/40 z-[-1]"
                                transition={{ type: "spring", bounce: 0.15, duration: 0.5 }}
                            />
                        )}
                        {option.label}
                    </button>
                );
            })}
        </div>
    );
}
