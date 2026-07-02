'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import type { AttentionSignalMessage, ServerMessage } from '@hie/shared/types/ws';
import { LessonSocket, type LessonSocketStatus } from '@/lib/ws/lessonSocket';
import { usePlayerStore } from '@/stores/player.machine';
import { createClient } from '@/lib/supabase/client';

/**
 * Connects to /ws/{session_id} and wires server messages into the player store.
 * Degrades gracefully — the lesson player must never freeze or crash if the
 * WebSocket fails to connect or drops permanently (AC8).
 */
export function useLessonSocket(sessionId: string | null) {
  const setTutorState = usePlayerStore((s) => s.setTutorState);
  const socketRef = useRef<LessonSocket | null>(null);
  const [status, setStatus] = useState<LessonSocketStatus>('closed');

  useEffect(() => {
    if (!sessionId) return;
    const sid = sessionId; // stable, non-null alias for use inside the nested async init()

    let cancelled = false;

    function handleServerMessage(msg: ServerMessage): void {
      switch (msg.type) {
        case 'state_change':
          setTutorState(msg.payload.to_state);
          break;
        case 'tutor_intervene':
          // Sprint 3 — TutorInterventionCard consumes this; no-op for now.
          break;
        case 'ces_update':
          // Not emitted by any live path yet (Dev 3 owns it); no-op.
          break;
        case 'attention_ack':
          // Live on the wire, but out of scope until Sprint 3 sends real signals; no-op.
          break;
        case 'lesson_ready':
          // Live via Redis pub/sub, but per the wire contract a client that may have
          // missed it must fetch via REST rather than rely on this push; no-op.
          break;
        case 'generation_progress':
          // Not emitted by any live path yet (Dev 1 owns it); no-op.
          break;
        case 'error':
          // eslint-disable-next-line no-console
          console.error('[LessonSocket] server error:', msg.payload.message);
          break;
      }
    }

    async function init(): Promise<void> {
      const supabase = createClient();
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token ?? '';
      if (cancelled) return;

      const socket = new LessonSocket({
        onServerMessage: handleServerMessage,
        onStatusChange: setStatus,
      });
      socketRef.current = socket;
      socket.connect(sid, token);
    }

    init();

    return () => {
      cancelled = true;
      socketRef.current?.disconnect();
      socketRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, setTutorState]);

  const sendAttentionSignal = useCallback((msg: AttentionSignalMessage) => {
    socketRef.current?.send(msg);
  }, []);

  return { status, sendAttentionSignal };
}
