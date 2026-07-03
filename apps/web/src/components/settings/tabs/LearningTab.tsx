"use client";

import { useState } from "react";
import { SegmentedControl } from "../SegmentedControl";
import { Gauge, MessageSquare, Zap, Layout } from "lucide-react";

export function LearningTab() {
    // Dummy state for settings
    const [pace, setPace] = useState("balanced");
    const [explanation, setExplanation] = useState("balanced");
    const [intervention, setIntervention] = useState("minimal");
    const [style, setStyle] = useState("visual");

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
                        value={pace}
                        onChange={setPace}
                        options={[
                            { value: "relaxed", label: "Relaxed" },
                            { value: "balanced", label: "Balanced" },
                            { value: "intensive", label: "Intensive" }
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
                        value={explanation}
                        onChange={setExplanation}
                        options={[
                            { value: "simple", label: "Simple" },
                            { value: "balanced", label: "Balanced" },
                            { value: "technical", label: "Technical" }
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
                        value={intervention}
                        onChange={setIntervention}
                        options={[
                            { value: "minimal", label: "Minimal" },
                            { value: "balanced", label: "Balanced" },
                            { value: "active", label: "Active" }
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
                        value={style}
                        onChange={setStyle}
                        options={[
                            { value: "visual", label: "Visual" },
                            { value: "conceptual", label: "Conceptual" },
                            { value: "hands-on", label: "Hands-on" },
                            { value: "mixed", label: "Mixed" }
                        ]}
                    />
                </div>

            </div>
        </div>
    );
}
