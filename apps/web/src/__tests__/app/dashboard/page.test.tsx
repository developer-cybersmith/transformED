import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

const { useDashboardMock, useAuthMock } = vi.hoisted(() => ({
  useDashboardMock: vi.fn(),
  useAuthMock: vi.fn(),
}));

vi.mock('@/hooks/useDashboard', () => ({
  useDashboard: useDashboardMock,
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: useAuthMock,
}));

vi.mock('@/services/onboarding.service', () => ({
  onboardingService: { getLearnerDna: vi.fn().mockResolvedValue({ reassessment_due: false }) },
}));

import DashboardPage from '@/app/(dashboard)/dashboard/page';

beforeEach(() => {
  useDashboardMock.mockReset();
  useAuthMock.mockReset();
  useAuthMock.mockReturnValue({ user: { full_name: 'Robert', email: 'robert@example.com' } });
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

  it('shows an empty-state message in place of the collapsed sections when the user has zero lessons (S4-10)', () => {
    useDashboardMock.mockReturnValue({
      data: { continueLearning: null, recentLessons: [], learningPulse: undefined },
      error: undefined,
      isLoading: false,
    });

    render(<DashboardPage />);

    expect(screen.getByText(/no lessons yet/i)).not.toBeNull();
  });

  it('does not show the zero-lessons empty-state once the user has a lesson', () => {
    useDashboardMock.mockReturnValue({
      data: {
        continueLearning: null,
        recentLessons: [{ lesson_id: 'l1', status: 'ready', title: 'Intro to Thermodynamics' }],
        learningPulse: undefined,
      },
      error: undefined,
      isLoading: false,
    });

    render(<DashboardPage />);

    expect(screen.queryByText(/no lessons yet/i)).toBeNull();
  });

  it('does not show the zero-lessons empty-state while still loading', () => {
    useDashboardMock.mockReturnValue({ data: null, error: undefined, isLoading: true });

    render(<DashboardPage />);

    expect(screen.queryByText(/no lessons yet/i)).toBeNull();
  });

  it('does not show the zero-lessons empty-state when the fetch has failed', () => {
    useDashboardMock.mockReturnValue({ data: null, error: new Error('boom'), isLoading: false });

    render(<DashboardPage />);

    expect(screen.queryByText(/no lessons yet/i)).toBeNull();
  });

  it('does not show the zero-lessons empty-state when the user has a continueLearning lesson, even with an empty recentLessons list', () => {
    useDashboardMock.mockReturnValue({
      data: {
        continueLearning: { lesson_id: 'l1', status: 'ready', title: 'Intro to Thermodynamics' },
        recentLessons: [],
        learningPulse: undefined,
      },
      error: undefined,
      isLoading: false,
    });

    render(<DashboardPage />);

    expect(screen.queryByText(/no lessons yet/i)).toBeNull();
  });

  it('does not show the zero-lessons empty-state before auth has resolved, even though useDashboard reports isLoading: false for its null SWR key (S4-10)', () => {
    // useDashboard keys its SWR call off `user` -- a null key means SWR is not
    // fetching at all (isLoading: false), NOT "confirmed no data". Without a
    // separate `user` check, a returning user with real lessons would see this
    // flash "No lessons yet" during the brief pre-auth window (review finding).
    useAuthMock.mockReturnValue({ user: null });
    useDashboardMock.mockReturnValue({ data: null, error: undefined, isLoading: false });

    render(<DashboardPage />);

    expect(screen.queryByText(/no lessons yet/i)).toBeNull();
  });
});
