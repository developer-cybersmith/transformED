// Re-export the frozen Sprint 0 WS contract for use across the web app.
// Source of truth: packages/shared/types/ws.ts
// When the real FastAPI WebSocket is wired in Sprint 2, components import
// directly from '@hie/shared/types/ws' — this file stays as a barrel.

import type { ServerMessage } from '@hie/shared/types/ws';

export type {
  WsMessage,
  TutorState,
  InterventionType,
  LessonReadyMessage,
  GenerationProgressMessage,
  AttentionAckMessage,
  TutorInterveneMessage,
  CesUpdateMessage,
  StateChangeMessage,
  ErrorMessage,
  AttentionSignalMessage,
  ServerMessage,
  ClientMessage,
  AnyWsMessage,
} from '@hie/shared/types/ws';

/** Callback signature for components subscribed to server messages. */
export type WebSocketCallback = (event: ServerMessage) => void;

/** Options for the mock socket simulation layer (Sprint 0/1 dev only). */
export interface MockSocketOptions {
  simulateError?: boolean;
  /** Name of the pipeline stage at which to inject an error. */
  errorStage?: string;
  /** Skip realistic delays for fast dev/test iteration. */
  fastForwardProcessing?: boolean;
}
