"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ProfileTab } from "./tabs/ProfileTab";
import { LearningTab } from "./tabs/LearningTab";
import { NotificationsTab } from "./tabs/NotificationsTab";
import { PrivacyTab } from "./tabs/PrivacyTab";
import { AccountTab } from "./tabs/AccountTab";
import { User, BrainCircuit, Bell, Shield, Wallet } from "lucide-react";
import clsx from "clsx";

const tabs = [
    { id: "profile", label: "Profile", icon: User },
    { id: "learning", label: "Learning", icon: BrainCircuit },
    { id: "notifications", label: "Notifications", icon: Bell },
    { id: "privacy", label: "Privacy", icon: Shield },
    { id: "account", label: "Account", icon: Wallet },
];

export function SettingsTabs() {
    const [activeTab, setActiveTab] = useState(tabs[0].id);

    // Force Lenis to recalculate height after tab changes and animations
    useEffect(() => {
        const timer = setTimeout(() => {
            window.dispatchEvent(new Event("resize"));
        }, 300); // Wait for AnimatePresence transition to finish

        return () => clearTimeout(timer);
    }, [activeTab]);

    return (
        <div className="flex flex-col gap-8 w-full">
            {/* Tab Navigation */}
            <div className="flex items-center gap-2 overflow-x-auto pb-2 scrollbar-hide no-scrollbar relative w-full border-b border-neutral-200">
                {tabs.map((tab) => {
                    const isActive = activeTab === tab.id;
                    const Icon = tab.icon;
                    return (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={clsx(
                                "relative flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors outline-none",
                                isActive ? "text-[var(--accent-primary)]" : "text-neutral-500 hover:text-neutral-900"
                            )}
                            style={{ WebkitTapHighlightColor: "transparent" }}
                            suppressHydrationWarning
                        >
                            <Icon className="w-4 h-4" />
                            {tab.label}
                            {isActive && (
                                <motion.div
                                    layoutId="active-tab-indicator"
                                    className="absolute left-0 right-0 bottom-0 h-0.5 bg-[var(--accent-primary)] rounded-t-full shadow-[0_0_8px_rgba(7,23,44,0.4)]"
                                    transition={{ type: "spring", bounce: 0.2, duration: 0.6 }}
                                />
                            )}
                        </button>
                    );
                })}
            </div>

            {/* Tab Content */}
            <div className="w-full relative min-h-[400px]">
                <AnimatePresence mode="wait">
                    <motion.div
                        key={activeTab}
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -10 }}
                        transition={{ duration: 0.2 }}
                        className="w-full"
                    >
                        {activeTab === "profile" && <ProfileTab />}
                        {activeTab === "learning" && <LearningTab />}
                        {activeTab === "notifications" && <NotificationsTab />}
                        {activeTab === "privacy" && <PrivacyTab />}
                        {activeTab === "account" && <AccountTab />}
                    </motion.div>
                </AnimatePresence>
            </div>
        </div>
    );
}
