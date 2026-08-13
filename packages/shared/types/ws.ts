// Sprint 0 interface contract â€” frozen
// WebSocket discriminated union types for HIE.
// Covers all messages defined in PRD Â§16.

import type { LessonPackage } from './lesson';

// ---------------------------------------------------------------------------
// Shared domain types
// ---------------------------------------------------------------------------

export type TutorState =
  | 'IDLE'
  | 'TEACHING'
  | 'INTERVENING'
  | 'CHECKING_IN'
  | 'QUIZZING'
  | 'TEACH_BACK'
  | 'SESSION_END';

export type InterventionType = 'distraction' | 'confusion' | 'fatigue';

// ---------------------------------------------------------------------------
// Generic base
// ---------------------------------------------------------------------------

export interface WsMessage<T extends string, P> {
  type: T;
  payload: P;
}

// ---------------------------------------------------------------------------
// Server â†’ Client messages
// ---------------------------------------------------------------------------

/** Lesson generation completed; full package delivered to client. */
export type LessonReadyMessage = WsMessage<
  'lesson_ready',
  { lesson_id: string; lesson: LessonPackage }
>;

/** Streaming progress during lesson generation (LangGraph node updates). */
export type GenerationProgressMessage = WsMessage<
  'generation_progress',
  { lesson_id: string; node: string; progress: number; message: string }
>;

/** Server acknowledges an attention signal and returns the computed CES. */
export type AttentionAckMessage = WsMessage<
  'attention_ack',
  { session_id: string; ces: number }
>;

/** Tutor intervention triggered by the attention pipeline. */
export type TutorInterveneMessage = WsMessage<
  'tutor_intervene',
  {
    session_id: string;
    type: InterventionType;
    message: string;
    action?: string;
  }
>;

/** Periodic CES update pushed to the client. */
export type CesUpdateMessage = WsMessage<
  'ces_update',
  { session_id: string; ces: number; window_index: number }
>;

/** Tutor FSM state transition notification. */
export type StateChangeMessage = WsMessage<
  'state_change',
  { session_id: string; from_state: TutorState; to_state: TutorState }
>;

/** Generic error from the server. */
export type ErrorMessage = WsMessage<
  'error',
  { code: string; message: string }
>;

// ---------------------------------------------------------------------------
// Client â†’ Server messages
// ---------------------------------------------------------------------------

/**
 * Batched engagement signals sent by the frontend every N seconds.
 * All numeric fields are on the [0.0, 1.0] scale.
 * Null values indicate a metric was not available in this window —
 * the backend redistributes CES weights proportionally across present signals.
 *
 * SYNC-B freeze (Story 4-27, 2026-08-13): field definitions and null semantics
 * are now authoritative. Do not change without a PR reviewed by all 4 developers.
 */
export type AttentionSignalMessage = WsMessage<
  'attention_signal',
  {
    session_id: string;

    /** range: [0.0, 1.0] — fraction of quiz questions answered correctly this window.
     *  null = no quiz submitted yet. */
    quiz_accuracy: number | null;

    /** range: [0.0, 1.0] — normalised teach-back score.
     *  null = teach-back skipped or not yet attempted. */
    teachback_score: number | null;

    /** range: [0.0, 1.0] — tab-visibility score (MVP definition).
     *  1.0 = document.visibilityState === 'visible' (tab in foreground).
     *  0.0 = tab is hidden (backgrounded, minimised, or visibilityState !== 'visible').
     *  null = Page Visibility API unavailable (e.g. cross-origin iframe restriction). */
    behavioral_score: number | null;

    /** range: [0.0, 1.0] — normalised head-pose attention score from MediaPipe.
     *  null = MediaPipe not yet initialised, or this frame was dropped. */
    head_pose_score: number | null;

    /** range: [0.0, 1.0] — normalised blink-rate score (higher = more alert).
     *  null = MediaPipe not yet initialised, or this frame was dropped. */
    blink_rate: number | null;
  }
>;

// ---------------------------------------------------------------------------
// Union types
// ---------------------------------------------------------------------------

export type ServerMessage =
  | LessonReadyMessage
  | GenerationProgressMessage
  | AttentionAckMessage
  | TutorInterveneMessage
  | CesUpdateMessage
  | StateChangeMessage
  | ErrorMessage;

export type ClientMessage = AttentionSignalMessage;

export type AnyWsMessage = ServerMessage | ClientMessage;

// ---------------------------------------------------------------------------
// Factory helper
// ---------------------------------------------------------------------------

export function createWsMessage<T extends string, P>(
  type: T,
  payload: P,
): WsMessage<T, P> {
  return { type, payload };
}

