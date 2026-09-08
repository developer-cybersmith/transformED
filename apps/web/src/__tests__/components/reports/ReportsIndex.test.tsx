import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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

  // ── Follow-up (same story, same-day feedback): filter tabs, recency
  // grouping, "Load more" -- a flat wall of every session at once was
  // reported as overwhelming. ─────────────────────────────────────────────

  describe('filter tabs', () => {
    it('shows a count per tab and defaults to "All"', () => {
      useSessionReportsMock.mockReturnValue({
        sessions: [COMPLETED_SESSION, IN_PROGRESS_SESSION],
        isLoading: false,
        error: undefined,
      });
      render(<ReportsIndex />);

      expect(screen.getByRole('tab', { name: 'All (2)' }).getAttribute('aria-selected')).toBe('true');
      expect(screen.getByRole('tab', { name: 'Completed (1)' })).not.toBeNull();
      expect(screen.getByRole('tab', { name: 'In Progress (1)' })).not.toBeNull();
    });

    it('narrows the grid to only completed sessions when the Completed tab is selected', async () => {
      useSessionReportsMock.mockReturnValue({
        sessions: [COMPLETED_SESSION, IN_PROGRESS_SESSION],
        isLoading: false,
        error: undefined,
      });
      render(<ReportsIndex />);

      await userEvent.click(screen.getByRole('tab', { name: 'Completed (1)' }));

      expect(screen.getByTestId('session-card-sess_1')).not.toBeNull();
      expect(screen.queryByTestId('session-card-sess_2')).toBeNull();
    });

    it('shows a friendly "no match" message, not an empty grid, when a filter matches zero sessions', async () => {
      useSessionReportsMock.mockReturnValue({
        sessions: [COMPLETED_SESSION],
        isLoading: false,
        error: undefined,
      });
      render(<ReportsIndex />);

      await userEvent.click(screen.getByRole('tab', { name: 'In Progress (0)' }));

      expect(screen.getByTestId('reports-index-no-match')).not.toBeNull();
      expect(screen.queryByTestId('session-card-sess_1')).toBeNull();
    });
  });

  describe('recency grouping', () => {
    const now = Date.now();
    const RECENT_SESSION: SessionSummary = {
      ...COMPLETED_SESSION,
      session_id: 'sess_recent',
      started_at: new Date(now - 1000 * 60 * 60).toISOString(), // 1 hour ago
    };
    const OLD_SESSION: SessionSummary = {
      ...COMPLETED_SESSION,
      session_id: 'sess_old',
      started_at: new Date(now - 1000 * 60 * 60 * 24 * 30).toISOString(), // 30 days ago
    };

    it('shows a "This Week" heading, not "Earlier", for a session started within the last 7 days', () => {
      useSessionReportsMock.mockReturnValue({ sessions: [RECENT_SESSION], isLoading: false, error: undefined });
      render(<ReportsIndex />);

      expect(screen.getByText('This Week')).not.toBeNull();
      expect(screen.queryByText('Earlier')).toBeNull();
    });

    it('shows an "Earlier" heading, not "This Week", for a session started over 7 days ago', () => {
      useSessionReportsMock.mockReturnValue({ sessions: [OLD_SESSION], isLoading: false, error: undefined });
      render(<ReportsIndex />);

      expect(screen.getByText('Earlier')).not.toBeNull();
      expect(screen.queryByText('This Week')).toBeNull();
    });

    it('shows both headings when sessions span both windows', () => {
      useSessionReportsMock.mockReturnValue({
        sessions: [RECENT_SESSION, OLD_SESSION],
        isLoading: false,
        error: undefined,
      });
      render(<ReportsIndex />);

      expect(screen.getByText('This Week')).not.toBeNull();
      expect(screen.getByText('Earlier')).not.toBeNull();
    });
  });

  describe('"Load more"', () => {
    const MANY_SESSIONS: SessionSummary[] = Array.from({ length: 10 }, (_, i) => ({
      ...COMPLETED_SESSION,
      session_id: `sess_${i}`,
      started_at: new Date(Date.now() - i * 1000).toISOString(),
    }));

    it('shows only the first 9 sessions and a "Load more" button when there are more than 9', () => {
      useSessionReportsMock.mockReturnValue({ sessions: MANY_SESSIONS, isLoading: false, error: undefined });
      render(<ReportsIndex />);

      expect(screen.getAllByTestId(/^session-card-/)).toHaveLength(9);
      expect(screen.getByRole('button', { name: /load more/i })).not.toBeNull();
    });

    it('reveals the rest and hides the button once "Load more" is clicked', async () => {
      useSessionReportsMock.mockReturnValue({ sessions: MANY_SESSIONS, isLoading: false, error: undefined });
      render(<ReportsIndex />);

      await userEvent.click(screen.getByRole('button', { name: /load more/i }));

      for (const s of MANY_SESSIONS) {
        expect(screen.getByTestId(`session-card-${s.session_id}`)).not.toBeNull();
      }
      expect(screen.queryByRole('button', { name: /load more/i })).toBeNull();
    });

    it('does not show a "Load more" button when there are 9 or fewer sessions', () => {
      useSessionReportsMock.mockReturnValue({
        sessions: [COMPLETED_SESSION, IN_PROGRESS_SESSION],
        isLoading: false,
        error: undefined,
      });
      render(<ReportsIndex />);

      expect(screen.queryByRole('button', { name: /load more/i })).toBeNull();
    });
  });
});
