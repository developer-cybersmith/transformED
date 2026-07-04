"use client";

import { useEffect, useState } from "react";
import { Toggle } from "../Toggle";
import { ShieldAlert } from "lucide-react";
import { settingsService } from "@/services/settings.service";
import type { PrivacySettings } from "@/mocks/data/users";

export function PrivacyTab() {
    const [settings, setSettings] = useState<PrivacySettings | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;
        settingsService.getPrivacy().then((response) => {
            if (cancelled) return;
            setSettings(response.data);
            setIsLoading(false);
        });
        return () => {
            cancelled = true;
        };
    }, []);

    function updateSetting<K extends keyof PrivacySettings>(key: K, value: PrivacySettings[K]) {
        setSettings((prev) => (prev ? { ...prev, [key]: value } : prev));
        settingsService.updatePrivacy({ [key]: value } as Partial<PrivacySettings>);
    }

    if (isLoading || !settings) {
        return (
            <div className="flex w-full max-w-3xl items-center justify-center pt-24 pb-24 text-sm text-neutral-400">
                Loading privacy settings…
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-10 w-full max-w-3xl pt-8 pb-12">
            <div>
                <h2 className="font-serif text-2xl font-semibold text-neutral-900 tracking-tight mb-2">Privacy & Trust</h2>
                <p className="text-neutral-500">Your data belongs to you. Control how it is used to improve your experience.</p>
            </div>

            <div className="flex flex-col gap-8">

                {/* Highlighted Trust Setting */}
                <div className="flex flex-col gap-4 p-5 rounded-2xl bg-gradient-to-br from-neutral-50 to-neutral-100/50 border border-neutral-200/60 shadow-sm relative overflow-hidden">
                    <div className="absolute top-0 right-0 p-4 opacity-5 pointer-events-none">
                        <ShieldAlert className="w-32 h-32" />
                    </div>

                    <div className="flex items-start justify-between relative z-10">
                        <div className="flex flex-col gap-2 max-w-[85%]">
                            <span className="text-lg font-semibold text-neutral-900">Camera-Based Focus Detection</span>
                            <span className="text-sm text-neutral-600 leading-relaxed">
                                Allows the intelligent tutor to adapt pacing based on your attention. <br />
                                <strong className="text-neutral-900 font-medium bg-neutral-200/50 px-1 py-0.5 rounded">Used only during active lessons and never permanently stored.</strong>
                            </span>
                        </div>
                        {/* This toggle is a UI display preference only. It is NOT the DPDP Act 2023
                            attention-tracking consent record (see CLAUDE.md §18 and
                            supabase/migrations/20260702000000_dpdp_user_consents.sql) — that consent
                            flow is a separate, not-yet-wired backend integration (S3-01 Attention
                            Consent Modal). Do not treat this toggle as satisfying that requirement. */}
                        <Toggle enabled={settings.focusDetection} onChange={(v) => updateSetting("focusDetection", v)} />
                    </div>
                </div>

                {/* Standard Settings */}
                <div className="flex flex-col border border-neutral-100 rounded-2xl bg-white shadow-sm">
                    <div className="flex items-center justify-between p-5 border-b border-neutral-100">
                        <div className="flex flex-col gap-1">
                            <span className="font-medium text-neutral-900">Learning Analytics</span>
                            <span className="text-sm text-neutral-500">Allow analysis of your performance to build a better curriculum.</span>
                        </div>
                        <Toggle enabled={settings.learningAnalytics} onChange={(v) => updateSetting("learningAnalytics", v)} />
                    </div>

                    <div className="flex items-center justify-between p-5">
                        <div className="flex flex-col gap-1">
                            <span className="font-medium text-neutral-900">Personalized Recommendations</span>
                            <span className="text-sm text-neutral-500">Use your activity data to suggest new modules and challenges.</span>
                        </div>
                        <Toggle enabled={settings.personalizedRecommendations} onChange={(v) => updateSetting("personalizedRecommendations", v)} />
                    </div>
                </div>

            </div>
        </div>
    );
}
