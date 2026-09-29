import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { PlayerControls } from '@/components/player/PlayerControls';
import { usePlayerStore } from '@/stores/player.machine';
import { mockLessonPackage } from '@/mocks/data/lessonPackage';

beforeEach(() => {
  usePlayerStore.getState().loadLesson(mockLessonPackage);
});

describe('PlayerControls — transport button', () => {
  it('shows Play when IDLE', () => {
    usePlayerStore.setState({ status: 'IDLE' });
    render(<PlayerControls />);
    expect(screen.getByRole('button', { name: 'Play' })).not.toBeNull();
  });

  it('shows Pause when PLAYING', () => {
    usePlayerStore.setState({ status: 'PLAYING' });
    render(<PlayerControls />);
    expect(screen.getByRole('button', { name: 'Pause' })).not.toBeNull();
  });

  it('shows Play (not Next) for a manual pause', () => {
    usePlayerStore.setState({ status: 'PAUSED', pauseReason: 'manual' });
    render(<PlayerControls />);
    expect(screen.getByRole('button', { name: 'Play' })).not.toBeNull();
  });

  it('Story 2-57 AC3: shows Next (not Play) during a slide-transition pause, and clicking it resumes', () => {
    usePlayerStore.setState({ status: 'PAUSED', pauseReason: 'slide-transition' });
    render(<PlayerControls />);

    const nextButton = screen.getByRole('button', { name: 'Next' });
    expect(nextButton).not.toBeNull();

    fireEvent.click(nextButton);

    expect(usePlayerStore.getState().status).toBe('PLAYING');
    expect(usePlayerStore.getState().pauseReason).toBeNull();
  });
});

// Story 2-65 / BR-10: the "skip pause for this segment" checkbox that used to
// live here moved into SlideTransitionPauseModal.test.tsx — see that file for
// its coverage (was only ever meaningful in-context, at the moment of an
// actual pause, not as a persistent control).

describe('PlayerControls — Ask Tutor button (Story 2-57 AC11)', () => {
  it('is enabled while PLAYING and pauses for intervention when clicked', () => {
    usePlayerStore.setState({ status: 'PLAYING' });
    render(<PlayerControls />);

    const askButton = screen.getByRole('button', { name: 'Ask Tutor' }) as HTMLButtonElement;
    expect(askButton.disabled).toBe(false);

    fireEvent.click(askButton);

    expect(usePlayerStore.getState().status).toBe('PAUSED');
    expect(usePlayerStore.getState().pauseReason).toBe('intervention');
  });

  it('is enabled during a slide-transition pause (review finding — must not require resuming first)', () => {
    usePlayerStore.setState({ status: 'PAUSED', pauseReason: 'slide-transition' });
    render(<PlayerControls />);

    const askButton = screen.getByRole('button', { name: 'Ask Tutor' }) as HTMLButtonElement;
    expect(askButton.disabled).toBe(false);

    fireEvent.click(askButton);

    expect(usePlayerStore.getState().pauseReason).toBe('intervention');
  });

  it('is disabled while IDLE', () => {
    usePlayerStore.setState({ status: 'IDLE' });
    render(<PlayerControls />);

    expect((screen.getByRole('button', { name: 'Ask Tutor' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('is disabled once the Ask Tutor panel is already open (pauseReason === intervention)', () => {
    usePlayerStore.setState({ status: 'PAUSED', pauseReason: 'intervention' });
    render(<PlayerControls />);

    expect((screen.getByRole('button', { name: 'Ask Tutor' }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('PlayerControls — speed control (default-playback-speed-0.8x)', () => {
  it('AC2: shows "1x" for the default real rate (0.8), not "0.8x"', () => {
    // loadLesson() in beforeEach already resets playbackRate to the default.
    render(<PlayerControls />);

    expect(usePlayerStore.getState().playbackRate).toBe(0.8);
    expect(screen.getByRole('button', { name: 'Playback speed 1×' })).not.toBeNull();
  });

  it('AC3: cycling speed steps through the real rates 0.8 -> 1.0 -> 1.2 -> 1.6 -> 0.6 -> 0.8, with labels 1x -> 1.25x -> 1.5x -> 2x -> 0.75x -> 1x', () => {
    render(<PlayerControls />);
    const button = screen.getByRole('button', { name: /Playback speed/ });

    const expected: { rate: number; label: string }[] = [
      { rate: 1.0, label: '1.25' },
      { rate: 1.2, label: '1.5' },
      { rate: 1.6, label: '2' },
      { rate: 0.6, label: '0.75' },
      { rate: 0.8, label: '1' }, // wraps back to the default
    ];

    for (const step of expected) {
      fireEvent.click(button);
      expect(usePlayerStore.getState().playbackRate).toBeCloseTo(step.rate, 10);
      expect(screen.getByRole('button', { name: `Playback speed ${step.label}×` })).not.toBeNull();
    }
  });
});
