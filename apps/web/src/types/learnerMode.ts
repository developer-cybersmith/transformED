export type LearnerTier = 'deep' | 'balanced' | 'refresher';

export interface LearnerTierOption {
  id: LearnerTier;
  label: string;
  description: string;
  disclaimer?: string;
  /** Total SEAT TIME in minutes -- the whole session in the player: teaching,
   *  quizzes, teach-back and tutor Q&A together. Mirrors the backend's
   *  TIER_SEAT_MINUTES (apps/api/app/schemas/lesson.py), not an independent
   *  estimate. Story 2-60 / BR-2; Story S5-4 made it enforced rather than a
   *  label: the backend now budgets narration words, quiz volume and the Q&A
   *  window from this number instead of generating identical content for
   *  every tier. */
  durationMinutes: number;
}

// S2-09: maps the frontend's descriptive tier id to the backend's T1/T2/T3
// contract (apps/api/app/schemas/lesson.py). Story S5-4 reinterpreted that enum:
// it means DURATION (45/30/15 min of seat time), not content depth — the
// "full depth / standard / critical-topics-only" framing it used to carry was
// deleted from the pipeline's prompts. See docs/stories/S5-4-duration-driven-lessons.md.
export const LEARNER_TIER_TO_BACKEND: Record<LearnerTier, 'T1' | 'T2' | 'T3'> = {
  deep: 'T1',
  balanced: 'T2',
  refresher: 'T3',
};

export const LEARNER_TIER_OPTIONS: LearnerTierOption[] = [
  {
    id: 'deep',
    label: 'Deep',
    description:
      'A full 45-minute session — teaching, quizzes and Q&A — covering the chapter thoroughly.',
    durationMinutes: 45,
  },
  {
    id: 'balanced',
    label: 'Balanced',
    description: 'A 30-minute session covering the chapter’s essentials, end to end.',
    disclaimer: 'Content is planned to fit the time — some detail is left out.',
    durationMinutes: 30,
  },
  {
    id: 'refresher',
    label: 'Refresher',
    description: 'A 15-minute session — best if you already know this material.',
    disclaimer: 'Assumes you already have prior mastery — not a full first-pass lesson.',
    durationMinutes: 15,
  },
];
