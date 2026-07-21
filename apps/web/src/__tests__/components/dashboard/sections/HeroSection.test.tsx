import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HeroSection } from '@/components/dashboard/sections/HeroSection';

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: { full_name: 'Robert', email: 'robert@example.com' } }),
}));

beforeEach(() => {
  pushMock.mockReset();
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
});
