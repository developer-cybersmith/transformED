import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SessionReport } from '@/components/reports/SessionReport';

const { useSessionReportMock } = vi.hoisted(() => ({
  useSessionReportMock: vi.fn(),
}));

vi.mock('@/hooks/useSessionReport', () => ({
  useSessionReport: useSessionReportMock,
}));

const FULL_REPORT = {
  session_id: 'sess_1',
  user_id: 'user_1',
  lesson_id: 'lesson_1',
  ces_score: 85,
  ces_breakdown: { quiz: 28.0, teachback: 20.0, behavioral: 0.0, head_pose: 0.0, blink: 0.0 },
  interventions_count: 2,
  quiz_score: 78.5,
  teachback_score: 90,
  duration_minutes: 42,
  completed_at: '2026-07-04T10:00:00Z',
};

beforeEach(() => {
  useSessionReportMock.mockReset();
});

describe('SessionReport', () => {
  it('shows a loading state while the report is in flight', () => {
    useSessionReportMock.mockReturnValue({ report: null, isLoading: true, error: undefined });

    render(<SessionReport sessionId="sess_1" />);

    expect(screen.getByTestId('session-report-loading')).not.toBeNull();
  });

  it('shows an error/empty state on fetch failure, with a link back to the dashboard', () => {
    useSessionReportMock.mockReturnValue({ report: null, isLoading: false, error: new Error('404') });

    render(<SessionReport sessionId="sess_1" />);

    expect(screen.getByTestId('session-report-error')).not.toBeNull();
    const link = screen.getByRole('link', { name: /dashboard/i });
    expect(link.getAttribute('href')).toBe('/dashboard');
  });

  it('renders quiz accuracy as a real percentage', () => {
    useSessionReportMock.mockReturnValue({ report: FULL_REPORT, isLoading: false, error: undefined });

    render(<SessionReport sessionId="sess_1" />);

    expect(screen.getByText(/78(\.5)?%/)).not.toBeNull();
  });

  it('never renders a raw CES or teach-back number — only descriptive labels', () => {
    useSessionReportMock.mockReturnValue({ report: FULL_REPORT, isLoading: false, error: undefined });

    const { container } = render(<SessionReport sessionId="sess_1" />);

    // The raw ces_score (85) and teachback_score (90) must never appear as visible numbers.
    expect(screen.queryByText('85')).toBeNull();
    expect(screen.queryByText('90')).toBeNull();
    expect(container.textContent).toMatch(/Highly Engaged/);
    expect(container.textContent).toMatch(/Strong grasp/);
  });

  it('shows friendly messaging when quiz_score and teachback_score are both null (zero-attempt session)', () => {
    useSessionReportMock.mockReturnValue({
      report: { ...FULL_REPORT, quiz_score: null, teachback_score: null },
      isLoading: false,
      error: undefined,
    });

    render(<SessionReport sessionId="sess_1" />);

    expect(screen.getByText(/No quiz questions this session/i)).not.toBeNull();
    expect(screen.getByText(/No teach-back this session/i)).not.toBeNull();
  });

  it('"Study Again" links to /lesson/{lesson_id} from the report response', () => {
    useSessionReportMock.mockReturnValue({ report: FULL_REPORT, isLoading: false, error: undefined });

    render(<SessionReport sessionId="sess_1" />);

    const link = screen.getByRole('link', { name: /study again/i });
    expect(link.getAttribute('href')).toBe('/lesson/lesson_1');
  });

  it('renders engagement summary (duration, interventions) without dumping raw field names', () => {
    useSessionReportMock.mockReturnValue({ report: FULL_REPORT, isLoading: false, error: undefined });

    const { container } = render(<SessionReport sessionId="sess_1" />);

    expect(container.textContent).toMatch(/42/);
    expect(container.textContent).not.toMatch(/duration_minutes/);
    expect(container.textContent).not.toMatch(/interventions_count/);
  });

  it('never renders "NaN minutes studied" for a non-finite duration_minutes', () => {
    useSessionReportMock.mockReturnValue({
      report: { ...FULL_REPORT, duration_minutes: NaN },
      isLoading: false,
      error: undefined,
    });

    const { container } = render(<SessionReport sessionId="sess_1" />);

    expect(container.textContent).not.toMatch(/NaN/);
  });

  it('never renders literal "Invalid Date" for a malformed completed_at', () => {
    useSessionReportMock.mockReturnValue({
      report: { ...FULL_REPORT, completed_at: 'not-a-real-date' },
      isLoading: false,
      error: undefined,
    });

    const { container } = render(<SessionReport sessionId="sess_1" />);

    expect(container.textContent).not.toMatch(/Invalid Date/);
  });
});
