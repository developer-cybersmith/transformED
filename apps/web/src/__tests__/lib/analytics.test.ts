import { describe, it, expect, vi, beforeEach } from 'vitest';

const { apiPostMock } = vi.hoisted(() => ({
  apiPostMock: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  api: { post: apiPostMock },
}));

import { trackEvent } from '@/lib/analytics';
import { usePlayerStore } from '@/stores/player.machine';

beforeEach(() => {
  apiPostMock.mockReset();
  apiPostMock.mockResolvedValue({ data: { inserted: 1 } });
});

describe('trackEvent', () => {
  it('does not call the API when there is no sessionId yet', () => {
    usePlayerStore.setState({ sessionId: '' });

    trackEvent('jargon_hover', { term: 'API' });

    expect(apiPostMock).not.toHaveBeenCalled();
  });

  it('posts a single-event batch with the current sessionId, event type, and payload', () => {
    usePlayerStore.setState({ sessionId: 'sess_123' });

    trackEvent('jargon_hover', { term: 'Neural Network' });

    expect(apiPostMock).toHaveBeenCalledTimes(1);
    const [path, body] = apiPostMock.mock.calls[0];
    expect(path).toBe('/analytics/events');
    expect(body.events).toHaveLength(1);
    expect(body.events[0]).toMatchObject({
      session_id: 'sess_123',
      event_type: 'jargon_hover',
      payload: { term: 'Neural Network' },
    });
    expect(typeof body.events[0].client_timestamp_ms).toBe('number');
  });

  it('defaults payload to an empty object when omitted', () => {
    usePlayerStore.setState({ sessionId: 'sess_123' });

    trackEvent('tab_switch');

    expect(apiPostMock.mock.calls[0][1].events[0].payload).toEqual({});
  });

  it('swallows a rejected request -- a dropped analytics event must never throw', async () => {
    usePlayerStore.setState({ sessionId: 'sess_123' });
    apiPostMock.mockRejectedValue(new Error('network down'));

    expect(() => trackEvent('tab_switch')).not.toThrow();
    // Let the rejected promise's .catch() settle before the test ends.
    await Promise.resolve().then(() => Promise.resolve());
  });
});
