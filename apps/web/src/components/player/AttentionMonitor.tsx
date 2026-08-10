'use client';

import { useAttentionMonitor } from '@/hooks/useAttentionMonitor';

/**
 * Self-contained, zero-props, renders nothing visible (S3-02) -- matches
 * TutorInterventionCard/CESIndicator/AttentionConsentModal's pattern. All
 * consent-gating, tutorState-gating, MediaPipe lifecycle, and signal
 * computation lives in useAttentionMonitor; this component is a thin mount
 * point so it can sit alongside its Sprint 3 siblings in Player.tsx's tree.
 */
export function AttentionMonitor() {
  useAttentionMonitor();
  return null;
}
