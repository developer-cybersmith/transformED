// Sprint 0 interface contract — frozen
// WebSocket discriminated union types for TransformED AI.
// Covers all messages defined in PRD §16.

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
// Server → Client messages
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
// Client → Server messages
// ---------------------------------------------------------------------------

/**
 * Batched engagement signals sent by the frontend every N seconds.
 * Null values indicate a metric was not available in this window.
 */
export type AttentionSignalMessage = WsMessage<
  'attention_signal',
  {
    session_id: string;
    quiz_accuracy: number | null;
    teachback_score: number | null;
    behavioral_score: number;
    head_pose_score: number;
    blink_rate: number;
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
