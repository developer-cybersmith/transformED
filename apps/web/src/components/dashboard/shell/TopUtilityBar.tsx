"use client";

import { Search, Bell, Flame } from "lucide-react";
import { motion } from "framer-motion";
import { Input } from "@/components/ui/input";

export function TopUtilityBar() {
    return (
        <header className="flex-shrink-0 h-24 px-8 lg:px-12 flex items-center justify-between relative z-40">

            {/* Search Widget */}
            <div className="flex-1 max-w-sm hidden md:flex">
                <div className="relative w-full group">
                    <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                        <Search className="h-4 w-4 text-neutral-400 group-focus-within:text-[var(--accent-primary)] transition-colors" />
                    </div>
                    <input
                        suppressHydrationWarning
                        type="text"
                        className="block w-full pl-11 pr-4 py-2.5 rounded-2xl border-0 bg-white/60 backdrop-blur-md shadow-[0_2px_10px_-4px_rgba(0,0,0,0.05)] text-sm placeholder:text-neutral-400 focus:ring-2 focus:ring-[var(--accent-primary)]/20 focus:bg-white transition-all duration-300 placeholder:font-light text-neutral-800"
                        placeholder="Search lessons, concepts..."
                    />
                </div>
            </div>

            <div className="flex items-center gap-6 ml-auto">

                {/* Subtle Streak Indicator */}
                <div className="hidden sm:flex items-center gap-2 px-4 py-2 bg-orange-50/80 text-orange-600 rounded-full border border-orange-100/50 shadow-sm">
                    <Flame className="w-4 h-4 fill-orange-500 animate-pulse" />
                    <span className="text-xs font-semibold tracking-wide">5 Day Streak</span>
                </div>

                {/* Notifications */}
                <button suppressHydrationWarning className="relative w-10 h-10 flex items-center justify-center rounded-full bg-white/60 hover:bg-white border border-neutral-100 shadow-sm transition-colors text-neutral-500 hover:text-neutral-800">
                    <Bell className="w-5 h-5" />
                    <span className="absolute top-2.5 right-2.5 w-2 h-2 bg-[var(--accent-primary)] rounded-full ring-2 ring-white" />
                </button>

                {/* Profile Dropdown Placeholder */}
                <button suppressHydrationWarning className="relative group focus:outline-none flex items-center gap-3 pl-3 pr-2 py-1.5 rounded-full hover:bg-neutral-100/50 transition-colors">
                    <div className="w-9 h-9 rounded-full bg-gradient-to-tr from-[var(--accent-primary)] to-[var(--accent-secondary)] flex items-center justify-center text-white font-medium text-sm shadow-md overflow-hidden">
                        <img src="https://ui-avatars.com/api/?name=J+O&background=random&color=fff" alt="Profile" className="w-full h-full object-cover" />
                    </div>
                </button>
            </div>
        </header>
    );
}
