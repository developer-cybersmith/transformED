import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';

const { useAttentionMonitorMock } = vi.hoisted(() => ({
  useAttentionMonitorMock: vi.fn(),
}));

vi.mock('@/hooks/useAttentionMonitor', () => ({
  useAttentionMonitor: useAttentionMonitorMock,
}));

import { AttentionMonitor } from '@/components/player/AttentionMonitor';

beforeEach(() => {
  useAttentionMonitorMock.mockReset();
});

describe('AttentionMonitor (S3-02)', () => {
  it('renders nothing visible', () => {
    const { container } = render(<AttentionMonitor />);
    expect(container.firstChild).toBeNull();
  });

  it('invokes useAttentionMonitor exactly once per mount', () => {
    render(<AttentionMonitor />);
    expect(useAttentionMonitorMock).toHaveBeenCalledTimes(1);
  });

  it('AC-5a: neither this component nor the hook it depends on ever calls a raw network API outside the typed AttentionSignalMessage path', () => {
    // Source-level scan, not a rendered-DOM check -- a regression that sends
    // raw video/canvas data via fetch/XHR/axios would not appear in any DOM
    // assertion, so the guard must read the real files.
    const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
    const forbidden = /\bfetch\s*\(|XMLHttpRequest|axios/i;
    const sourceFiles = [
      resolve(SRC, 'components/player/AttentionMonitor.tsx'),
      resolve(SRC, 'hooks/useAttentionMonitor.ts'),
    ];
    for (const file of sourceFiles) {
      const contents = readFileSync(file, 'utf-8');
      expect(contents).not.toMatch(forbidden);
    }
  });

  it("AC-5a: never calls a raw WebSocket .send() -- the only send path is the typed wsSendAttentionSignal store function", () => {
    // AC-5's own text names this as part of the guard ("any ... WebSocket
    // `.send()` call whose argument isn't the typed shape") -- the previous
    // guard only checked fetch/XHR/axios, leaving this half unenforced
    // (review finding, confirmed by 4 layers). A `.send(` MEMBER call (dot
    // prefix) is what's forbidden; the sanctioned pattern is a bare
    // `send(msg)` call on the destructured store function, which this
    // regex does not match.
    const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
    const sourceFiles = [
      resolve(SRC, 'components/player/AttentionMonitor.tsx'),
      resolve(SRC, 'hooks/useAttentionMonitor.ts'),
    ];
    for (const file of sourceFiles) {
      const contents = readFileSync(file, 'utf-8');
      expect(contents).not.toMatch(/\.send\s*\(/);
    }
  });

  it('AC-5a: the hook never sends a raw video/canvas buffer -- every payload construction site is the typed AttentionSignalMessage shape', () => {
    const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
    const contents = readFileSync(resolve(SRC, 'hooks/useAttentionMonitor.ts'), 'utf-8');
    expect(contents).not.toMatch(/toDataURL|captureStream|ImageData\(/i);
  });

  it('never calls useLessonSocket a second time -- reads sendAttentionSignal via the player store instead, so no duplicate WebSocket connection is opened', () => {
    const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
    const contents = readFileSync(resolve(SRC, 'hooks/useAttentionMonitor.ts'), 'utf-8');
    expect(contents).not.toMatch(/useLessonSocket/);
  });
});
