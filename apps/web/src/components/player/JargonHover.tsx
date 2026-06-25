"use client";

import React, { useMemo } from 'react';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@/components/ui/tooltip";

const MOCK_JARGON_DICTIONARY: Record<string, string> = {
    "SQL injection": "A code injection technique used to attack data-driven applications by inserting malicious SQL statements.",
    "code injection": "The exploitation of a computer bug that is caused by processing invalid data, injecting code that is then executed by the application.",
    "unsanitized inputs": "User-supplied data that has not been properly filtered or validated before being processed, posing a major security risk.",
    "APIs": "Application Programming Interfaces; a set of rules that lets different software applications communicate with each other.",
    "database": "An organized collection of structured information, or data, typically stored electronically in a computer system.",
    "Authentication": "The process or action of verifying the identity of a user or process.",
    "Authorization": "The function of specifying access rights and privileges to resources.",
    "Zero Trust": "A security framework requiring all users to be authorized and continuously validated before being granted access.",
    "Buffer Overflows": "A vulnerability where a program writes more data to a buffer than it can hold, overwriting adjacent memory."
};

interface JargonHoverProps {
    text: string;
    /** 
     * Plug and play dictionary. Backend can inject session-specific jargon defs here. 
     * Fallbacks to mock definitions for Sprint 1.
     */
    dictionary?: Record<string, string>;
}

export function JargonHover({ text, dictionary = MOCK_JARGON_DICTIONARY }: JargonHoverProps) {
    // Parse the text to find occurrences of jargon terms dynamically
    const parsedNodes = useMemo(() => {
        if (!text) return [];

        // Build an array of keys sorted by length (longest first) to prevent partial word matching
        const jargonKeys = Object.keys(dictionary).sort((a, b) => b.length - a.length);

        if (jargonKeys.length === 0) return [text];

        // Create a regex to match any of the jargon keys (case-insensitive, whole words only)
        // Escape special regex chars just in case
        const escapedKeys = jargonKeys.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
        const regex = new RegExp(`\\b(${escapedKeys.join('|')})\\b`, 'gi');

        const nodes: React.ReactNode[] = [];
        let lastIndex = 0;
        let match;

        while ((match = regex.exec(text)) !== null) {
            // Push raw text before the match
            if (match.index > lastIndex) {
                nodes.push(text.slice(lastIndex, match.index));
            }

            const matchedText = match[0];
            // Find the original casing for the dictionary key
            const dictKey = jargonKeys.find(k => k.toLowerCase() === matchedText.toLowerCase());

            if (dictKey) {
                nodes.push(
                    <TooltipProvider key={`${match.index}-${matchedText}`} delayDuration={150}>
                        <Tooltip delayDuration={150}>
                            <TooltipTrigger asChild>
                                <span className="cursor-help inline-block font-semibold text-[var(--accent-primary)] bg-[var(--accent-primary)]/5 border-b-[2px] border-dotted border-[var(--accent-primary)]/60 hover:bg-[var(--accent-primary)]/15 hover:border-solid hover:shadow-sm hover:-translate-y-[1px] transition-all rounded-md px-1.5 py-0.5 mx-0.5 relative z-10">
                                    {matchedText}
                                </span>
                            </TooltipTrigger>
                            <TooltipContent side="top" align="center" sideOffset={10} className="w-[300px] border border-[var(--accent-primary)]/20 shadow-[0_10px_40px_-10px_rgba(0,0,0,0.6)]">
                                <div className="p-2">
                                    <p className="font-semibold text-white mb-2 inline-flex items-center gap-2.5">
                                        <span className="w-2 h-2 rounded-full bg-[var(--accent-primary)] shrink-0 shadow-[0_0_10px_var(--accent-primary)]" />
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

        // Push any remaining text after the last match
        if (lastIndex < text.length) {
            nodes.push(text.slice(lastIndex));
        }

        return nodes;
    }, [text, dictionary]);

    return <>{parsedNodes}</>;
}
