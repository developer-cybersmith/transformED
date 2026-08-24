import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LessonError from '@/app/lesson/[id]/error';

describe('LessonError', () => {
  it('logs the error and renders the branded error state (S4-11 — not Next.js\'s default unstyled error page)', () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const error = new Error('boom');

    render(<LessonError error={error} reset={vi.fn()} />);

    expect(screen.getByText('Something went wrong')).not.toBeNull();
    expect(consoleErrorSpy).toHaveBeenCalledWith('Lesson route error:', error);
    consoleErrorSpy.mockRestore();
  });

  it('calls reset when "Try again" is clicked', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const reset = vi.fn();
    const user = userEvent.setup();

    render(<LessonError error={new Error('boom')} reset={reset} />);
    await user.click(screen.getByRole('button', { name: /try again/i }));

    expect(reset).toHaveBeenCalledTimes(1);
  });

  it('links back to the dashboard, for the case where retrying in place won\'t help', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});

    render(<LessonError error={new Error('boom')} reset={vi.fn()} />);

    const link = screen.getByRole('link', { name: /return to dashboard/i });
    expect(link.getAttribute('href')).toBe('/dashboard');
  });
});
