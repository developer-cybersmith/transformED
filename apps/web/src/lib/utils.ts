import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

export function formatTimeAgo(iso: string): string {
    const timestamp = new Date(iso).getTime();
    if (Number.isNaN(timestamp)) return "Unknown";

    const diffMs = Date.now() - timestamp;
    const diffMinutes = Math.floor(diffMs / 60000);

    if (diffMinutes < 1) return "Just now";
    if (diffMinutes < 60) return `${diffMinutes} minute${diffMinutes === 1 ? "" : "s"} ago`;

    const diffHours = Math.floor(diffMinutes / 60);
    if (diffHours < 24) return `${diffHours} hour${diffHours === 1 ? "" : "s"} ago`;

    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays} day${diffDays === 1 ? "" : "s"} ago`;
}

// CES is never shown as a raw number to students (PRD: descriptive label only).
export function formatCesLabel(cesScore: number): string {
    if (cesScore >= 80) return "Highly Engaged";
    if (cesScore >= 60) return "Well Focused";
    if (cesScore >= 40) return "Getting There";
    return "Room to Grow";
}

// Teach-back score is never shown as a raw number to students (PRD: no rubric
// score shown in Phase 1) — same rule already enforced on TeachBackModal.
export function formatTeachbackLabel(teachbackScore: number | null): string {
    if (teachbackScore === null) return "No teach-back this session";
    if (teachbackScore >= 80) return "Strong grasp";
    if (teachbackScore >= 60) return "Solid understanding";
    return "Needs another look";
}
