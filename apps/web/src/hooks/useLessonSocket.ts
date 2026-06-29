import { useEffect, useRef } from 'react';
import { createClient } from '@/lib/supabase/client';
import { lessonSocket } from '@/lib/ws/lessonSocket';
import type { ConnectionStatus } from '@/lib/ws/lessonSocket';
import { usePlayerStore } from '@/stores/player.machine';
import type { AttentionSignalMessage } from '@hie/shared/types/ws';

export function useLessonSocket(sessionId: string): { connectionStatus: ConnectionStatus } {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let mounted = true;

    const init = async () => {
      const supabase = createClient();
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token ?? '';
      if (!mounted) return;

      lessonSocket.connect(sessionId, token, {
        onTutorIntervene: () => {
          usePlayerStore.getState().setTutorState('INTERVENING');
        },
        onCesUpdate: (payload) => {
          usePlayerStore.getState().updateCes(payload.ces);
        },
        onStateChange: (payload) => {
          usePlayerStore.getState().setTutorState(payload.to_state);
        },
      });

      // Sprint 1: send placeholder attention signal every 5s.
      // Sprint 3: replace defaults with real values from AttentionMonitor.
      intervalRef.current = setInterval(() => {
        const signal: AttentionSignalMessage = {
          type: 'attention_signal',
          payload: {
            session_id: sessionId,
            quiz_accuracy: null,
            teachback_score: null,
            behavioral_score: 1.0,
            head_pose_score: 1.0,
            blink_rate: 0.2,
          },
        };
        lessonSocket.send(signal);
      }, 5000);
    };

    init();

    return () => {
      mounted = false;
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      lessonSocket.disconnect();
    };
  }, [sessionId]);

  return { connectionStatus: lessonSocket.connectionStatus };
}
