import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import Footer from '@/components/layout/Footer';

describe('Footer', () => {
  it('never mentions IQ, EQ, or SQ — CLAUDE.md bans this terminology anywhere in the product', () => {
    const { container } = render(<Footer />);
    const text = container.textContent ?? '';
    for (const banned of [/\bIQ\b/i, /\bEQ\b/i, /\bSQ\b/i]) {
      expect(text).not.toMatch(banned);
    }
  });
});
