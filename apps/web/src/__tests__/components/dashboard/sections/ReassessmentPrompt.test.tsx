import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ReassessmentPrompt } from '@/components/dashboard/sections/ReassessmentPrompt';
import type { LearnerDNA } from '@/types/assessment';

const { pushMock, getLearnerDnaMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  getLearnerDnaMock: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock('@/services/onboarding.service', () => ({
  onboardingService: {
    getLearnerDna: getLearnerDnaMock,
  },
}));

const DUE_AT_10: LearnerDNA = {
  user_id: 'user_1',
  badge_labels: ['Goal-Oriented'],
  profile_text: 'Existing profile. — Pursuant to DPDP Act 2023.',
  session_count: 10,
  reassessment_due: true,
  last_updated: '2026-07-01T00:00:00Z',
};

const NOT_DUE: LearnerDNA = {
  ...DUE_AT_10,
  session_count: 5,
  reassessment_due: false,
};

const FETCH_ERROR = { isAxiosError: true, response: { status: 500 } };

beforeEach(() => {
  pushMock.mockReset();
  getLearnerDnaMock.mockReset();
  window.localStorage.clear();
});

describe('ReassessmentPrompt', () => {
  it('renders the prompt when reassessment_due is true', async () => {
    getLearnerDnaMock.mockResolvedValueOnce(DUE_AT_10);

    render(<ReassessmentPrompt />);

    await waitFor(() => expect(screen.getByText(/update my profile/i)).not.toBeNull());
  });

  it('renders nothing when reassessment_due is false', async () => {
    getLearnerDnaMock.mockResolvedValueOnce(NOT_DUE);

    const { container } = render(<ReassessmentPrompt />);

    await waitFor(() => expect(getLearnerDnaMock).toHaveBeenCalledTimes(1));
    expect(container.textContent).toBe('');
  });

  it('renders nothing when the DNA fetch fails', async () => {
    getLearnerDnaMock.mockRejectedValueOnce(FETCH_ERROR);

    const { container } = render(<ReassessmentPrompt />);

    await waitFor(() => expect(getLearnerDnaMock).toHaveBeenCalledTimes(1));
    expect(container.textContent).toBe('');
  });

  it('renders nothing while the fetch is still pending', () => {
    getLearnerDnaMock.mockReturnValueOnce(new Promise(() => {}));

    const { container } = render(<ReassessmentPrompt />);

    expect(container.textContent).toBe('');
  });

  it('the CTA navigates to /onboarding', async () => {
    getLearnerDnaMock.mockResolvedValueOnce(DUE_AT_10);
    const user = userEvent.setup();

    render(<ReassessmentPrompt />);

    await waitFor(() => expect(screen.getByText(/update my profile/i)).not.toBeNull());
    await user.click(screen.getByText(/update my profile/i));

    expect(pushMock).toHaveBeenCalledWith('/onboarding');
  });

  it('dismissing hides the prompt and persists across a remount for the same session_count', async () => {
    getLearnerDnaMock.mockResolvedValueOnce(DUE_AT_10);
    const user = userEvent.setup();

    const { container, unmount } = render(<ReassessmentPrompt />);
    await waitFor(() => expect(screen.getByText(/update my profile/i)).not.toBeNull());

    await user.click(screen.getByLabelText(/dismiss/i));
    expect(container.textContent).toBe('');

    unmount();
    getLearnerDnaMock.mockResolvedValueOnce(DUE_AT_10);
    const { container: container2 } = render(<ReassessmentPrompt />);

    await waitFor(() => expect(getLearnerDnaMock).toHaveBeenCalledTimes(2));
    expect(container2.textContent).toBe('');
  });

  it('a dismissal at session_count 10 does NOT suppress a later prompt at session_count 20', async () => {
    getLearnerDnaMock.mockResolvedValueOnce(DUE_AT_10);
    const user = userEvent.setup();

    const { unmount } = render(<ReassessmentPrompt />);
    await waitFor(() => expect(screen.getByText(/update my profile/i)).not.toBeNull());
    await user.click(screen.getByLabelText(/dismiss/i));
    unmount();

    const DUE_AT_20: LearnerDNA = { ...DUE_AT_10, session_count: 20 };
    getLearnerDnaMock.mockResolvedValueOnce(DUE_AT_20);
    render(<ReassessmentPrompt />);

    await waitFor(() => expect(screen.getByText(/update my profile/i)).not.toBeNull());
  });
});
