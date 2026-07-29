import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { AvatarOverlay } from '@/components/player/AvatarOverlay';
import { usePlayerStore } from '@/stores/player.machine';
import { mockLessonPackage } from '@/mocks/data/lessonPackage';

let playMock: ReturnType<typeof vi.fn>;
const originalPlay = window.HTMLMediaElement.prototype.play;

beforeEach(() => {
  playMock = vi.fn().mockResolvedValue(undefined);
  window.HTMLMediaElement.prototype.play = playMock;
  usePlayerStore.getState().loadLesson(mockLessonPackage);
});

afterEach(() => {
  window.HTMLMediaElement.prototype.play = originalPlay;
});

describe('AvatarOverlay — no avatar fields configured (every real lesson today, AC-7)', () => {
  it('renders nothing at all when all 3 avatar fields are absent', () => {
    usePlayerStore.setState({ status: 'IDLE' });

    render(<AvatarOverlay lesson={mockLessonPackage} />);

    expect(screen.queryByTestId('avatar-intro')).toBeNull();
    expect(screen.queryByTestId('avatar-static')).toBeNull();
    expect(screen.queryByTestId('avatar-outro')).toBeNull();
  });

  it('does not call play() or block the store when no intro is configured', () => {
    usePlayerStore.setState({ status: 'IDLE' });

    render(<AvatarOverlay lesson={mockLessonPackage} />);

    expect(playMock).not.toHaveBeenCalled();
    expect(usePlayerStore.getState().status).toBe('IDLE'); // unchanged -- manual Play button still required
  });
});

describe('AvatarOverlay — intro', () => {
  const lessonWithIntro = { ...mockLessonPackage, avatar_intro_url: 'https://example.com/intro.mp4' };

  it('renders and attempts to play the intro while IDLE', () => {
    usePlayerStore.setState({ status: 'IDLE' });

    render(<AvatarOverlay lesson={lessonWithIntro} />);

    expect(screen.getByTestId('avatar-intro')).not.toBeNull();
    expect(playMock).toHaveBeenCalled();
  });

  it('starts the lesson (play()) and unmounts itself when the intro ends', () => {
    usePlayerStore.setState({ status: 'IDLE' });

    render(<AvatarOverlay lesson={lessonWithIntro} />);
    const video = screen.getByTestId('avatar-intro').querySelector('video')!;

    act(() => {
      video.dispatchEvent(new Event('ended'));
    });

    expect(usePlayerStore.getState().status).toBe('PLAYING');
    expect(screen.queryByTestId('avatar-intro')).toBeNull();
  });

  it('skips to the lesson gracefully when the intro asset errors', () => {
    usePlayerStore.setState({ status: 'IDLE' });

    render(<AvatarOverlay lesson={lessonWithIntro} />);
    const video = screen.getByTestId('avatar-intro').querySelector('video')!;

    act(() => {
      video.dispatchEvent(new Event('error'));
    });

    expect(usePlayerStore.getState().status).toBe('PLAYING');
    expect(screen.queryByTestId('avatar-intro')).toBeNull();
  });

  it('skips to the lesson gracefully when autoplay is blocked (play() rejects)', async () => {
    playMock.mockRejectedValue(new DOMException('blocked', 'NotAllowedError'));
    usePlayerStore.setState({ status: 'IDLE' });

    render(<AvatarOverlay lesson={lessonWithIntro} />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(usePlayerStore.getState().status).toBe('PLAYING');
    expect(screen.queryByTestId('avatar-intro')).toBeNull();
  });

  it('does not render the intro once status has moved past IDLE', () => {
    usePlayerStore.setState({ status: 'PLAYING' });

    render(<AvatarOverlay lesson={lessonWithIntro} />);

    expect(screen.queryByTestId('avatar-intro')).toBeNull();
  });
});

describe('AvatarOverlay — static image', () => {
  const lessonWithStatic = { ...mockLessonPackage, avatar_static_url: 'https://example.com/static.png' };

  it('shows the static avatar while PLAYING', () => {
    usePlayerStore.setState({ status: 'PLAYING' });

    render(<AvatarOverlay lesson={lessonWithStatic} />);

    const img = screen.getByTestId('avatar-static').querySelector('img');
    expect(img?.getAttribute('src')).toBe('https://example.com/static.png');
  });

  it('shows the static avatar while PAUSED and QUIZ too (lesson body, not just PLAYING)', () => {
    usePlayerStore.setState({ status: 'PAUSED' });
    const { rerender } = render(<AvatarOverlay lesson={lessonWithStatic} />);
    expect(screen.getByTestId('avatar-static')).not.toBeNull();

    act(() => {
      usePlayerStore.setState({ status: 'QUIZ' });
    });
    rerender(<AvatarOverlay lesson={lessonWithStatic} />);
    expect(screen.getByTestId('avatar-static')).not.toBeNull();
  });

  it('does NOT show the static avatar while IDLE', () => {
    usePlayerStore.setState({ status: 'IDLE' });

    render(<AvatarOverlay lesson={lessonWithStatic} />);

    expect(screen.queryByTestId('avatar-static')).toBeNull();
  });

  it('does NOT show the static avatar once ENDED', () => {
    usePlayerStore.setState({ status: 'ENDED' });

    render(<AvatarOverlay lesson={lessonWithStatic} />);

    expect(screen.queryByTestId('avatar-static')).toBeNull();
  });
});

describe('AvatarOverlay — outro', () => {
  const lessonWithOutro = { ...mockLessonPackage, avatar_outro_url: 'https://example.com/outro.mp4' };

  it('renders and attempts to play the outro once ENDED', () => {
    usePlayerStore.setState({ status: 'ENDED' });

    render(<AvatarOverlay lesson={lessonWithOutro} />);

    expect(screen.getByTestId('avatar-outro')).not.toBeNull();
    expect(playMock).toHaveBeenCalled();
  });

  it('unmounts once the outro ends, revealing whatever is underneath (Player.tsx\'s own ENDED screen)', () => {
    usePlayerStore.setState({ status: 'ENDED' });

    render(<AvatarOverlay lesson={lessonWithOutro} />);
    const video = screen.getByTestId('avatar-outro').querySelector('video')!;

    act(() => {
      video.dispatchEvent(new Event('ended'));
    });

    expect(screen.queryByTestId('avatar-outro')).toBeNull();
  });

  it('unmounts gracefully if the outro asset errors, instead of blocking the completion screen forever', () => {
    usePlayerStore.setState({ status: 'ENDED' });

    render(<AvatarOverlay lesson={lessonWithOutro} />);
    const video = screen.getByTestId('avatar-outro').querySelector('video')!;

    act(() => {
      video.dispatchEvent(new Event('error'));
    });

    expect(screen.queryByTestId('avatar-outro')).toBeNull();
  });

  it('unmounts gracefully if autoplay is blocked, instead of getting stuck forever', async () => {
    playMock.mockRejectedValue(new DOMException('blocked', 'NotAllowedError'));
    usePlayerStore.setState({ status: 'ENDED' });

    render(<AvatarOverlay lesson={lessonWithOutro} />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.queryByTestId('avatar-outro')).toBeNull();
  });

  it('does not render the outro before status is ENDED', () => {
    usePlayerStore.setState({ status: 'PLAYING' });

    render(<AvatarOverlay lesson={lessonWithOutro} />);

    expect(screen.queryByTestId('avatar-outro')).toBeNull();
  });
});

describe('AvatarOverlay — all 3 fields configured together', () => {
  const fullLesson = {
    ...mockLessonPackage,
    avatar_intro_url: 'https://example.com/intro.mp4',
    avatar_static_url: 'https://example.com/static.png',
    avatar_outro_url: 'https://example.com/outro.mp4',
  };

  it('shows only the intro while IDLE, not the static image', () => {
    usePlayerStore.setState({ status: 'IDLE' });

    render(<AvatarOverlay lesson={fullLesson} />);

    expect(screen.getByTestId('avatar-intro')).not.toBeNull();
    expect(screen.queryByTestId('avatar-static')).toBeNull();
  });

  it('shows only the static image while PLAYING, not intro or outro', () => {
    usePlayerStore.setState({ status: 'PLAYING' });

    render(<AvatarOverlay lesson={fullLesson} />);

    expect(screen.queryByTestId('avatar-intro')).toBeNull();
    expect(screen.getByTestId('avatar-static')).not.toBeNull();
    expect(screen.queryByTestId('avatar-outro')).toBeNull();
  });

  it('shows only the outro once ENDED, not the static image', () => {
    usePlayerStore.setState({ status: 'ENDED' });

    render(<AvatarOverlay lesson={fullLesson} />);

    expect(screen.queryByTestId('avatar-static')).toBeNull();
    expect(screen.getByTestId('avatar-outro')).not.toBeNull();
  });
});
