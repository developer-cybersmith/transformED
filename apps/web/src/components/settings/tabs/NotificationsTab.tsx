"use client";

import { useEffect, useState } from "react";
import { Toggle } from "../Toggle";
import { settingsService } from "@/services/settings.service";
import type { NotificationSettings } from "@/mocks/data/users";

export function NotificationsTab() {
    const [settings, setSettings] = useState<NotificationSettings | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;
        settingsService.getNotifications().then((response) => {
            if (cancelled) return;
            setSettings(response.data);
            setIsLoading(false);
        });
        return () => {
            cancelled = true;
        };
    }, []);

    function updateSetting<K extends keyof NotificationSettings>(key: K, value: NotificationSettings[K]) {
        setSettings((prev) => (prev ? { ...prev, [key]: value } : prev));
        settingsService.updateNotifications({ [key]: value } as Partial<NotificationSettings>);
    }

    if (isLoading || !settings) {
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

                <div className="flex items-center justify-between p-5 border-b border-neutral-100">
                    <div className="flex flex-col gap-1">
                        <span className="font-medium text-neutral-900">Lesson Ready</span>
                        <span className="text-sm text-neutral-500">Get notified when your personalized lesson is ready.</span>
                    </div>
                    <Toggle enabled={settings.lessonReady} onChange={(v) => updateSetting("lessonReady", v)} />
                </div>

                <div className="flex items-center justify-between p-5 border-b border-neutral-100">
                    <div className="flex flex-col gap-1">
                        <span className="font-medium text-neutral-900">Weekly Progress</span>
                        <span className="text-sm text-neutral-500">Receive a weekly summary of your learning journey.</span>
                    </div>
                    <Toggle enabled={settings.weeklyProgress} onChange={(v) => updateSetting("weeklyProgress", v)} />
                </div>

                <div className="flex items-center justify-between p-5">
                    <div className="flex flex-col gap-1">
                        <span className="font-medium text-neutral-900">Streak Reminders</span>
                        <span className="text-sm text-neutral-500">Helpful nudges to keep your daily streak alive.</span>
                    </div>
                    <Toggle enabled={settings.streakReminders} onChange={(v) => updateSetting("streakReminders", v)} />
                </div>

            </div>
        </div>
    );
}
