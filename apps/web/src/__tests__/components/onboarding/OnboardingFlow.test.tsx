import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { OnboardingFlow } from '@/components/onboarding/OnboardingFlow';
import { QUESTIONS } from '@/components/onboarding/questions';
import type { OnboardingResult, LearnerDNA } from '@/types/assessment';

const { pushMock, submitOnboardingMock, getLearnerDnaMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  submitOnboardingMock: vi.fn(),
  getLearnerDnaMock: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock('@/services/onboarding.service', () => ({
  onboardingService: {
    submitOnboarding: submitOnboardingMock,
    getLearnerDna: getLearnerDnaMock,
  },
}));

const RESULT: OnboardingResult = {
  badge_labels: ['Pattern Thinker'],
  profile_text: 'Descriptive text. — Pursuant to DPDP Act 2023.',
  session_count: 0,
};

const EXISTING_DNA: LearnerDNA = {
  user_id: 'user_1',
  badge_labels: ['Goal-Oriented'],
  profile_text: 'Existing profile. — Pursuant to DPDP Act 2023.',
  session_count: 2,
  reassessment_due: false,
  last_updated: '2026-06-01T00:00:00Z',
};

const REASSESSMENT_DUE_DNA: LearnerDNA = {
  ...EXISTING_DNA,
  session_count: 10,
  reassessment_due: true,
};

// isAxiosError: true is required — OnboardingFlow uses axios.isAxiosError(), not duck-typing.
const NOT_ONBOARDED = { isAxiosError: true, response: { status: 404 } };
const UNAUTHENTICATED = { isAxiosError: true, response: { status: 401 } };
const ALREADY_SUBMITTED = { isAxiosError: true, response: { status: 409 } };
const VALIDATION_ERROR = { isAxiosError: true, response: { status: 422, data: { detail: 'Invalid submission.' } } };
const SERVER_ERROR = { isAxiosError: true, response: { status: 500 } };

async function acknowledgeDisclaimer(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => expect(screen.getByText(/not a clinical assessment/i)).not.toBeNull());
  await user.click(screen.getByText('I Understand, Begin Assessment'));
}

async function answerQuestion(user: ReturnType<typeof userEvent.setup>, index: number, isLast: boolean) {
  const q = QUESTIONS[index];
  await waitFor(() => expect(screen.getByText(q.text)).not.toBeNull());
  await user.click(screen.getByText(q.options[0]));
  await user.click(screen.getByText(isLast ? 'Complete Assessment' : 'Next'));
}

async function answerAllQuestions(user: ReturnType<typeof userEvent.setup>) {
  for (let i = 0; i < QUESTIONS.length; i++) {
    await answerQuestion(user, i, i === QUESTIONS.length - 1);
  }
}

beforeEach(() => {
  pushMock.mockReset();
  submitOnboardingMock.mockReset();
  getLearnerDnaMock.mockReset();
  window.sessionStorage.clear();
});

describe('OnboardingFlow', () => {
  it('skips straight to /dashboard if the user has already onboarded (GET dna resolves 200 on mount)', async () => {
    getLearnerDnaMock.mockResolvedValueOnce(EXISTING_DNA);

    render(<OnboardingFlow />);

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith('/dashboard'));
    expect(screen.queryByText(/not a clinical assessment/i)).toBeNull();
  });

  it('proceeds into the disclaimer/questions flow instead of redirecting when reassessment_due is true', async () => {
    getLearnerDnaMock.mockResolvedValueOnce(REASSESSMENT_DUE_DNA);
    const user = userEvent.setup();

    render(<OnboardingFlow />);

    await waitFor(() => expect(screen.getByText(/not a clinical assessment/i)).not.toBeNull());
    expect(pushMock).not.toHaveBeenCalledWith('/dashboard');

    await user.click(screen.getByText('I Understand, Begin Assessment'));
    expect(screen.getByText(QUESTIONS[0].text)).not.toBeNull();
  });

  it('does NOT resume stale persisted progress from a different reassessment session_count', async () => {
    window.sessionStorage.setItem(
      'onboarding_progress_v1',
      JSON.stringify({ current: 3, answers: { [QUESTIONS[0].id]: 0 }, disclaimerAcknowledged: true, dueSessionCount: 10 })
    );
    getLearnerDnaMock.mockResolvedValueOnce({ ...REASSESSMENT_DUE_DNA, session_count: 20 });

    render(<OnboardingFlow />);

    await waitFor(() => expect(screen.getByText(/not a clinical assessment/i)).not.toBeNull());
  });

  it('resumes persisted progress when it matches the current reassessment session_count', async () => {
    window.sessionStorage.setItem(
      'onboarding_progress_v1',
      JSON.stringify({ current: 3, answers: { [QUESTIONS[0].id]: 0 }, disclaimerAcknowledged: true, dueSessionCount: 10 })
    );
    getLearnerDnaMock.mockResolvedValueOnce(REASSESSMENT_DUE_DNA);

    render(<OnboardingFlow />);

    await waitFor(() => expect(screen.getByText(QUESTIONS[3].text)).not.toBeNull());
  });

  it('redirects to /signin if the mount-time check returns 401 (expired session)', async () => {
    getLearnerDnaMock.mockRejectedValueOnce(UNAUTHENTICATED);

    render(<OnboardingFlow />);

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith('/signin'));
    expect(screen.queryByText(/not a clinical assessment/i)).toBeNull();
  });

  it('shows the disclaimer and blocks question 1 until acknowledged (GET dna 404 on mount = not onboarded)', async () => {
    getLearnerDnaMock.mockRejectedValueOnce(NOT_ONBOARDED);
    const user = userEvent.setup();

    render(<OnboardingFlow />);

    await waitFor(() => expect(screen.getByText(/not a clinical assessment/i)).not.toBeNull());
    expect(screen.queryByText(QUESTIONS[0].text)).toBeNull();

    await user.click(screen.getByText('I Understand, Begin Assessment'));
    expect(screen.getByText(QUESTIONS[0].text)).not.toBeNull();
  });

  it('fails open into the flow on an unexpected mount error (e.g. 500), not just on 404', async () => {
    getLearnerDnaMock.mockRejectedValueOnce(SERVER_ERROR);

    render(<OnboardingFlow />);

    await waitFor(() => expect(screen.getByText(/not a clinical assessment/i)).not.toBeNull());
  });

  it('submits all 20 responses in the correct batched shape and shows the DNA result', async () => {
    getLearnerDnaMock.mockRejectedValueOnce(NOT_ONBOARDED);
    submitOnboardingMock.mockResolvedValueOnce(RESULT);
    const user = userEvent.setup();

    render(<OnboardingFlow />);
    await acknowledgeDisclaimer(user);
    await answerAllQuestions(user);

    await waitFor(() => expect(submitOnboardingMock).toHaveBeenCalledTimes(1));
    const responses = submitOnboardingMock.mock.calls[0][0];
    expect(responses).toHaveLength(20);
    expect(responses[0]).toEqual({
      question_id: QUESTIONS[0].id,
      dimension: QUESTIONS[0].dimension,
      selected_index: 0,
      selected_text: QUESTIONS[0].options[0],
    });

    await waitFor(() => expect(screen.getByText('Pattern Thinker')).not.toBeNull());
    expect(screen.getByText(RESULT.profile_text)).not.toBeNull();
  }, 15000);

  it('on 409 (already submitted), fetches existing DNA and shows the result instead of an error', async () => {
    getLearnerDnaMock.mockRejectedValueOnce(NOT_ONBOARDED); // mount check
    submitOnboardingMock.mockRejectedValueOnce(ALREADY_SUBMITTED);
    getLearnerDnaMock.mockResolvedValueOnce(EXISTING_DNA); // post-409 fetch
    const user = userEvent.setup();

    render(<OnboardingFlow />);
    await acknowledgeDisclaimer(user);
    await answerAllQuestions(user);

    await waitFor(() => expect(screen.getByText('Goal-Oriented')).not.toBeNull());
    expect(screen.getByText(EXISTING_DNA.profile_text as string)).not.toBeNull();
  }, 15000);

  it('on 409 where the follow-up DNA fetch also fails, offers "Continue to Dashboard" instead of an infinite Retry loop', async () => {
    getLearnerDnaMock.mockRejectedValueOnce(NOT_ONBOARDED); // mount check
    submitOnboardingMock.mockRejectedValueOnce(ALREADY_SUBMITTED);
    getLearnerDnaMock.mockRejectedValueOnce(SERVER_ERROR); // post-409 fetch also fails
    const user = userEvent.setup();

    render(<OnboardingFlow />);
    await acknowledgeDisclaimer(user);
    await answerAllQuestions(user);

    await waitFor(() => expect(screen.getByText(/already completed onboarding/i)).not.toBeNull());
    expect(screen.queryByText('Retry')).toBeNull();

    await user.click(screen.getByText('Continue to Dashboard'));
    expect(pushMock).toHaveBeenCalledWith('/dashboard');
  }, 15000);

  it('redirects to /signin if the session expires (401) at final submit', async () => {
    getLearnerDnaMock.mockRejectedValueOnce(NOT_ONBOARDED);
    submitOnboardingMock.mockRejectedValueOnce(UNAUTHENTICATED);
    const user = userEvent.setup();

    render(<OnboardingFlow />);
    await acknowledgeDisclaimer(user);
    await answerAllQuestions(user);

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith('/signin'));
  }, 15000);

  it('on 422, shows a retry option without losing collected answers', async () => {
    getLearnerDnaMock.mockRejectedValueOnce(NOT_ONBOARDED);
    submitOnboardingMock.mockRejectedValueOnce(VALIDATION_ERROR);
    submitOnboardingMock.mockResolvedValueOnce(RESULT);
    const user = userEvent.setup();

    render(<OnboardingFlow />);
    await acknowledgeDisclaimer(user);
    await answerAllQuestions(user);

    await waitFor(() => expect(screen.getByText('Invalid submission.')).not.toBeNull());
    await user.click(screen.getByText('Retry'));

    await waitFor(() => expect(submitOnboardingMock).toHaveBeenCalledTimes(2));
    const secondAttemptResponses = submitOnboardingMock.mock.calls[1][0];
    expect(secondAttemptResponses).toHaveLength(20);
    expect(secondAttemptResponses[0].selected_index).toBe(0);
  }, 15000);

  it('Back returns to the previous question with its prior answer still selected, and is disabled on question 1', async () => {
    getLearnerDnaMock.mockRejectedValueOnce(NOT_ONBOARDED);
    const user = userEvent.setup();

    render(<OnboardingFlow />);
    await acknowledgeDisclaimer(user);

    expect(screen.getByText('Back').closest('button')).toHaveProperty('disabled', true);

    await answerQuestion(user, 0, false);
    await waitFor(() => expect(screen.getByText(QUESTIONS[1].text)).not.toBeNull());

    await user.click(screen.getByText('Back'));

    await waitFor(() => expect(screen.getByText(QUESTIONS[0].text)).not.toBeNull());
    expect(screen.getByText(QUESTIONS[0].options[0]).closest('button')?.getAttribute('aria-checked')).toBe('true');
  });

  it('persists progress to sessionStorage and resumes on remount instead of restarting from question 1', async () => {
    getLearnerDnaMock.mockRejectedValueOnce(NOT_ONBOARDED);
    const user = userEvent.setup();

    const { unmount } = render(<OnboardingFlow />);
    await acknowledgeDisclaimer(user);
    await answerQuestion(user, 0, false);
    await answerQuestion(user, 1, false);
    await waitFor(() => expect(screen.getByText(QUESTIONS[2].text)).not.toBeNull());

    unmount();

    getLearnerDnaMock.mockRejectedValueOnce(NOT_ONBOARDED);
    render(<OnboardingFlow />);

    await waitFor(() => expect(screen.getByText(QUESTIONS[2].text)).not.toBeNull());
    expect(screen.queryByText(/not a clinical assessment/i)).toBeNull();
  });

  it('clears persisted progress once the assessment is submitted successfully', async () => {
    getLearnerDnaMock.mockRejectedValueOnce(NOT_ONBOARDED);
    submitOnboardingMock.mockResolvedValueOnce(RESULT);
    const user = userEvent.setup();

    render(<OnboardingFlow />);
    await acknowledgeDisclaimer(user);
    await answerAllQuestions(user);

    await waitFor(() => expect(window.sessionStorage.getItem('onboarding_progress_v1')).toBeNull());
  }, 15000);
});
