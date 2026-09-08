export type LearnerTier = 'deep' | 'balanced' | 'refresher';

export interface LearnerTierOption {
  id: LearnerTier;
  label: string;
  description: string;
  disclaimer?: string;
  /** Fixed lesson duration in minutes -- mirrors the backend's own
   *  _TIER_MINUTES (Story F2-3, apps/api/app/modules/assessment/service.py),
   *  not an independent estimate. Story 2-60 / BR-2. */
  durationMinutes: number;
}

// S2-09: maps the frontend's descriptive tier id to the backend's T1/T2/T3
// contract (apps/api/app/schemas/lesson.py) — deep=full depth, balanced=standard
// default, refresher=critical-topics-only. See docs/stories/2-lm3-lm4-lm5-tier-aware-generation.md.
export const LEARNER_TIER_TO_BACKEND: Record<LearnerTier, 'T1' | 'T2' | 'T3'> = {
  deep: 'T1',
  balanced: 'T2',
  refresher: 'T3',
};

export const LEARNER_TIER_OPTIONS: LearnerTierOption[] = [
  {
    id: 'deep',
    label: 'Deep',
    description: 'Full-depth lesson with no time constraint — covers everything.',
    durationMinutes: 45,
  },
  {
    id: 'balanced',
    label: 'Balanced',
    description: 'Time-boxed depth — covers the essentials within your available time.',
    disclaimer: 'Content may be trimmed or condensed to fit your available time.',
    durationMinutes: 30,
  },
  {
    id: 'refresher',
    label: 'Refresher',
    description: 'Condensed review — best if you already know this material.',
    disclaimer: 'Assumes you already have prior mastery — not a full first-pass lesson.',
    durationMinutes: 15,
  },
];
