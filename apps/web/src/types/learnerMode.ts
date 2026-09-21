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

// S5-2: labels and descriptions updated to reflect HIE lecture-format names.
// durationMinutes, LEARNER_TIER_TO_BACKEND mapping, and LearnerTier type are unchanged.
export const LEARNER_TIER_OPTIONS: LearnerTierOption[] = [
  {
    id: 'deep',
    label: '45 min',
    description: 'HIE Master Session — dual-topic, 10 slides with binding timings. Full depth.',
    durationMinutes: 45,
  },
  {
    id: 'balanced',
    label: '30 min',
    description: 'HIE Dual-Topic Protocol — two topics, 10 slides. Covers the essentials.',
    durationMinutes: 30,
  },
  {
    id: 'refresher',
    label: '15 min',
    description: 'HIE First-Teach — single topic, 7 slides. Best for a first introduction.',
    durationMinutes: 15,
  },
];
