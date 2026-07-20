import { describe, it, expect, vi, beforeEach } from 'vitest';

const { postMock, getMock } = vi.hoisted(() => ({
  postMock: vi.fn(),
  getMock: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  api: { post: postMock, get: getMock },
}));

import { onboardingService } from '@/services/onboarding.service';
import type { OnboardingAnswer, OnboardingResult, LearnerDNA } from '@/types/assessment';

beforeEach(() => {
  postMock.mockReset();
  getMock.mockReset();
});

const RESPONSES: OnboardingAnswer[] = [
  { question_id: 'c1', dimension: 'cognitive', selected_index: 2, selected_text: 'Option C' },
];

describe('onboardingService.submitOnboarding', () => {
  it('POSTs to assessment/onboarding/submit with { responses } and returns response.data', async () => {
    const result: OnboardingResult = {
      badge_labels: ['Pattern Thinker'],
      profile_text: 'Descriptive text. — Pursuant to DPDP Act 2023.',
      session_count: 0,
    };
    postMock.mockResolvedValue({ data: result });

    const data = await onboardingService.submitOnboarding(RESPONSES);

    expect(postMock).toHaveBeenCalledWith('assessment/onboarding/submit', { responses: RESPONSES });
    expect(data).toEqual(result);
  });

  it('propagates rejection (e.g. 409/422) instead of swallowing it', async () => {
    const error = { response: { status: 409 } };
    postMock.mockRejectedValue(error);

    await expect(onboardingService.submitOnboarding(RESPONSES)).rejects.toBe(error);
  });
});

describe('onboardingService.getLearnerDna', () => {
  it('GETs assessment/user/dna and returns response.data', async () => {
    const dna: LearnerDNA = {
      user_id: 'user_1',
      badge_labels: [],
      profile_text: null,
      session_count: 0,
      reassessment_due: false,
      last_updated: null,
    };
    getMock.mockResolvedValue({ data: dna });

    const data = await onboardingService.getLearnerDna();

    expect(getMock).toHaveBeenCalledWith('assessment/user/dna');
    expect(data).toEqual(dna);
  });

  it('propagates rejection (e.g. 404 = not onboarded) instead of swallowing it', async () => {
    const error = { response: { status: 404 } };
    getMock.mockRejectedValue(error);

    await expect(onboardingService.getLearnerDna()).rejects.toBe(error);
  });
});
