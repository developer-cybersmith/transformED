"use client";

import { useState } from "react";
import { Toggle } from "../Toggle";

export function NotificationsTab() {
    const [lessonReady, setLessonReady] = useState(true);
    const [weeklyProgress, setWeeklyProgress] = useState(true);
    const [streakReminders, setStreakReminders] = useState(false);
    const [productUpdates, setProductUpdates] = useState(false);

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
                    <Toggle enabled={lessonReady} onChange={setLessonReady} />
                </div>

                <div className="flex items-center justify-between p-5 border-b border-neutral-100">
                    <div className="flex flex-col gap-1">
                        <span className="font-medium text-neutral-900">Weekly Progress</span>
                        <span className="text-sm text-neutral-500">Receive a weekly summary of your learning journey.</span>
                    </div>
                    <Toggle enabled={weeklyProgress} onChange={setWeeklyProgress} />
                </div>

                <div className="flex items-center justify-between p-5 border-b border-neutral-100">
                    <div className="flex flex-col gap-1">
                        <span className="font-medium text-neutral-900">Streak Reminders</span>
                        <span className="text-sm text-neutral-500">Helpful nudges to keep your daily streak alive.</span>
                    </div>
                    <Toggle enabled={streakReminders} onChange={setStreakReminders} />
                </div>

                <div className="flex items-center justify-between p-5">
                    <div className="flex flex-col gap-1">
                        <span className="font-medium text-neutral-900">Product Updates</span>
                        <span className="text-sm text-neutral-500">News about active features and platform improvements.</span>
                    </div>
                    <Toggle enabled={productUpdates} onChange={setProductUpdates} />
                </div>

            </div>
        </div>
    );
}
