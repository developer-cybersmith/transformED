// Assessment API contract types — matches Dev 3 OpenAPI spec (docs/openapi-assessment.json)
// Do not modify field names without a 4-developer PR review (frozen interface contract).

// ── Shared building blocks ────────────────────────────────────────────────

export interface QuizAnswer {
  question_id: string;
  response_index: number;
  response_time_ms?: number;
}

export interface OnboardingAnswer {
  question_id: string;
  dimension: "cognitive" | "emotional" | "self_direction";
  selected_index: number;
  selected_text: string;
}

// ── POST /api/assessment/quiz ─────────────────────────────────────────────

export interface QuizSubmission {
  session_id: string;
  lesson_id: string;
  segment_id: string;
  answers: QuizAnswer[];
}

export interface QuizResult {
  session_id: string;
  score: number;
  correct_count: number;
  total_count: number;
  ces_contribution: number;
  feedback: Array<{ [key: string]: unknown }>;
}

// ── POST /api/assessment/teachback ────────────────────────────────────────

export interface TeachbackSubmission {
  session_id: string;
  lesson_id: string;
  segment_id: string;
  response_text: string; // TYPED text only — NO transcript, NO audio, NO STT
}

export interface TeachbackResult {
  session_id: string;
  rubric_scores: {
    accuracy?: number;
    depth?: number;
    clarity?: number;
    relevance?: number;
    [key: string]: number | undefined;
  };
  overall_score: number;
  ces_contribution: number;
  feedback: string;
}

// ── GET /api/assessment/session/{session_id}/report ───────────────────────

// Story 3-30 (learner_dna_snapshot). Label values verified against the actual
// shipped backend (apps/api/app/modules/assessment/service.py's
// _score_to_label()/_delta_to_growth_label(), not just the story doc) -- NOT
// Dev 3's HTML integration guide, whose DimensionLabel/GrowthLabel
// definitions are stale/incomplete (no 'Advanced' dimension label exists;
// the growth label is 'Needs Attention', not 'Declining'; and the guide
// omits the real 'Exceptional' band entirely -- review-round fix).
export type DnaDimension =
  | 'pattern_recognition'
  | 'logical_deduction'
  | 'processing_speed'
  | 'frustration_tolerance'
  | 'persistence'
  | 'help_seeking'
  | 'goal_orientation'
  | 'curiosity_index'
  | 'study_independence';

export type DnaDimensionLabel = 'Beginning' | 'Emerging' | 'Developing' | 'Proficient' | 'Exceptional';
export type DnaGrowthLabel = 'Improving' | 'Stable' | 'Needs Attention';

export interface LearnerDnaSnapshot {
  dimension_labels: Record<DnaDimension, DnaDimensionLabel>;
  growth_labels: Record<DnaDimension, DnaGrowthLabel | null>;
}

export interface SessionReport {
  session_id: string;
  user_id: string;
  lesson_id: string;
  ces_score: number;
  // Exactly 5 keys, matching the frozen backend contract verbatim
  // (apps/api/app/modules/assessment/router.py SessionReport, story 3-19 AC 7).
  // behavioral/head_pose/blink are always 0.0 in Sprint 2 (Phase 3 concern).
  ces_breakdown: {
    quiz: number;
    teachback: number;
    behavioral: number;
    head_pose: number;
    blink: number;
  };
  interventions_count: number;
  quiz_score: number | null;
  teachback_score: number | null;
  duration_minutes: number;
  completed_at: string | null;
  // Story 3-29 additions — tier is defaulted to 'T2'/'Standard' server-side
  // when the lessons row is missing/unrecognized; never absent or null.
  tier: 'T1' | 'T2' | 'T3';
  tier_label: string;
  quiz_total_questions: number;
  quiz_correct_count: number;
  quiz_accuracy_label: 'Strong' | 'Developing' | 'Needs Review' | null;
  // Story 3-30 addition — null when the user has no learner_dna row yet.
  learner_dna_snapshot: LearnerDnaSnapshot | null;
}

// ── GET /api/assessment/user/dna ──────────────────────────────────────────

export interface LearnerDNA {
  user_id: string;
  badge_labels: string[];
  profile_text: string | null; // DPDP Act 2023: always ends with legal disclaimer — never truncate
  session_count: number;
  reassessment_due: boolean;
  last_updated: string | null;
}

// ── POST /api/assessment/onboarding/submit ────────────────────────────────

export interface OnboardingDiagnosticSubmission {
  responses: OnboardingAnswer[];
}

export interface OnboardingResult {
  badge_labels: string[];
  profile_text: string; // always ends with the DPDP Act 2023 disclaimer sentence — never truncate
  session_count: number;
}
