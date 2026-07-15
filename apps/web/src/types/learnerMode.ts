export type LearnerTier = 'deep' | 'balanced' | 'refresher';

export interface LearnerTierOption {
  id: LearnerTier;
  label: string;
  description: string;
  disclaimer?: string;
}

export const LEARNER_TIER_OPTIONS: LearnerTierOption[] = [
  {
    id: 'deep',
    label: 'Deep',
    description: 'Full-depth lesson with no time constraint — covers everything.',
  },
  {
    id: 'balanced',
    label: 'Balanced',
    description: 'Time-boxed depth — covers the essentials within your available time.',
    disclaimer: 'Content may be trimmed or condensed to fit your available time.',
  },
  {
    id: 'refresher',
    label: 'Refresher',
    description: 'Condensed review — best if you already know this material.',
    disclaimer: 'Assumes you already have prior mastery — not a full first-pass lesson.',
  },
];
