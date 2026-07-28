"use client";

import React, { useMemo } from 'react';
import type { JargonEntry } from '@hie/shared/types/lesson';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@/components/ui/tooltip";

interface JargonHoverProps {
    text: string;
    /** Jargon entries from the frozen LessonPackage contract. Empty array = no highlights. */
    jargon: JargonEntry[];
}

// [DEV1-SPRINT2-PENDING] This depends on the real LessonPackage from Dev 1's
// package_builder (Story S2-11, not yet built). Do not build a parallel
// real-content path here -- this will be reconciled when Sprint 2 lands.
// Ping Dev 1 (developer1-cybersmith) before changing this shape.
export function JargonHover({ text, jargon }: JargonHoverProps) {
    // Convert JargonEntry[] → Record<string, string> once per jargon array reference
    const dictionary = useMemo<Record<string, string>>(
        () => Object.fromEntries(jargon.map(({ term, definition }) => [term, definition])),
        [jargon],
    );

    const parsedNodes = useMemo(() => {
        if (!text) return [];

        const jargonKeys = Object.keys(dictionary).sort((a, b) => b.length - a.length);
        if (jargonKeys.length === 0) return [text];

        const escapedKeys = jargonKeys.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
        const regex = new RegExp(`\\b(${escapedKeys.join('|')})\\b`, 'gi');

        const nodes: React.ReactNode[] = [];
        let lastIndex = 0;
        let match;

        while ((match = regex.exec(text)) !== null) {
            if (match.index > lastIndex) {
                nodes.push(text.slice(lastIndex, match.index));
            }

            const matchedText = match[0];
            const dictKey = jargonKeys.find(k => k.toLowerCase() === matchedText.toLowerCase());

            if (dictKey) {
                nodes.push(
                    <TooltipProvider key={`${match.index}-${matchedText}`} delayDuration={150}>
                        <Tooltip delayDuration={150}>
                            <TooltipTrigger asChild>
                                {/*
                                  * No hover:-translate-y here — translate on hover shifts surrounding
                                  * inline text by 1px. All other classes are constant so line height
                                  * stays stable across all bullet renders.
                                  */}
                                <span className="cursor-help inline-block font-semibold text-[var(--accent-secondary)] bg-[var(--accent-secondary)]/8 border-b-[2px] border-dotted border-[var(--accent-secondary)]/60 hover:bg-[var(--accent-secondary)]/18 hover:border-solid hover:shadow-sm transition-all rounded-md px-1.5 py-0.5 mx-0.5 relative z-10">
                                    {matchedText}
                                </span>
                            </TooltipTrigger>
                            {/*
                              * TooltipContent portals to document.body via Radix's default Portal
                              * behaviour — never clipped by overflow-y-auto on SlideRenderer.
                              */}
                            <TooltipContent side="top" align="center" sideOffset={10} className="w-[300px] border border-[var(--accent-secondary)]/25 shadow-[0_10px_40px_-10px_rgba(0,0,0,0.6)]">
                                <div className="p-2">
                                    <p className="font-serif font-semibold text-white mb-2 inline-flex items-center gap-2.5">
                                        <span className="w-2 h-2 rounded-full bg-[var(--accent-secondary)] shrink-0 shadow-[0_0_10px_var(--accent-secondary)]" />
                                        {dictKey}
                                    </p>
                                    <p className="text-neutral-300 text-[13px] leading-relaxed font-normal">{dictionary[dictKey]}</p>
                                </div>
                            </TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                );
            } else {
                nodes.push(matchedText);
            }

            lastIndex = regex.lastIndex;
        }

        if (lastIndex < text.length) {
            nodes.push(text.slice(lastIndex));
        }

        return nodes;
    }, [text, dictionary]);

    return <>{parsedNodes}</>;
}
