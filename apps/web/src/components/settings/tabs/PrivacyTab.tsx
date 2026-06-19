"use client";

import { useState } from "react";
import { Toggle } from "../Toggle";
import { ShieldAlert } from "lucide-react";

export function PrivacyTab() {
    const [focusDetection, setFocusDetection] = useState(true);
    const [learningAnalytics, setLearningAnalytics] = useState(true);
    const [personalizedRecommendations, setPersonalizedRecommendations] = useState(true);

    return (
        <div className="flex flex-col gap-10 w-full max-w-3xl pt-8 pb-12">
            <div>
                <h2 className="text-2xl font-semibold text-neutral-900 tracking-tight mb-2">Privacy & Trust</h2>
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
                        <Toggle enabled={focusDetection} onChange={setFocusDetection} />
                    </div>
                </div>

                {/* Standard Settings */}
                <div className="flex flex-col border border-neutral-100 rounded-2xl bg-white shadow-sm">
                    <div className="flex items-center justify-between p-5 border-b border-neutral-100">
                        <div className="flex flex-col gap-1">
                            <span className="font-medium text-neutral-900">Learning Analytics</span>
                            <span className="text-sm text-neutral-500">Allow analysis of your performance to build a better curriculum.</span>
                        </div>
                        <Toggle enabled={learningAnalytics} onChange={setLearningAnalytics} />
                    </div>

                    <div className="flex items-center justify-between p-5">
                        <div className="flex flex-col gap-1">
                            <span className="font-medium text-neutral-900">Personalized Recommendations</span>
                            <span className="text-sm text-neutral-500">Use your activity data to suggest new modules and challenges.</span>
                        </div>
                        <Toggle enabled={personalizedRecommendations} onChange={setPersonalizedRecommendations} />
                    </div>
                </div>

            </div>
        </div>
    );
}
