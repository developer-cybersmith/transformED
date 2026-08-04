import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

const { useDashboardMock } = vi.hoisted(() => ({ useDashboardMock: vi.fn() }));

vi.mock('@/hooks/useDashboard', () => ({
  useDashboard: useDashboardMock,
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: { full_name: 'Robert', email: 'robert@example.com' } }),
}));

vi.mock('@/services/onboarding.service', () => ({
  onboardingService: { getLearnerDna: vi.fn().mockResolvedValue({ reassessment_due: false }) },
}));

import DashboardPage from '@/app/(dashboard)/dashboard/page';

beforeEach(() => {
  useDashboardMock.mockReset();
});

describe('DashboardPage', () => {
  it('shows a loading state instead of a flash of empty sections while the real fetch is in flight', () => {
    useDashboardMock.mockReturnValue({ data: null, error: undefined, isLoading: true });

    render(<DashboardPage />);

    expect(screen.getByText('Loading your dashboard...')).not.toBeNull();
    expect(screen.queryByText('Recently Added Lessons')).toBeNull();
  });

  it('renders the dashboard sections once data has loaded', () => {
    useDashboardMock.mockReturnValue({
      data: { continueLearning: null, recentLessons: [], learningPulse: undefined },
      error: undefined,
      isLoading: false,
    });

    render(<DashboardPage />);

    expect(screen.queryByText('Loading your dashboard...')).toBeNull();
  });

  it('shows the error banner instead of the loading state when the fetch has failed', () => {
    useDashboardMock.mockReturnValue({ data: null, error: new Error('boom'), isLoading: false });

    render(<DashboardPage />);

    expect(screen.getByText(/couldn't load some of your dashboard data/)).not.toBeNull();
    expect(screen.queryByText('Loading your dashboard...')).toBeNull();
  });
});
