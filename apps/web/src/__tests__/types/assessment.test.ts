import { describe, it, expect } from 'vitest';
import type {
  QuizAnswer,
  OnboardingAnswer,
  QuizSubmission,
  QuizResult,
  TeachbackSubmission,
  TeachbackResult,
  SessionReport,
  LearnerDNA,
  OnboardingDiagnosticSubmission,
  OnboardingResult,
} from '@/types/assessment';

// ── Type-shape tests via runtime value construction ───────────────────────
// These tests prove the interface shapes are correct at compile time.
// If any field name or type is wrong, TypeScript will fail here.

describe('assessment types', () => {
  it('2a: TeachbackSubmission has response_text (typed text) — no transcript/audio field', () => {
    const submission: TeachbackSubmission = {
      session_id: 'sess_001',
      lesson_id: 'lesson_001',
      segment_id: 'seg_01',
      response_text: 'Photosynthesis converts sunlight into glucose.',
    };
    expect(submission.response_text).toBe('Photosynthesis converts sunlight into glucose.');
    // TypeScript: if this compiles, there is no 'transcript' or 'audio' required field
    expect(Object.keys(submission)).not.toContain('transcript');
    expect(Object.keys(submission)).not.toContain('audio');
  });

  it('2b: LearnerDNA.profile_text is string | null — not a number or truncated type', () => {
    const dna: LearnerDNA = {
      user_id: 'user_abc',
      badge_labels: ['Pattern Thinker'],
      profile_text: 'You are a deep learner. [DPDP disclaimer text]',
      session_count: 3,
      reassessment_due: false,
      last_updated: '2026-06-26T00:00:00Z',
    };
    expect(typeof dna.profile_text).toBe('string');

    const dnaNullProfile: LearnerDNA = {
      user_id: 'user_xyz',
      badge_labels: [],
      profile_text: null,
      session_count: 0,
      reassessment_due: true,
      last_updated: null,
    };
    expect(dnaNullProfile.profile_text).toBeNull();
  });

  it('2c: QuizAnswer uses response_index (number) — not selected_option', () => {
    const answer: QuizAnswer = {
      question_id: 'q_001',
      response_index: 2,
    };
    expect(answer.response_index).toBe(2);
    expect(Object.keys(answer)).not.toContain('selected_option');
  });

  it('QuizSubmission includes lesson_id and segment_id', () => {
    const sub: QuizSubmission = {
      session_id: 'sess_001',
      lesson_id: 'lesson_001',
      segment_id: 'seg_01',
      answers: [{ question_id: 'q_001', response_index: 0 }],
    };
    expect(sub.lesson_id).toBe('lesson_001');
    expect(sub.segment_id).toBe('seg_01');
  });

  it('OnboardingAnswer has dimension union type', () => {
    const ans: OnboardingAnswer = {
      question_id: 'c1',
      dimension: 'cognitive',
      selected_index: 2,
      selected_text: 'I prefer to understand the why',
    };
    expect(['cognitive', 'emotional', 'self_direction']).toContain(ans.dimension);
  });

  it('OnboardingDiagnosticSubmission uses responses[] (not subject/grade_level)', () => {
    const sub: OnboardingDiagnosticSubmission = {
      responses: [
        { question_id: 'c1', dimension: 'cognitive', selected_index: 1, selected_text: 'Why' },
      ],
    };
    expect(sub.responses).toHaveLength(1);
    expect(Object.keys(sub)).not.toContain('subject');
    expect(Object.keys(sub)).not.toContain('grade_level');
  });

  it('OnboardingResult uses badge_labels/profile_text (not dna_label/profile_narrative)', () => {
    const result: OnboardingResult = {
      badge_labels: ['Pattern Thinker'],
      profile_text: 'You learn visually. — Pursuant to DPDP Act 2023.',
      session_count: 0,
    };
    expect(result.badge_labels).toContain('Pattern Thinker');
    expect(Object.keys(result)).not.toContain('dna_label');
    expect(Object.keys(result)).not.toContain('profile_narrative');
    const forbidden = [
      'pattern_recognition', 'logical_deduction', 'processing_speed',
      'frustration_tolerance', 'persistence', 'help_seeking',
      'goal_orientation', 'curiosity_index', 'study_independence',
    ];
    for (const field of forbidden) {
      expect(Object.keys(result)).not.toContain(field);
    }
  });

  it('SessionReport has duration_minutes (not duration_seconds)', () => {
    const report: SessionReport = {
      session_id: 'sess_001',
      user_id: 'user_001',
      lesson_id: 'lesson_001',
      ces_score: 72,
      ces_breakdown: { quiz: 28.0, teachback: 20.0, behavioral: 0.0, head_pose: 0.0, blink: 0.0 },
      interventions_count: 2,
      quiz_score: 0.75,
      teachback_score: null,
      duration_minutes: 18,
      completed_at: '2026-06-26T10:00:00Z',
      tier: 'T2',
      tier_label: 'Standard',
      quiz_total_questions: 4,
      quiz_correct_count: 3,
      quiz_accuracy_label: 'Strong',
      learner_dna_snapshot: null,
    };
    expect(report.duration_minutes).toBe(18);
    expect(Object.keys(report)).not.toContain('duration_seconds');
  });

  it('SessionReport.ces_breakdown has exactly the 5 real backend keys (quiz/teachback/behavioral/head_pose/blink) — not quiz_accuracy', () => {
    const report: SessionReport = {
      session_id: 'sess_001',
      user_id: 'user_001',
      lesson_id: 'lesson_001',
      ces_score: 48.0,
      ces_breakdown: { quiz: 28.0, teachback: 20.0, behavioral: 0.0, head_pose: 0.0, blink: 0.0 },
      interventions_count: 0,
      quiz_score: null,
      teachback_score: null,
      duration_minutes: 5,
      completed_at: null,
      tier: 'T2',
      tier_label: 'Standard',
      quiz_total_questions: 0,
      quiz_correct_count: 0,
      quiz_accuracy_label: null,
      learner_dna_snapshot: null,
    };
    expect(Object.keys(report.ces_breakdown).sort()).toEqual(
      ['behavioral', 'blink', 'head_pose', 'quiz', 'teachback']
    );
  });

  it('TeachbackResult has overall_score and rubric_scores', () => {
    const result: TeachbackResult = {
      session_id: 'sess_001',
      rubric_scores: { accuracy: 0.9, depth: 0.7, clarity: 0.8, relevance: 0.85 },
      overall_score: 0.81,
      ces_contribution: 0.81,
      feedback: 'Strong answer.',
    };
    expect(result.overall_score).toBe(0.81);
    expect(result.rubric_scores.accuracy).toBe(0.9);
  });

  it('QuizResult has ces_contribution field', () => {
    const result: QuizResult = {
      session_id: 'sess_001',
      score: 0.75,
      correct_count: 3,
      total_count: 4,
      ces_contribution: 0.75,
      feedback: [{
        question_id: 'q_001', question: 'Q?', is_correct: true,
        correct_index: 0, correct_option: 'A', selected_option: 'A',
        explanation: 'Great.',
      }],
    };
    expect(result.ces_contribution).toBe(0.75);
  });
});
