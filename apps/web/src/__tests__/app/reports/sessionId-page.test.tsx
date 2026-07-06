import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

const { sessionReportMock } = vi.hoisted(() => ({
  sessionReportMock: vi.fn(),
}));

vi.mock('@/components/reports/SessionReport', () => ({
  SessionReport: (props: { sessionId: string }) => {
    sessionReportMock(props);
    return <div data-testid="session-report-stub">{props.sessionId}</div>;
  },
}));

import SessionReportPage from '@/app/reports/[sessionId]/page';

beforeEach(() => {
  sessionReportMock.mockReset();
});

describe('SessionReportPage', () => {
  it('unwraps the async sessionId route param and passes it to SessionReport', async () => {
    const element = await SessionReportPage({ params: Promise.resolve({ sessionId: 'sess_abc123' }) });
    render(element);

    expect(sessionReportMock).toHaveBeenCalledWith({ sessionId: 'sess_abc123' });
    expect(screen.getByTestId('session-report-stub').textContent).toBe('sess_abc123');
  });
});
