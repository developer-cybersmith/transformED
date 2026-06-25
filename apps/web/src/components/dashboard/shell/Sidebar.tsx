"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "framer-motion";
import { LayoutDashboard, Library, UploadCloud, PieChart, Settings, UserCircle } from "lucide-react";
import Image from "next/image";
import { cn } from "@/lib/utils";

const mainNavItems = [
    { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
    { name: "My Library", href: "/library", icon: Library },
    { name: "Upload PDF", href: "/upload", icon: UploadCloud },
    { name: "Reports", href: "/reports", icon: PieChart },
];

const bottomNavItems = [
    { name: "Settings", href: "/settings", icon: Settings },
];

export function Sidebar() {
    const pathname = usePathname();

    return (
        <aside className="w-68 h-[calc(100vh-2.5rem)] my-5 ml-5 flex-shrink-0 relative hidden lg:flex flex-col rounded-[36px] bg-white/70 backdrop-blur-2xl border border-[var(--accent-primary)]/10 shadow-[0_8px_30px_rgb(0,0,0,0.04)] z-50 overflow-hidden before:absolute before:inset-0 before:bg-gradient-to-b before:from-white/40 before:to-transparent before:pointer-events-none">

            {/* Logo Area */}
            <div className="pt-10 pb-8 px-8 relative z-10 flex items-center justify-between">
                <Link href="/" className="flex items-center gap-3 inline-block group">
                    <Image src="/logo.jpeg" alt="HIE Logo" width={32} height={32} className="rounded-lg transition-transform duration-300 group-hover:scale-105 object-contain" />
                    <span className="text-xl font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-[var(--accent-primary)] to-[var(--accent-secondary)] transition-all duration-300">
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
                                        className="absolute inset-0 bg-gradient-to-r from-[var(--accent-primary)]/10 to-[var(--accent-secondary)]/5 rounded-full"
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
                                    <item.icon className={cn(
                                        "w-5 h-5 transition-transform duration-300 group-hover:scale-110",
                                        isActive ? "text-[var(--accent-primary)]" : "text-neutral-400 group-hover:text-neutral-600"
                                    )} />
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
                    {bottomNavItems.map((item) => {
                        const isActive = pathname === item.href;
                        return (
                            <Link key={item.name} href={item.href} className="block relative focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-primary)] rounded-full">
                                {isActive && (
                                    <motion.div
                                        layoutId="activeNavBackground"
                                        className="absolute inset-0 bg-gradient-to-r from-[var(--accent-primary)]/10 to-[var(--accent-secondary)]/5 rounded-full"
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
                                    <item.icon className={cn(
                                        "w-5 h-5 transition-transform duration-300 group-hover:rotate-12",
                                        isActive ? "text-[var(--accent-primary)]" : "text-neutral-400 group-hover:text-neutral-600"
                                    )} />
                                    <span className="text-[15px]">{item.name}</span>
                                </div>
                            </Link>
                        );
                    })}
                </nav>
            </div>
        </aside>
    );
}
