import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
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
    // AC-1: must explain webcam use, the 5-number-only claim, and that raw
    // video specifically never leaves the browser -- not just any sentence
    // containing "never" somewhere on the page.
    expect(screen.getByText(/webcam/i)).not.toBeNull();
    expect(screen.getByText(/five aggregate numbers/i)).not.toBeNull();
    expect(screen.getByText(/raw video never leaves your browser/i)).not.toBeNull();
    expect(screen.getByRole('button', { name: /accept/i })).not.toBeNull();
    expect(screen.getByRole('button', { name: /decline/i })).not.toBeNull();
  });

  it('never references any camera-capture or MediaPipe API anywhere in the actual source of this component or the hook it depends on (AC-4 ordering guard)', () => {
    // Source-level scan, not a rendered-DOM check -- a regression that adds
    // a camera call inside useAttentionConsent's effect (which renders
    // nothing into this component's markup) would not appear in any DOM
    // assertion, so the guard must read the real files.
    const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
    // Matches actual usage (a call, an import, instantiation) — not prose
    // mentions in comments like "makes no camera/MediaPipe call".
    const forbidden = /getUserMedia\s*\(|from\s+['"]@mediapipe|new\s+FaceLandmarker/i;
    const sourceFiles = [
      resolve(SRC, 'components/player/AttentionConsentModal.tsx'),
      resolve(SRC, 'hooks/useAttentionConsent.ts'),
    ];
    for (const file of sourceFiles) {
      const contents = readFileSync(file, 'utf-8');
      expect(contents).not.toMatch(forbidden);
    }
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
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<AttentionConsentModal />);

    await userEvent.click(screen.getByRole('button', { name: /accept/i }));

    // Failure surfaced, not swallowed silently -- and actually logged (AC-7).
    expect(screen.getByRole('alert')).not.toBeNull();
    expect(consoleErrorSpy).toHaveBeenCalled();
    // A way forward exists — clicking it dismisses without granting consent.
    const continueButton = screen.getByRole('button', { name: /continue/i });
    await userEvent.click(continueButton);
    expect(decline).toHaveBeenCalledTimes(1);
    consoleErrorSpy.mockRestore();
  });

  it('retrying after a failure clears the failure alert once accept() succeeds', async () => {
    const accept = vi.fn().mockRejectedValueOnce(new Error('404')).mockResolvedValueOnce(undefined);
    useAttentionConsentMock.mockReturnValue(baseHookReturn({ accept }));
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<AttentionConsentModal />);

    await userEvent.click(screen.getByRole('button', { name: /accept/i }));
    expect(screen.getByRole('alert')).not.toBeNull();

    await userEvent.click(screen.getByRole('button', { name: /retry/i }));

    expect(accept).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('alert')).toBeNull();
    consoleErrorSpy.mockRestore();
  });
});
