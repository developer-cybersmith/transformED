import { api } from './api';
import type { SessionReport } from '@/types/assessment';

// ── Quiz ──────────────────────────────────────────────────────────────────────

export interface QuizAnswer {
  question_id: string;
  response_index: number;
  response_time_ms: number;
}

export interface QuizSubmitPayload {
  session_id: string;
  lesson_id: string;
  segment_id: string;
  answers: QuizAnswer[];
}

export interface QuizFeedbackItem {
  question_id: string;
  correct: boolean;
  message: string;
}

export interface QuizResult {
  session_id: string;
  score: number;
  correct_count: number;
  total_count: number;
  ces_contribution: number;
  feedback: QuizFeedbackItem[];
}

export async function submitQuiz(payload: QuizSubmitPayload): Promise<QuizResult> {
  const { data } = await api.post<QuizResult>('/assessment/quiz', payload);
  return data;
}

// ── Teach-back ────────────────────────────────────────────────────────────────

export interface TeachBackSubmitPayload {
  session_id: string;
  lesson_id: string;
  segment_id: string;
  response_text: string;
}

export interface RubricScores {
  accuracy: number;
  completeness: number;
  clarity: number;
}

export interface TeachBackResult {
  session_id: string;
  rubric_scores: RubricScores;
  overall_score: number;
  ces_contribution: number;
  feedback: string;
}

export async function submitTeachBack(payload: TeachBackSubmitPayload): Promise<TeachBackResult> {
  const { data } = await api.post<TeachBackResult>('/assessment/teachback', payload);
  return data;
}

// ── Session report ──────────────────────────────────────────────────────────

export async function getSessionReport(sessionId: string): Promise<SessionReport> {
  const { data } = await api.get<SessionReport>(
    `/assessment/session/${encodeURIComponent(sessionId)}/report`
  );
  return data;
}
