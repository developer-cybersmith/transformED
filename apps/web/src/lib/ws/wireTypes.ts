// Local-only wire types — NOT part of the frozen `@hie/shared/types/ws` contract.
//
// The live backend (docs/ws-message-contract.md) accepts/sends several flat control
// frames that packages/shared/types/ws.ts does not define, and diverges from the
// typed `error` shape. Rather than touching the frozen contract (requires a
// 4-dev-reviewed PR), these types stay local to apps/web and are normalized at the
// lessonSocket.ts boundary — see that file's onmessage handler.
//
// TODO(ws-contract-pr): once docs/ws-message-contract.md's reconciliation items
// (a)-(e) land in ws.ts, delete this file's local unions and fold OutgoingMessage /
// the normalization shim in lessonSocket.ts back into the frozen ClientMessage /
// ServerMessage types directly.

import type { ClientMessage } from '@hie/shared/types/ws';

/** Client → server flow events that drive the tutor FSM (see _TUTOR_CLIENT_EVENTS
 *  in apps/api/app/core/websocket.py). Flat `{type}` frames, no payload. */
type FlowEvent =
  | 'segment_complete'
  | 'checkin_complete'
  | 'low_checkin_score'
  | 'quiz_trigger'
  | 'quiz_complete'
  | 'quiz_failed'
  | 'teachback_complete'
  | 'teachback_failed'
  | 'lesson_complete';

/** Flat control frames the client may send that aren't in the frozen ClientMessage union. */
export type LocalControlOut =
  | { type: 'session_start' }
  | { type: 'ping' }
  | { type: FlowEvent };

/** Flat control/error frames the server may send that aren't in the frozen ServerMessage union. */
export type LocalControlIn =
  | { type: 'pong' }
  | { error: string };

/** Everything LessonSocket can send: the frozen contract plus local control frames. */
export type OutgoingMessage = ClientMessage | LocalControlOut;
