import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { useLessonSocket } from '@/hooks/useLessonSocket';
import { usePlayerStore } from '@/stores/player.machine';
import { FakeWebSocket } from '../testUtils/fakeWebSocket';

vi.mock('@/lib/supabase/client', () => ({
  createClient: () => ({
    auth: {
      getSession: () =>
        Promise.resolve({ data: { session: { access_token: 'fake-token' } } }),
    },
  }),
}));

function latestFake(): FakeWebSocket {
  return FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  global.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
  usePlayerStore.setState({ tutorState: 'IDLE' });
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
});
