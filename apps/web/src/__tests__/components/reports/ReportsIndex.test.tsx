import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ReportsIndex } from '@/components/reports/ReportsIndex';
import type { SessionSummary } from '@/types/assessment';

const { useSessionReportsMock } = vi.hoisted(() => ({
  useSessionReportsMock: vi.fn(),
}));

vi.mock('@/hooks/useSessionReports', () => ({
  useSessionReports: useSessionReportsMock,
}));

const COMPLETED_SESSION: SessionSummary = {
  session_id: 'sess_1',
  lesson_id: 'lesson_1',
  lesson_title: 'Photosynthesis',
  tier: 'T1',
  tier_label: 'Full-Depth',
  started_at: '2026-09-01T10:00:00Z',
  ended_at: '2026-09-01T10:20:00Z',
  completed: true,
  ces_score: 82,
};

const IN_PROGRESS_SESSION: SessionSummary = {
  session_id: 'sess_2',
  lesson_id: 'lesson_2',
  lesson_title: null,
  tier: 'T3',
  tier_label: 'Refresher',
  started_at: '2026-09-02T09:00:00Z',
  ended_at: null,
  completed: false,
  ces_score: null,
};

beforeEach(() => {
  useSessionReportsMock.mockReset();
});

describe('ReportsIndex — Story 2-58 / BR-7', () => {
  it('shows a loading skeleton while fetching', () => {
    useSessionReportsMock.mockReturnValue({ sessions: [], isLoading: true, error: undefined });
    render(<ReportsIndex />);

    expect(screen.getByTestId('reports-index-loading')).not.toBeNull();
  });

  it('shows an error state, with a link back to the dashboard, on fetch failure', () => {
    useSessionReportsMock.mockReturnValue({
      sessions: [],
      isLoading: false,
      error: new Error('network'),
    });
    render(<ReportsIndex />);

    expect(screen.getByTestId('reports-index-error')).not.toBeNull();
    expect(screen.getByRole('link', { name: /back to dashboard/i }).getAttribute('href')).toBe(
      '/dashboard'
    );
  });

  it('shows a friendly empty state, with a link back to the dashboard, when the student has no sessions yet', () => {
    useSessionReportsMock.mockReturnValue({ sessions: [], isLoading: false, error: undefined });
    render(<ReportsIndex />);

    expect(screen.getByTestId('reports-index-empty')).not.toBeNull();
    expect(screen.getByRole('link', { name: /back to dashboard/i }).getAttribute('href')).toBe(
      '/dashboard'
    );
  });

  it('renders one card per session, each linking to its own /reports/{session_id}', () => {
    useSessionReportsMock.mockReturnValue({
      sessions: [COMPLETED_SESSION, IN_PROGRESS_SESSION],
      isLoading: false,
      error: undefined,
    });
    render(<ReportsIndex />);

    const completedCard = screen.getByTestId('session-card-sess_1');
    expect(completedCard.getAttribute('href')).toBe('/reports/sess_1');
    expect(completedCard.textContent).toContain('Photosynthesis');
    expect(completedCard.textContent).toContain('Full-Depth');

    const inProgressCard = screen.getByTestId('session-card-sess_2');
    expect(inProgressCard.getAttribute('href')).toBe('/reports/sess_2');
    // No title on the backend row -- must not render blank or crash.
    expect(inProgressCard.textContent).toContain('Untitled Lesson');
    expect(inProgressCard.textContent).toContain('In progress');
  });

  it('never renders a numeric CES score for an in-progress (null-score) session', () => {
    useSessionReportsMock.mockReturnValue({
      sessions: [IN_PROGRESS_SESSION],
      isLoading: false,
      error: undefined,
    });
    render(<ReportsIndex />);

    expect(screen.queryByText(/\/100/)).toBeNull();
  });
});
