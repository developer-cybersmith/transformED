import { api } from '@/lib/api';

/**
 * Body of `PATCH /api/users/consent` (S3-01). This endpoint does not exist
 * yet — D29, owned by Dev 3, tracked in docs/DEFECT-REGISTER.md. Verified
 * absent on both `main` and Dev 3's own unmerged Sprint 3 branch as of this
 * story's baseline. Calls to this service will 404 until he ships the
 * `user_consents` writer; `useAttentionConsent`'s accept() path degrades
 * gracefully on that failure rather than trapping the student (AC-7).
 */
export interface SetAttentionConsentPayload {
    attention_consent: boolean;
}

export const usersService = {
    setAttentionConsent: async (consent: boolean): Promise<void> => {
        const body: SetAttentionConsentPayload = { attention_consent: consent };
        await api.patch('users/consent', body);
    },
};
