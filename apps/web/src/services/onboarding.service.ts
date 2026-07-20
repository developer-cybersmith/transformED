import { api } from '@/lib/api';
import type { LearnerDNA, OnboardingAnswer, OnboardingResult } from '@/types/assessment';

export const onboardingService = {
    submitOnboarding: (responses: OnboardingAnswer[]) =>
        api.post<OnboardingResult>('assessment/onboarding/submit', { responses }).then((r) => r.data),

    getLearnerDna: () =>
        api.get<LearnerDNA>('assessment/user/dna').then((r) => r.data),
};
