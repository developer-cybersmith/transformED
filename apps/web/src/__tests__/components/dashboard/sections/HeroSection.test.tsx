import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HeroSection } from '@/components/dashboard/sections/HeroSection';

const { pushMock, useAuthMock } = vi.hoisted(() => ({
  pushMock: vi.fn(),
  useAuthMock: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: useAuthMock,
}));

beforeEach(() => {
  pushMock.mockReset();
  useAuthMock.mockReset();
  useAuthMock.mockReturnValue({ user: { full_name: 'Robert', email: 'robert@example.com' } });
});

describe('HeroSection', () => {
  it('"Resume Journey" navigates to the in-progress lesson when one is given', async () => {
    const user = userEvent.setup();
    render(<HeroSection continueLessonId="les_1" />);

    await user.click(screen.getByText('Resume Journey'));

    expect(pushMock).toHaveBeenCalledWith('/lesson/les_1');
  });

  it('"Resume Journey" falls back to /upload when there is no in-progress lesson', async () => {
    const user = userEvent.setup();
    render(<HeroSection />);

    await user.click(screen.getByText('Resume Journey'));

    expect(pushMock).toHaveBeenCalledWith('/upload');
  });

  it('"Upload PDF" always navigates to /upload', async () => {
    const user = userEvent.setup();
    render(<HeroSection continueLessonId="les_1" />);

    await user.click(screen.getByText('Upload PDF'));

    expect(pushMock).toHaveBeenCalledWith('/upload');
  });

  it('does not render a blank greeting for a leading-space full_name (review fix)', () => {
    useAuthMock.mockReturnValue({ user: { full_name: ' Robert', email: 'robert@example.com' } });
    render(<HeroSection />);

    expect(screen.getByText(/good evening, robert/i)).not.toBeNull();
  });

  it('falls back to "there" instead of a blank greeting when full_name is whitespace-only', () => {
    useAuthMock.mockReturnValue({ user: { full_name: '   ', email: 'robert@example.com' } });
    render(<HeroSection />);

    expect(screen.getByText(/good evening, there/i)).not.toBeNull();
  });
});
