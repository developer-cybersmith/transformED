import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

const { getDashboardMock } = vi.hoisted(() => ({ getDashboardMock: vi.fn() }));

vi.mock('@/services/dashboard.service', () => ({
  dashboardService: { getDashboard: getDashboardMock },
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import { DashboardDataFetcher } from '@/app/(dashboard)/dashboard/page';

const MOCK_PULSE = { streak: 5, hoursThisWeek: 4.2, strongestTopic: 'Web Security' };

beforeEach(() => {
  getDashboardMock.mockReset();
});

describe('DashboardDataFetcher (dashboard server component)', () => {
  it('renders the full dashboard on success', async () => {
    getDashboardMock.mockResolvedValue({
      success: true,
      data: {
        continueLearning: null,
        learningPulse: MOCK_PULSE,
        recentLessons: [],
        recentLessonsError: null,
      },
      message: 'ok',
    });

    render(await DashboardDataFetcher());

    expect(screen.getByText('Quick Actions')).not.toBeNull();
  });

  it('still renders the dashboard (not a blank error page) when recentLessonsError is set — non-blocking', async () => {
    getDashboardMock.mockResolvedValue({
      success: true,
      data: {
        continueLearning: null,
        learningPulse: MOCK_PULSE,
        recentLessons: [],
        recentLessonsError: "We couldn't load your recent lessons right now.",
      },
      message: 'ok',
    });

    render(await DashboardDataFetcher());

    expect(screen.getByText('Quick Actions')).not.toBeNull();
    expect(screen.getByText("We couldn't load your recent lessons right now.")).not.toBeNull();
  });
});
