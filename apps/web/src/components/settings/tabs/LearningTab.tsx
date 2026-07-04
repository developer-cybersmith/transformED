"use client";

import { useEffect, useState } from "react";
import { SegmentedControl } from "../SegmentedControl";
import { Gauge, MessageSquare, Zap, Layout } from "lucide-react";
import { settingsService } from "@/services/settings.service";
import type { LearningPreferences } from "@/mocks/data/users";

export function LearningTab() {
    const [preferences, setPreferences] = useState<LearningPreferences | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;
        settingsService.getPreferences().then((response) => {
            if (cancelled) return;
            setPreferences(response.data);
            setIsLoading(false);
        });
        return () => {
            cancelled = true;
        };
    }, []);

    function updatePreference<K extends keyof LearningPreferences>(key: K, value: LearningPreferences[K]) {
        const previous = preferences;
        setPreferences((prev) => (prev ? { ...prev, [key]: value } : prev));
        settingsService.updatePreferences({ [key]: value } as Partial<LearningPreferences>).catch(() => {
            setPreferences(previous);
        });
    }

    if (isLoading || !preferences) {
        return (
            <div className="flex w-full max-w-3xl items-center justify-center pt-24 pb-24 text-sm text-neutral-400">
                Loading preferences…
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-10 w-full max-w-3xl pt-8 pb-12">
            <div>
                <h2 className="font-serif text-2xl font-semibold text-neutral-900 tracking-tight mb-2">Learning Preferences</h2>
                <p className="text-neutral-500">Fine-tune how the intelligent tutor interacts with you.</p>
            </div>

            <div className="flex flex-col gap-8">
                {/* Setting Item */}
                <div className="flex flex-col gap-4 border-b border-neutral-100 pb-8">
                    <div className="flex flex-col gap-1.5">
                        <h3 className="text-base font-medium flex items-center gap-2 text-neutral-900">
                            <Gauge className="w-4 h-4 text-[var(--accent-primary)]" /> Learning Pace
                        </h3>
                        <p className="text-sm text-neutral-500">How quickly new concepts are introduced.</p>
                    </div>
                    <SegmentedControl
                        value={preferences.pace}
                        onChange={(v) => updatePreference("pace", v as LearningPreferences["pace"])}
                        options={[
                            { value: "relaxed", label: "Relaxed" },
                            { value: "moderate", label: "Moderate" },
                            { value: "accelerated", label: "Accelerated" }
                        ]}
                    />
                </div>

                {/* Setting Item */}
                <div className="flex flex-col gap-4 border-b border-neutral-100 pb-8">
                    <div className="flex flex-col gap-1.5">
                        <h3 className="text-base font-medium flex items-center gap-2 text-neutral-900">
                            <MessageSquare className="w-4 h-4 text-[var(--accent-primary)]" /> Explanation Style
                        </h3>
                        <p className="text-sm text-neutral-500">Depth and terminology used in explanations.</p>
                    </div>
                    <SegmentedControl
                        value={preferences.explanationStyle}
                        onChange={(v) => updatePreference("explanationStyle", v as LearningPreferences["explanationStyle"])}
                        options={[
                            { value: "concise", label: "Concise" },
                            { value: "detailed", label: "Detailed" },
                            { value: "socratic", label: "Socratic" }
                        ]}
                    />
                </div>

                {/* Setting Item */}
                <div className="flex flex-col gap-4 border-b border-neutral-100 pb-8">
                    <div className="flex flex-col gap-1.5">
                        <h3 className="text-base font-medium flex items-center gap-2 text-neutral-900">
                            <Zap className="w-4 h-4 text-[var(--accent-primary)]" /> Tutor Intervention Frequency
                        </h3>
                        <p className="text-sm text-neutral-500">How often the tutor steps in to guide you actively.</p>
                    </div>
                    <SegmentedControl
                        value={preferences.interventionFrequency}
                        onChange={(v) => updatePreference("interventionFrequency", v as LearningPreferences["interventionFrequency"])}
                        options={[
                            { value: "low", label: "Low" },
                            { value: "medium", label: "Medium" },
                            { value: "high", label: "High" }
                        ]}
                    />
                </div>

                {/* Setting Item */}
                <div className="flex flex-col gap-4 pb-4">
                    <div className="flex flex-col gap-1.5">
                        <h3 className="text-base font-medium flex items-center gap-2 text-neutral-900">
                            <Layout className="w-4 h-4 text-[var(--accent-primary)]" /> Preferred Learning Style
                        </h3>
                        <p className="text-sm text-neutral-500">The primary format for presenting new concepts.</p>
                    </div>
                    <SegmentedControl
                        value={preferences.learningStyle}
                        onChange={(v) => updatePreference("learningStyle", v as LearningPreferences["learningStyle"])}
                        options={[
                            { value: "visual", label: "Visual" },
                            { value: "auditory", label: "Auditory" },
                            { value: "kinesthetic", label: "Kinesthetic" },
                            { value: "reading", label: "Reading" }
                        ]}
                    />
                </div>

            </div>
        </div>
    );
}
