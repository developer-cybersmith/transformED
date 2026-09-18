import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SlideTransitionPauseModal } from '@/components/player/SlideTransitionPauseModal';
import { usePlayerStore } from '@/stores/player.machine';
import { mockLessonPackage } from '@/mocks/data/lessonPackage';

beforeEach(() => {
  usePlayerStore.getState().loadLesson(mockLessonPackage);
  usePlayerStore.setState({
    status: 'PAUSED',
    pauseReason: 'slide-transition',
    skipTransitionPauseForSegment: false,
  });
});

describe('SlideTransitionPauseModal (Story 2-65 / BR-10)', () => {
  it('renders as a centered overlay card, matching the AskTutorPanel/TeachBackModal pattern', () => {
    render(<SlideTransitionPauseModal />);
    expect(screen.getByTestId('slide-transition-pause-modal')).not.toBeNull();
  });

  it('AC2: Next button calls play() and resumes playback', () => {
    render(<SlideTransitionPauseModal />);

    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    expect(usePlayerStore.getState().status).toBe('PLAYING');
    expect(usePlayerStore.getState().pauseReason).toBeNull();
  });

  it('AC3: skip-pause-for-segment checkbox reflects and toggles the existing store field', () => {
    render(<SlideTransitionPauseModal />);

    const checkbox = screen.getByRole('checkbox', { name: /skip pause for this segment/i }) as HTMLInputElement;
    expect(checkbox.checked).toBe(false);

    fireEvent.click(checkbox);

    expect(usePlayerStore.getState().skipTransitionPauseForSegment).toBe(true);
    expect(checkbox.checked).toBe(true);
  });

  it('AC4: Ask Tutor button pauses for intervention', () => {
    render(<SlideTransitionPauseModal />);

    fireEvent.click(screen.getByRole('button', { name: 'Ask Tutor' }));

    expect(usePlayerStore.getState().status).toBe('PAUSED');
    expect(usePlayerStore.getState().pauseReason).toBe('intervention');
  });

  it('AC7: has no timer element or numeric countdown of any kind', () => {
    const { container } = render(<SlideTransitionPauseModal />);

    expect(screen.queryByRole('timer')).toBeNull();
    expect(container.textContent).not.toMatch(/\d+:\d{2}/);
    expect(container.textContent).not.toMatch(/\d+\s*(s|sec|seconds)\b/i);
  });
});
