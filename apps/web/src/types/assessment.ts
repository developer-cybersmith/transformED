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

export interface SessionReport {
  session_id: string;
  user_id: string;
  lesson_id: string;
  ces_score: number;
  ces_breakdown: {
    quiz_accuracy?: number;
    teachback_score?: number;
    behavioral?: number;
    head_pose?: number;
    blink?: number;
    [key: string]: number | undefined;
  };
  interventions_count: number;
  quiz_score: number | null;
  teachback_score: number | null;
  duration_minutes: number;
  completed_at: string | null;
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
