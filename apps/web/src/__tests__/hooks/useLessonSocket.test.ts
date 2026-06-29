import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';

// ---------------------------------------------------------------------------
// Mocks — set up before dynamic imports
// ---------------------------------------------------------------------------

// Mock lessonSocket singleton
const mockConnect = vi.fn();
const mockDisconnect = vi.fn();
const mockSend = vi.fn();

vi.mock('@/lib/ws/lessonSocket', () => ({
  lessonSocket: {
    connect: mockConnect,
    disconnect: mockDisconnect,
    send: mockSend,
    connectionStatus: 'connecting',
  },
}));

// Mock Supabase client
vi.mock('@/lib/supabase/client', () => ({
  createClient: () => ({
    auth: {
      getSession: vi.fn().mockResolvedValue({
        data: { session: { access_token: 'mock-jwt-token' } },
      }),
    },
  }),
}));

// Mock player store — capture the callbacks passed to connect
vi.mock('@/stores/player.machine', () => ({
  usePlayerStore: {
    getState: vi.fn().mockReturnValue({
      setTutorState: vi.fn(),
      updateCes: vi.fn(),
    }),
  },
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useLessonSocket', () => {

  beforeEach(() => {
    vi.useFakeTimers();
    mockConnect.mockClear();
    mockDisconnect.mockClear();
    mockSend.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it('4d: hook calls lessonSocket.connect with sessionId and token on mount', async () => {
    const { useLessonSocket } = await import('@/hooks/useLessonSocket');

    await act(async () => {
      renderHook(() => useLessonSocket('session-xyz'));
      // Allow microtasks (async getSession) to complete
      await Promise.resolve();
    });

    expect(mockConnect).toHaveBeenCalledOnce();
    expect(mockConnect.mock.calls[0][0]).toBe('session-xyz');
    expect(mockConnect.mock.calls[0][1]).toBe('mock-jwt-token');
  });

  it('4e: hook calls lessonSocket.disconnect on unmount', async () => {
    const { useLessonSocket } = await import('@/hooks/useLessonSocket');

    let unmount: () => void;
    await act(async () => {
      const result = renderHook(() => useLessonSocket('session-xyz'));
      unmount = result.unmount;
      await Promise.resolve();
    });

    act(() => { unmount(); });

    expect(mockDisconnect).toHaveBeenCalledOnce();
  });

  it('4f: hook schedules lessonSocket.send on a 5000ms interval', async () => {
    const { useLessonSocket } = await import('@/hooks/useLessonSocket');

    await act(async () => {
      renderHook(() => useLessonSocket('session-xyz'));
      await Promise.resolve();
    });

    // No send before 5000ms
    expect(mockSend).not.toHaveBeenCalled();

    // Advance to first tick
    act(() => { vi.advanceTimersByTime(5000); });
    expect(mockSend).toHaveBeenCalledOnce();

    // Advance to second tick
    act(() => { vi.advanceTimersByTime(5000); });
    expect(mockSend).toHaveBeenCalledTimes(2);

    // Payload type should be 'attention_signal'
    expect(mockSend.mock.calls[0][0].type).toBe('attention_signal');
    expect(mockSend.mock.calls[0][0].payload.session_id).toBe('session-xyz');
  });

  it('4g: onStateChange callback dispatches store.setTutorState()', async () => {
    const { useLessonSocket } = await import('@/hooks/useLessonSocket');
    const { usePlayerStore } = await import('@/stores/player.machine');

    await act(async () => {
      renderHook(() => useLessonSocket('session-xyz'));
      await Promise.resolve();
    });

    // Extract the callbacks passed to connect
    const callbacks = mockConnect.mock.calls[0][2];
    expect(callbacks).toBeDefined();

    // Simulate state_change message from server
    act(() => {
      callbacks.onStateChange({ session_id: 'session-xyz', from_state: 'TEACHING', to_state: 'QUIZZING' });
    });

    expect(usePlayerStore.getState().setTutorState).toHaveBeenCalledWith('QUIZZING');
  });

  it('4h: onCesUpdate callback dispatches store.updateCes()', async () => {
    const { useLessonSocket } = await import('@/hooks/useLessonSocket');
    const { usePlayerStore } = await import('@/stores/player.machine');

    await act(async () => {
      renderHook(() => useLessonSocket('session-xyz'));
      await Promise.resolve();
    });

    const callbacks = mockConnect.mock.calls[0][2];
    act(() => {
      callbacks.onCesUpdate({ session_id: 'session-xyz', ces: 82.0, window_index: 3 });
    });

    expect(usePlayerStore.getState().updateCes).toHaveBeenCalledWith(82.0);
  });

});
