import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { useLessonSocket } from '@/hooks/useLessonSocket';
import { usePlayerStore } from '@/stores/player.machine';
import { FakeWebSocket } from '../testUtils/fakeWebSocket';

const { getSessionMock } = vi.hoisted(() => ({
  getSessionMock: vi.fn(),
}));

vi.mock('@/lib/supabase/client', () => ({
  createClient: () => ({
    auth: { getSession: getSessionMock },
  }),
}));

function latestFake(): FakeWebSocket {
  return FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  global.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
  usePlayerStore.setState({ tutorState: 'IDLE', wsSendControl: null });
  getSessionMock.mockReset();
  getSessionMock.mockResolvedValue({ data: { session: { access_token: 'fake-token' } } });
});

describe('useLessonSocket', () => {
  it('does not construct a socket when sessionId is null', async () => {
    renderHook(() => useLessonSocket(null));

    // Give any stray microtasks a chance to run, then confirm nothing connected.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it('updates player store tutorState after a simulated state_change message (AC3/AC9)', async () => {
    renderHook(() => useLessonSocket('sess_1'));

    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => latestFake().simulateOpen());

    act(() =>
      latestFake().simulateMessage({
        type: 'state_change',
        payload: { session_id: 'sess_1', from_state: 'TEACHING', to_state: 'CHECKING_IN' },
      }),
    );

    await waitFor(() =>
      expect(usePlayerStore.getState().tutorState).toBe('CHECKING_IN'),
    );
  });

  it('disconnects the underlying socket on unmount (AC9)', async () => {
    const { unmount } = renderHook(() => useLessonSocket('sess_1'));

    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const fake = latestFake();
    act(() => fake.simulateOpen());

    unmount();

    expect(fake.readyState).toBe(FakeWebSocket.CLOSED);
  });

  it('ignores a state_change for a different session_id (stale message from an abandoned session)', async () => {
    renderHook(() => useLessonSocket('sess_1'));

    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => latestFake().simulateOpen());

    act(() =>
      latestFake().simulateMessage({
        type: 'state_change',
        payload: { session_id: 'sess_OTHER', from_state: 'TEACHING', to_state: 'CHECKING_IN' },
      }),
    );

    // Give the (would-be) update a tick, then confirm it never happened.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(usePlayerStore.getState().tutorState).toBe('IDLE');
  });

  it('does not throw and does not update tutorState on a malformed state_change (missing to_state)', async () => {
    renderHook(() => useLessonSocket('sess_1'));

    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => latestFake().simulateOpen());

    expect(() =>
      act(() =>
        latestFake().simulateMessage({
          type: 'state_change',
          payload: { session_id: 'sess_1' },
        }),
      ),
    ).not.toThrow();

    expect(usePlayerStore.getState().tutorState).toBe('IDLE');
  });

  it.each([
    ['tutor_intervene', { session_id: 'sess_1', type: 'distraction', message: 'hi' }],
    ['ces_update', { session_id: 'sess_1', ces: 0.5, window_index: 1 }],
    ['attention_ack', { session_id: 'sess_1', ces: 0.5 }],
    ['lesson_ready', { session_id: 'sess_1', lesson_id: 'lsn_1', lesson: {} }],
    ['generation_progress', { session_id: 'sess_1', lesson_id: 'lsn_1', node: 'x', progress: 1, message: 'x' }],
  ])('handles %s as a no-op without throwing or mutating tutorState', async (type, payload) => {
    renderHook(() => useLessonSocket('sess_1'));

    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => latestFake().simulateOpen());

    expect(() => act(() => latestFake().simulateMessage({ type, payload }))).not.toThrow();
    expect(usePlayerStore.getState().tutorState).toBe('IDLE');
  });

  it('degrades gracefully (status closed, no socket) when the Supabase session lookup rejects', async () => {
    getSessionMock.mockRejectedValueOnce(new Error('network down'));

    const { result } = renderHook(() => useLessonSocket('sess_1'));

    // Synchronous setStatus('connecting') should already have run on mount.
    expect(result.current.status).toBe('connecting');

    await waitFor(() => expect(result.current.status).toBe('closed'));
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it('registers wsSendControl into the player store once the socket connects, and it forwards to the real socket (S2-06)', async () => {
    renderHook(() => useLessonSocket('sess_1'));

    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => latestFake().simulateOpen());

    await waitFor(() => expect(usePlayerStore.getState().wsSendControl).not.toBeNull());

    act(() => usePlayerStore.getState().wsSendControl!({ type: 'segment_complete' }));

    expect(latestFake().sentMessages).toContain(JSON.stringify({ type: 'segment_complete' }));
  });

  it('clears wsSendControl in the player store on unmount (S2-06)', async () => {
    const { unmount } = renderHook(() => useLessonSocket('sess_1'));

    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => latestFake().simulateOpen());
    await waitFor(() => expect(usePlayerStore.getState().wsSendControl).not.toBeNull());

    unmount();

    expect(usePlayerStore.getState().wsSendControl).toBeNull();
  });

  it('a stale instance unmounting after a fresher instance has taken over does not clobber the fresher one (review fix)', async () => {
    const first = renderHook(() => useLessonSocket('sess_1'));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => latestFake().simulateOpen());
    await waitFor(() => expect(usePlayerStore.getState().wsSendControl).not.toBeNull());
    const firstSendControl = usePlayerStore.getState().wsSendControl;

    // A second, fresher instance connects (e.g. StrictMode double-invoke, or fast
    // sessionId churn) before the first one has unmounted.
    renderHook(() => useLessonSocket('sess_2'));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    act(() => FakeWebSocket.instances[1].simulateOpen());
    await waitFor(() => expect(usePlayerStore.getState().wsSendControl).not.toBe(firstSendControl));
    const secondSendControl = usePlayerStore.getState().wsSendControl;

    // The stale first instance unmounts last — its cleanup must not null out the
    // second instance's still-live send function.
    first.unmount();

    expect(usePlayerStore.getState().wsSendControl).toBe(secondSendControl);
    expect(usePlayerStore.getState().wsSendControl).not.toBeNull();
  });
});
