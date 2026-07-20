"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { LayoutDashboard, Library, UploadCloud, PieChart, Settings, LogOut, UserCircle } from "lucide-react";
import Image from "next/image";
import { cn } from "@/lib/utils";
import { useAuth } from "@/contexts/AuthContext";

const mainNavItems = [
    { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
    { name: "My Library", href: "/library", icon: Library },
    { name: "Upload PDF", href: "/upload", icon: UploadCloud },
    { name: "Reports", href: "/reports", icon: PieChart },
];

export function Sidebar() {
    const pathname = usePathname();
    const { logout } = useAuth();
    const [isAccountMenuOpen, setIsAccountMenuOpen] = useState(false);
    const accountMenuRef = useRef<HTMLDivElement>(null);
    const isSettingsActive = pathname === "/settings";

    useEffect(() => {
        if (!isAccountMenuOpen) return;

        function handleClickOutside(event: MouseEvent) {
            if (accountMenuRef.current && !accountMenuRef.current.contains(event.target as Node)) {
                setIsAccountMenuOpen(false);
            }
        }

        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, [isAccountMenuOpen]);

    return (
        <aside className="w-68 h-[calc(100vh-2.5rem)] my-5 ml-5 flex-shrink-0 relative hidden lg:flex flex-col rounded-[36px] bg-white/70 backdrop-blur-2xl border border-[var(--accent-primary)]/10 shadow-[0_8px_30px_rgb(0,0,0,0.04)] z-50 overflow-hidden before:absolute before:inset-0 before:bg-gradient-to-b before:from-white/40 before:to-transparent before:pointer-events-none">

            {/* Logo Area */}
            <div className="pt-10 pb-8 px-8 relative z-10 flex items-center justify-between">
                <Link href="/" className="flex items-center gap-3 inline-block group">
                    <Image src="/logo.jpeg" alt="HIE Logo" width={32} height={32} className="rounded-lg transition-transform duration-300 group-hover:scale-105 object-contain" />
                    <span className="text-xl font-bold tracking-tight text-[var(--accent-primary)] transition-all duration-300">
                        HIE
                    </span>
                </Link>
            </div>

            <div className="flex flex-col flex-1 px-4 relative z-10">
                <nav className="flex-1 space-y-1">
                    {mainNavItems.map((item) => {
                        const isActive = pathname === item.href;
                        return (
                            <Link key={item.name} href={item.href} className="block relative focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)] rounded-full">
                                {isActive && (
                                    <motion.div
                                        layoutId="activeNavBackground"
                                        className="absolute inset-0 bg-[var(--accent-primary)]/8 rounded-full"
                                        initial={{ opacity: 0 }}
                                        animate={{ opacity: 1 }}
                                        exit={{ opacity: 0 }}
                                        transition={{ type: "spring", stiffness: 350, damping: 30 }}
                                    />
                                )}

                                <div className={cn(
                                    "relative flex items-center gap-4 px-5 py-3.5 rounded-full transition-all duration-300 group",
                                    isActive
                                        ? "text-[var(--accent-primary-hover)] font-medium"
                                        : "text-neutral-500 hover:text-neutral-800 hover:bg-black/5"
                                )}>
                                    <div className={cn(
                                        "flex items-center justify-center w-8 h-8 rounded-lg shrink-0 transition-colors duration-300",
                                        isActive && "bg-[var(--accent-secondary)]"
                                    )}>
                                        <item.icon className={cn(
                                            "w-5 h-5 transition-transform duration-300 group-hover:scale-110",
                                            isActive ? "text-[var(--accent-primary)]" : "text-neutral-400 group-hover:text-neutral-600"
                                        )} />
                                    </div>
                                    <span className="text-[15px]">{item.name}</span>
                                </div>
                            </Link>
                        );
                    })}
                </nav>

                <div className="py-4">
                    <div className="h-px bg-gradient-to-r from-transparent via-neutral-200/60 to-transparent mx-4" />
                </div>

                <nav className="pb-8 space-y-1">
                    <div className="relative" ref={accountMenuRef}>
                        <AnimatePresence>
                            {isAccountMenuOpen && (
                                <motion.div
                                    initial={{ opacity: 0, y: 8, scale: 0.97 }}
                                    animate={{ opacity: 1, y: 0, scale: 1 }}
                                    exit={{ opacity: 0, y: 8, scale: 0.97 }}
                                    transition={{ duration: 0.15 }}
                                    className="absolute bottom-full left-0 right-0 mb-2 p-1.5 rounded-2xl bg-white border border-neutral-100 shadow-[0_8px_30px_rgb(0,0,0,0.08)] z-20"
                                >
                                    <Link
                                        href="/settings"
                                        onClick={() => setIsAccountMenuOpen(false)}
                                        className="flex items-center gap-3 px-4 py-2.5 rounded-xl text-[14px] text-neutral-600 hover:bg-black/5 hover:text-neutral-900 transition-colors"
                                    >
                                        <Settings className="w-4 h-4" />
                                        Settings
                                    </Link>
                                    <button
                                        type="button"
                                        onClick={() => {
                                            setIsAccountMenuOpen(false);
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

                        <button
                            type="button"
                            onClick={() => setIsAccountMenuOpen((open) => !open)}
                            aria-haspopup="menu"
                            aria-expanded={isAccountMenuOpen}
                            className="block w-full relative focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)] rounded-full"
                        >
                            {(isSettingsActive || isAccountMenuOpen) && (
                                <motion.div
                                    layoutId="activeNavBackground"
                                    className="absolute inset-0 bg-[var(--accent-primary)]/8 rounded-full"
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    exit={{ opacity: 0 }}
                                    transition={{ type: "spring", stiffness: 350, damping: 30 }}
                                />
                            )}
                            <div className={cn(
                                "relative flex items-center gap-4 px-5 py-3.5 rounded-full transition-all duration-300 group",
                                isSettingsActive || isAccountMenuOpen
                                    ? "text-[var(--accent-primary-hover)] font-medium"
                                    : "text-neutral-500 hover:text-neutral-800 hover:bg-black/5"
                            )}>
                                <div className={cn(
                                    "flex items-center justify-center w-8 h-8 rounded-lg shrink-0 transition-colors duration-300",
                                    (isSettingsActive || isAccountMenuOpen) && "bg-[var(--accent-secondary)]"
                                )}>
                                    <UserCircle className={cn(
                                        "w-5 h-5 transition-transform duration-300 group-hover:rotate-12",
                                        isSettingsActive || isAccountMenuOpen ? "text-[var(--accent-primary)]" : "text-neutral-400 group-hover:text-neutral-600"
                                    )} />
                                </div>
                                <span className="text-[15px]">Account</span>
                            </div>
                        </button>
                    </div>
                </nav>
            </div>
        </aside>
    );
}
