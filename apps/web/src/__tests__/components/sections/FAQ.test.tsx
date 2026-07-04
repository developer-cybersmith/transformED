import { describe, it, expect, beforeAll } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import FAQ from '@/components/sections/FAQ';

// framer-motion's whileInView uses IntersectionObserver internally
beforeAll(() => {
  global.IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof IntersectionObserver;
});

describe('FAQ accordion accessibility', () => {
  it('each toggle button has aria-expanded reflecting its open/closed state', async () => {
    const user = userEvent.setup();
    render(<FAQ />);

    const firstQuestion = screen.getByText('What kind of PDFs can I upload?');
    const button = firstQuestion.closest('button')!;
    expect(button.getAttribute('aria-expanded')).toBe('false');

    await user.click(button);

    expect(button.getAttribute('aria-expanded')).toBe('true');
  });

  it('the toggle button has aria-controls pointing at the answer panel\'s id', async () => {
    const user = userEvent.setup();
    render(<FAQ />);

    const firstQuestion = screen.getByText('What kind of PDFs can I upload?');
    const button = firstQuestion.closest('button')!;
    await user.click(button);

    const panelId = button.getAttribute('aria-controls');
    expect(panelId).toBeTruthy();
    expect(document.getElementById(panelId!)).not.toBeNull();
  });

  it('the answer panel has role="region" once open', async () => {
    const user = userEvent.setup();
    render(<FAQ />);

    await user.click(screen.getByText('What kind of PDFs can I upload?'));

    const answer = screen.getByText(/Textbooks, lecture notes/);
    const region = answer.closest('[role="region"]');
    expect(region).not.toBeNull();
  });
});
