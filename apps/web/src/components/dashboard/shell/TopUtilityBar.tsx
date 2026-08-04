"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Search, Bell, Flame, Settings, LogOut, Menu, X } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useAuth } from "@/contexts/AuthContext";
import { getInitials, cn } from "@/lib/utils";
import { mainNavItems } from "@/components/dashboard/shell/Sidebar";

export function TopUtilityBar() {
    const { user, logout } = useAuth();
    const pathname = usePathname();
    const [isProfileMenuOpen, setIsProfileMenuOpen] = useState(false);
    const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
    const profileMenuRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!isProfileMenuOpen) return;

        function handleClickOutside(event: MouseEvent) {
            if (profileMenuRef.current && !profileMenuRef.current.contains(event.target as Node)) {
                setIsProfileMenuOpen(false);
            }
        }
        // Review fix: menu exposed aria-haspopup/aria-expanded but had no
        // keyboard way to dismiss it.
        function handleEscape(event: KeyboardEvent) {
            if (event.key === "Escape") setIsProfileMenuOpen(false);
        }

        document.addEventListener("mousedown", handleClickOutside);
        document.addEventListener("keydown", handleEscape);
        return () => {
            document.removeEventListener("mousedown", handleClickOutside);
            document.removeEventListener("keydown", handleEscape);
        };
    }, [isProfileMenuOpen]);

    // Sidebar (the only place these routes were reachable from) is `hidden
    // lg:flex` with no mobile equivalent -- below lg a logged-in user had no
    // way to reach Dashboard/Library/Upload/Reports except typing the URL.
    useEffect(() => {
        if (!isMobileNavOpen) return;

        function handleEscape(event: KeyboardEvent) {
            if (event.key === "Escape") setIsMobileNavOpen(false);
        }

        document.addEventListener("keydown", handleEscape);
        return () => document.removeEventListener("keydown", handleEscape);
    }, [isMobileNavOpen]);

    const displayName = user?.full_name || user?.email || "Guest";

    return (
        <header className="flex-shrink-0 h-24 px-8 lg:px-12 flex items-center justify-between relative z-40">

            {/* Mobile Nav Toggle — Sidebar is hidden below lg with no other entry point */}
            <button
                suppressHydrationWarning
                type="button"
                onClick={() => setIsMobileNavOpen((open) => !open)}
                aria-label="Toggle navigation menu"
                aria-haspopup="menu"
                aria-expanded={isMobileNavOpen}
                className="lg:hidden mr-3 w-10 h-10 flex items-center justify-center rounded-full bg-white/60 hover:bg-white border border-neutral-100 shadow-sm transition-colors text-neutral-500 hover:text-neutral-800 shrink-0"
            >
                {isMobileNavOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>

            <AnimatePresence>
                {isMobileNavOpen && (
                    <motion.div
                        initial={{ opacity: 0, y: -8 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -8 }}
                        transition={{ duration: 0.15 }}
                        className="lg:hidden absolute top-full left-4 right-4 mt-2 p-1.5 rounded-2xl bg-white border border-neutral-100 shadow-[0_8px_30px_rgb(0,0,0,0.08)] z-20"
                    >
                        {mainNavItems.map((item) => {
                            const isActive = pathname === item.href;
                            return (
                                <Link
                                    key={item.name}
                                    href={item.href}
                                    onClick={() => setIsMobileNavOpen(false)}
                                    className={cn(
                                        "flex items-center gap-3 px-4 py-2.5 rounded-xl text-[14px] transition-colors",
                                        isActive ? "text-[var(--accent-primary-hover)] font-medium bg-[var(--accent-primary)]/8" : "text-neutral-600 hover:bg-black/5 hover:text-neutral-900"
                                    )}
                                >
                                    <item.icon className="w-4 h-4" />
                                    {item.name}
                                </Link>
                            );
                        })}
                        <div className="h-px bg-neutral-100 my-1.5 mx-2" />
                        <Link
                            href="/settings"
                            onClick={() => setIsMobileNavOpen(false)}
                            className="flex items-center gap-3 px-4 py-2.5 rounded-xl text-[14px] text-neutral-600 hover:bg-black/5 hover:text-neutral-900 transition-colors"
                        >
                            <Settings className="w-4 h-4" />
                            Settings
                        </Link>
                        <button
                            type="button"
                            onClick={() => {
                                setIsMobileNavOpen(false);
                                logout();
                            }}
                            className="flex w-full items-center gap-3 px-4 py-2.5 rounded-xl text-[14px] text-neutral-600 hover:bg-black/5 hover:text-neutral-900 transition-colors"
                        >
                            <LogOut className="w-4 h-4" />
                            Sign Out
                        </button>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Search Widget */}
            <div className="flex-1 max-w-md hidden md:flex">
                <div className="relative w-full group">
                    <div className="absolute -inset-0.5 bg-gradient-to-r from-[var(--accent-primary)]/20 to-[var(--accent-secondary)]/20 rounded-[1.15rem] blur opacity-0 group-focus-within:opacity-100 transition duration-500" />
                    <div className="relative flex items-center w-full bg-white/70 backdrop-blur-xl border border-white rounded-[1.15rem] shadow-[0_4px_15px_-4px_rgba(0,0,0,0.05),0_0_0_1px_rgba(200,205,210,0.3)] group-focus-within:bg-white group-focus-within:shadow-[0_8px_30px_rgba(7,23,44,0.06),0_0_0_1px_rgba(7,23,44,0.1)] transition-all duration-300">
                        <div className="pl-4 pr-3 flex items-center pointer-events-none">
                            <Search className="h-4 w-4 text-neutral-400 group-focus-within:text-[var(--accent-primary)] transition-colors duration-300" />
                        </div>
                        <input
                            suppressHydrationWarning
                            type="text"
                            className="block w-full py-2.5 px-0 bg-transparent border-0 text-base sm:text-[14px] placeholder:text-neutral-400/80 focus:ring-0 outline-none text-neutral-800 placeholder:font-light"
                            placeholder="Find lessons, concepts, insights..."
                        />
                        <div className="pr-3 flex items-center gap-1 opacity-70 group-focus-within:opacity-100 transition-opacity">
                            <kbd className="hidden sm:inline-flex items-center justify-center min-w-[24px] h-6 px-1.5 bg-neutral-100/80 border border-neutral-200/60 rounded text-[11px] font-sans font-medium text-neutral-500 shadow-[0_1px_0_rgba(0,0,0,0.05)]">
                                ⌘
                            </kbd>
                            <kbd className="hidden sm:inline-flex items-center justify-center min-w-[24px] h-6 px-1.5 bg-neutral-100/80 border border-neutral-200/60 rounded text-[11px] font-sans font-medium text-neutral-500 shadow-[0_1px_0_rgba(0,0,0,0.05)]">
                                K
                            </kbd>
                        </div>
                    </div>
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

                {/* Profile Dropdown */}
                <div className="relative" ref={profileMenuRef}>
                    <button
                        suppressHydrationWarning
                        type="button"
                        onClick={() => setIsProfileMenuOpen((open) => !open)}
                        aria-haspopup="menu"
                        aria-expanded={isProfileMenuOpen}
                        className="relative group focus:outline-none flex items-center gap-3 pl-3 pr-2 py-1.5 rounded-full hover:bg-neutral-100/50 transition-colors"
                    >
                        <div className="w-9 h-9 rounded-full bg-gradient-to-tr from-[var(--accent-primary)] to-[var(--accent-primary-hover)] flex items-center justify-center text-white font-medium text-sm shadow-md overflow-hidden">
                            {/* Only initials (never the full name/email) are sent to this
                                third-party CDN as the avatar seed — review fix. */}
                            <img src={`https://ui-avatars.com/api/?name=${encodeURIComponent(getInitials(displayName))}&background=random&color=fff`} alt="Profile" className="w-full h-full object-cover" />
                        </div>
                    </button>

                    <AnimatePresence>
                        {isProfileMenuOpen && (
                            <motion.div
                                initial={{ opacity: 0, y: -8, scale: 0.97 }}
                                animate={{ opacity: 1, y: 0, scale: 1 }}
                                exit={{ opacity: 0, y: -8, scale: 0.97 }}
                                transition={{ duration: 0.15 }}
                                className="absolute top-full right-0 mt-2 w-56 p-1.5 rounded-2xl bg-white border border-neutral-100 shadow-[0_8px_30px_rgb(0,0,0,0.08)] z-20"
                            >
                                <div className="px-4 py-2.5 border-b border-neutral-100 mb-1">
                                    <p className="text-sm font-medium text-neutral-900 truncate">{displayName}</p>
                                    {user?.email && <p className="text-xs text-neutral-400 truncate">{user.email}</p>}
                                </div>
                                <Link
                                    href="/settings"
                                    onClick={() => setIsProfileMenuOpen(false)}
                                    className="flex items-center gap-3 px-4 py-2.5 rounded-xl text-[14px] text-neutral-600 hover:bg-black/5 hover:text-neutral-900 transition-colors"
                                >
                                    <Settings className="w-4 h-4" />
                                    Settings
                                </Link>
                                <button
                                    type="button"
                                    onClick={() => {
                                        setIsProfileMenuOpen(false);
                                        logout();
                                    }}
                                    className="flex w-full items-center gap-3 px-4 py-2.5 rounded-xl text-[14px] text-neutral-600 hover:bg-black/5 hover:text-neutral-900 transition-colors"
                                >
                                    <LogOut className="w-4 h-4" />
                                    Sign Out
                                </button>
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>
            </div>
        </header>
    );
}
