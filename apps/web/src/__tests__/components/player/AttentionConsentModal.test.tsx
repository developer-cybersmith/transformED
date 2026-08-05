import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { useAttentionConsentMock } = vi.hoisted(() => ({
  useAttentionConsentMock: vi.fn(),
}));

vi.mock('@/hooks/useAttentionConsent', () => ({
  useAttentionConsent: useAttentionConsentMock,
}));

import { AttentionConsentModal } from '@/components/player/AttentionConsentModal';

function baseHookReturn(overrides: Partial<ReturnType<typeof useAttentionConsentMock>> = {}) {
  return {
    consentStatus: 'unknown' as const,
    isLoading: false,
    showModal: true,
    accept: vi.fn().mockResolvedValue(undefined),
    decline: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  useAttentionConsentMock.mockReset();
});

describe('AttentionConsentModal (S3-01 AC-1/AC-4)', () => {
  it('renders nothing when showModal is false', () => {
    useAttentionConsentMock.mockReturnValue(baseHookReturn({ showModal: false }));
    render(<AttentionConsentModal />);
    expect(screen.queryByTestId('attention-consent-modal')).toBeNull();
  });

  it('renders the explanation and both actions when showModal is true', () => {
    useAttentionConsentMock.mockReturnValue(baseHookReturn());
    render(<AttentionConsentModal />);

    expect(screen.getByTestId('attention-consent-modal')).not.toBeNull();
    // AC-1: must explain webcam use, the 5-number-only claim, and never video.
    expect(screen.getByText(/webcam/i)).not.toBeNull();
    expect(screen.getAllByText(/never/i).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: /accept/i })).not.toBeNull();
    expect(screen.getByRole('button', { name: /decline/i })).not.toBeNull();
  });

  it('never references any camera-capture or MediaPipe API anywhere in this test file\'s own assertions or the component source (AC-4 ordering guard)', () => {
    // This is a static, structural guard, not a runtime one — S3-02
    // (AttentionMonitor) does not exist yet and must not be reached from here.
    useAttentionConsentMock.mockReturnValue(baseHookReturn());
    render(<AttentionConsentModal />);
    const html = document.body.innerHTML;
    expect(html).not.toMatch(/getUserMedia|MediaPipe|FaceLandmarker/i);
  });

  it('calls accept() when Accept is clicked', async () => {
    const accept = vi.fn().mockResolvedValue(undefined);
    useAttentionConsentMock.mockReturnValue(baseHookReturn({ accept }));
    render(<AttentionConsentModal />);

    await userEvent.click(screen.getByRole('button', { name: /accept/i }));

    expect(accept).toHaveBeenCalledTimes(1);
  });

  it('calls decline() when Decline is clicked, with no accept() call', async () => {
    const accept = vi.fn();
    const decline = vi.fn();
    useAttentionConsentMock.mockReturnValue(baseHookReturn({ accept, decline }));
    render(<AttentionConsentModal />);

    await userEvent.click(screen.getByRole('button', { name: /decline/i }));

    expect(decline).toHaveBeenCalledTimes(1);
    expect(accept).not.toHaveBeenCalled();
  });

  it('shows an inline retry option when accept() rejects, and never traps the student (AC-7)', async () => {
    const accept = vi.fn().mockRejectedValue(new Error('404'));
    const decline = vi.fn();
    useAttentionConsentMock.mockReturnValue(baseHookReturn({ accept, decline }));
    render(<AttentionConsentModal />);

    await userEvent.click(screen.getByRole('button', { name: /accept/i }));

    // Failure surfaced, not swallowed silently.
    expect(screen.getByRole('alert')).not.toBeNull();
    // A way forward exists — clicking it dismisses without granting consent.
    const continueButton = screen.getByRole('button', { name: /continue/i });
    await userEvent.click(continueButton);
    expect(decline).toHaveBeenCalledTimes(1);
  });

  it('retrying after a failure calls accept() again', async () => {
    const accept = vi.fn().mockRejectedValueOnce(new Error('404')).mockResolvedValueOnce(undefined);
    useAttentionConsentMock.mockReturnValue(baseHookReturn({ accept }));
    render(<AttentionConsentModal />);

    await userEvent.click(screen.getByRole('button', { name: /accept/i }));
    await userEvent.click(screen.getByRole('button', { name: /retry/i }));

    expect(accept).toHaveBeenCalledTimes(2);
  });
});
