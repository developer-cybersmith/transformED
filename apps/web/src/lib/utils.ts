import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

// Review fix: avatar seeds must not leak a user's real name/email to
// third-party avatar CDNs (ui-avatars.com, dicebear) as a plaintext query
// param. Initials are a minimal, non-identifying substitute for services that
// render literal text (ui-avatars); trims/filters so a leading-space or
// whitespace-only name never produces a blank/garbled result.
export function getInitials(name: string): string {
    const parts = name.trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return "?";
    const first = parts[0][0];
    const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
    return (first + last).toUpperCase();
}

// Same trim/filter discipline as getInitials — a leading-space full_name
// (e.g. " Robert") previously produced a blank first name via a bare
// `.split(" ")[0]` (review fix).
export function getFirstName(name: string): string {
    const parts = name.trim().split(/\s+/).filter(Boolean);
    return parts[0] ?? "";
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
// NaN/out-of-range input is surfaced as "Unknown" rather than silently banded
// as the lowest score — a malformed response shouldn't read as "fully disengaged".
export function formatCesLabel(cesScore: number): string {
    if (!Number.isFinite(cesScore) || cesScore < 0 || cesScore > 100) return "Unknown";
    if (cesScore >= 80) return "Highly Engaged";
    if (cesScore >= 60) return "Well Focused";
    if (cesScore >= 40) return "Getting There";
    return "Room to Grow";
}

// Teach-back score is never shown as a raw number to students (PRD: no rubric
// score shown in Phase 1) — same rule already enforced on TeachBackModal.
export function formatTeachbackLabel(teachbackScore: number | null): string {
    if (teachbackScore === null) return "No teach-back this session";
    if (!Number.isFinite(teachbackScore) || teachbackScore < 0 || teachbackScore > 100) return "Unknown";
    if (teachbackScore >= 80) return "Strong grasp";
    if (teachbackScore >= 60) return "Solid understanding";
    return "Needs another look";
}
