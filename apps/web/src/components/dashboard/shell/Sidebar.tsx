"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { LayoutDashboard, BookOpen, UploadCloud, PieChart, Settings, LogOut, UserCircle, ChevronLeft, ChevronRight } from "lucide-react";
import Image from "next/image";
import { cn } from "@/lib/utils";
import { useAuth } from "@/contexts/AuthContext";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

export const mainNavItems = [
    { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
    { name: "My Books", href: "/books", icon: BookOpen },
    { name: "Upload PDF", href: "/upload", icon: UploadCloud },
    { name: "Reports", href: "/reports", icon: PieChart },
];

// The sidebar is duplicated per top-level route (there is no shared
// (dashboard)/layout.tsx -- see books/layout.tsx's own comment on this), so
// each navigation between Dashboard/Books/Upload/Reports/Settings mounts a
// FRESH <Sidebar />. Plain useState would silently re-expand on every such
// navigation; persisting to localStorage is what makes the collapsed choice
// actually stick, matching useAttentionConsent.ts's guarded read/write
// pattern (storage can be unavailable -- fail to the safe/visible default).
const SIDEBAR_COLLAPSED_KEY = "hie:sidebar-collapsed";

function readCollapsed(): boolean {
    try {
        return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
    } catch {
        return false;
    }
}

function writeCollapsed(collapsed: boolean): void {
    try {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
        // Storage inaccessible -- the preference just won't persist across
        // navigations/reloads this session, which is the safe direction to
        // fail in (defaults back to fully visible, not stuck hidden).
    }
}

export function Sidebar() {
    const pathname = usePathname();
    const { logout } = useAuth();
    const [isAccountMenuOpen, setIsAccountMenuOpen] = useState(false);
    const accountMenuRef = useRef<HTMLDivElement>(null);
    const isSettingsActive = pathname === "/settings";
    // Starts false (expanded) on every render, including the server-rendered
    // one, and only flips after mount -- reading localStorage during render
    // would desync from the server HTML and trigger a hydration warning.
    const [isCollapsed, setIsCollapsed] = useState(false);

    useEffect(() => {
        // Deliberately synchronous, same as useAttentionConsent.ts's own
        // mount-time read: this is the ONE-TIME sync from localStorage to
        // React state that must happen before the collapsed UI can be
        // correct, not a subscription to an ongoing external change stream.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setIsCollapsed(readCollapsed());
    }, []);

    const toggleCollapsed = () => {
        setIsCollapsed((prev) => {
            const next = !prev;
            writeCollapsed(next);
            return next;
        });
    };

    useEffect(() => {
        if (!isAccountMenuOpen) return;

        function handleClickOutside(event: MouseEvent) {
            if (accountMenuRef.current && !accountMenuRef.current.contains(event.target as Node)) {
                setIsAccountMenuOpen(false);
            }
        }
        // Review fix: menus exposed aria-haspopup/aria-expanded but had no
        // keyboard way to dismiss them.
        function handleEscape(event: KeyboardEvent) {
            if (event.key === "Escape") setIsAccountMenuOpen(false);
        }

        document.addEventListener("mousedown", handleClickOutside);
        document.addEventListener("keydown", handleEscape);
        return () => {
            document.removeEventListener("mousedown", handleClickOutside);
            document.removeEventListener("keydown", handleEscape);
        };
    }, [isAccountMenuOpen]);

    return (
        <TooltipProvider delayDuration={200}>
        <aside className={cn(
            "h-[calc(100vh-2.5rem)] my-5 ml-5 flex-shrink-0 relative hidden lg:flex flex-col rounded-[36px] bg-white/70 backdrop-blur-2xl border border-[var(--accent-primary)]/10 shadow-[0_8px_30px_rgb(0,0,0,0.04)] z-50 overflow-hidden before:absolute before:inset-0 before:bg-gradient-to-b before:from-white/40 before:to-transparent before:pointer-events-none transition-[width] duration-300 ease-in-out",
            isCollapsed ? "w-20" : "w-68"
        )}>

            {/* Logo Area */}
            <div className="pt-10 pb-8 px-5 relative z-10 flex items-center justify-between">
                <Link href="/" className="flex items-center gap-3 inline-block group min-w-0">
                    <Image src="/logo.jpeg" alt="HIE Logo" width={32} height={32} className="rounded-lg shrink-0 transition-transform duration-300 group-hover:scale-105 object-contain" />
                    {!isCollapsed && (
                        <span className="text-xl font-bold tracking-tight text-[var(--accent-primary)] transition-all duration-300 whitespace-nowrap">
                            HIE
                        </span>
                    )}
                </Link>

                <button
                    type="button"
                    onClick={toggleCollapsed}
                    aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
                    aria-pressed={isCollapsed}
                    className={cn(
                        "flex items-center justify-center w-7 h-7 rounded-full text-neutral-400 hover:text-neutral-700 hover:bg-black/5 transition-colors shrink-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)]",
                        isCollapsed && "absolute -right-3 top-11 bg-white border border-[var(--accent-primary)]/10 shadow-[0_2px_10px_rgb(0,0,0,0.08)] hover:bg-neutral-50"
                    )}
                >
                    {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
                </button>
            </div>

            <div className={cn("flex flex-col flex-1 relative z-10", isCollapsed ? "px-3" : "px-4")}>
                <nav className="flex-1 space-y-1">
                    {mainNavItems.map((item) => {
                        const isActive = pathname === item.href;
                        const linkContent = (
                            <Link
                                key={item.name}
                                href={item.href}
                                aria-label={isCollapsed ? item.name : undefined}
                                className="block relative focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)] rounded-full"
                            >
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
                                    "relative flex items-center gap-4 py-3.5 rounded-full transition-all duration-300 group",
                                    isCollapsed ? "justify-center px-0" : "px-5",
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
                                    {!isCollapsed && <span className="text-[15px] whitespace-nowrap">{item.name}</span>}
                                </div>
                            </Link>
                        );

                        if (!isCollapsed) return linkContent;

                        return (
                            <Tooltip key={item.name}>
                                <TooltipTrigger asChild>{linkContent}</TooltipTrigger>
                                <TooltipContent side="right" sideOffset={12}>{item.name}</TooltipContent>
                            </Tooltip>
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
                                    className={cn(
                                        "absolute bottom-full mb-2 p-1.5 rounded-2xl bg-white border border-neutral-100 shadow-[0_8px_30px_rgb(0,0,0,0.08)] z-20",
                                        isCollapsed ? "left-0 w-56" : "left-0 right-0"
                                    )}
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

                        {(() => {
                            const accountButton = (
                                <button
                                    type="button"
                                    onClick={() => setIsAccountMenuOpen((open) => !open)}
                                    aria-haspopup="menu"
                                    aria-expanded={isAccountMenuOpen}
                                    aria-label={isCollapsed ? "Account" : undefined}
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
                                        "relative flex items-center gap-4 py-3.5 rounded-full transition-all duration-300 group",
                                        isCollapsed ? "justify-center px-0" : "px-5",
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
                                        {!isCollapsed && <span className="text-[15px] whitespace-nowrap">Account</span>}
                                    </div>
                                </button>
                            );

                            if (!isCollapsed) return accountButton;

                            return (
                                <Tooltip>
                                    <TooltipTrigger asChild>{accountButton}</TooltipTrigger>
                                    <TooltipContent side="right" sideOffset={12}>Account</TooltipContent>
                                </Tooltip>
                            );
                        })()}
                    </div>
                </nav>
            </div>
        </aside>
        </TooltipProvider>
    );
}
