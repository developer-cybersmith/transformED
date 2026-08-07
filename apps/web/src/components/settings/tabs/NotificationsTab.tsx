"use client";

import { Toggle } from "../Toggle";
import { useNotificationPreferences, type NotificationPreferences } from "@/hooks/useNotificationPreferences";

const TOGGLES: Array<{
    key: keyof NotificationPreferences;
    label: string;
    description: string;
}> = [
    {
        key: "session_report_email",
        label: "Session Report",
        description: "Get an email summary after each lesson session.",
    },
    {
        key: "lesson_ready_email",
        label: "Lesson Ready",
        description: "Get notified when your personalized lesson is ready.",
    },
    {
        key: "weekly_progress_email",
        label: "Weekly Progress",
        description: "Receive a weekly summary of your learning journey.",
    },
    {
        key: "streak_reminders",
        label: "Streak Reminders",
        description: "Helpful nudges to keep your daily streak alive.",
    },
];

export function NotificationsTab() {
    const { preferences, isLoading, updatePreference } = useNotificationPreferences();

    if (isLoading) {
        return (
            <div className="flex w-full max-w-3xl items-center justify-center pt-24 pb-24 text-sm text-neutral-400">
                Loading notification settings…
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-8 w-full max-w-3xl pt-8 pb-12">
            <div>
                <h2 className="font-serif text-2xl font-semibold text-neutral-900 tracking-tight mb-2">Notifications</h2>
                <p className="text-neutral-500">Manage how and when HIE communicates with you.</p>
            </div>

            <div className="flex flex-col rounded-2xl border border-neutral-100 bg-white overflow-hidden shadow-sm">
                {TOGGLES.map(({ key, label, description }, index) => (
                    <div
                        key={key}
                        className={`flex items-center justify-between p-5 ${
                            index < TOGGLES.length - 1 ? "border-b border-neutral-100" : ""
                        }`}
                    >
                        <div className="flex flex-col gap-1">
                            <span className="font-medium text-neutral-900">{label}</span>
                            <span className="text-sm text-neutral-500">{description}</span>
                        </div>
                        <Toggle
                            enabled={preferences[key]}
                            onChange={(value) => {
                                void updatePreference(key, value);
                            }}
                        />
                    </div>
                ))}
            </div>
        </div>
    );
}
