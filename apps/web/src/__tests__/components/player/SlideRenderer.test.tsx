import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { Slide, JargonEntry } from '@hie/shared/types/lesson';
import { SlideRenderer } from '@/components/player/SlideRenderer';

// ── Fixtures ─────────────────────────────────────────────────────────────────

const mockSlide: Slide = {
  slide_id: 'sl_0_0',
  title: 'Defining AI',
  bullets: [
    'AI simulates human intelligence',
    'First coined in 1956',
    'Narrow AI is task-specific systems',
  ],
  image_url: 'https://cdn.hie.ai/mock/slide_0.jpg',
  fallback_image_url: 'https://cdn.hie.ai/mock/slide_0_fallback.jpg',
};

const mockJargon: JargonEntry[] = [
  { term: 'Narrow AI', definition: 'An AI system designed to perform a specific task.' },
];

const nullImageSlide: Slide = {
  ...mockSlide,
  slide_id: 'sl_null',
  image_url: null,
  fallback_image_url: null,
};

// ── Tests ────────────────────────────────────────────────────────────────────

describe('SlideRenderer — content', () => {
  it('renders the slide title', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    expect(screen.getByText('Defining AI')).toBeDefined();
  });

  it('renders all bullets as list items', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const items = screen.getAllByRole('listitem');
    expect(items.length).toBe(3);
  });

  it('renders bullet text content', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    expect(screen.getByText(/AI simulates human intelligence/)).toBeDefined();
    expect(screen.getByText(/First coined in 1956/)).toBeDefined();
  });
});

describe('SlideRenderer — JargonHover integration', () => {
  it('wraps a matching jargon term in a highlighted span', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={mockJargon} />);
    // JargonHover renders the matched term inside a TooltipTrigger span with cursor-help class
    const jargonSpan = screen.getByText('Narrow AI');
    expect(jargonSpan.className).toContain('cursor-help');
  });

  it('does not highlight text when jargon list is empty', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    // "Narrow AI" should still be in the DOM as plain text, not in a styled span
    const el = screen.getByText(/Narrow AI is task-specific systems/);
    // The containing element should NOT have cursor-help (it's not a jargon span)
    expect(el.className).not.toContain('cursor-help');
  });
});

describe('SlideRenderer — isActive / visibility', () => {
  it('active slide has opacity-100 class', () => {
    const { container } = render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const outer = container.firstElementChild as HTMLElement;
    expect(outer.className).toContain('opacity-100');
    expect(outer.className).not.toContain('opacity-0');
  });

  it('inactive slide has opacity-0 class', () => {
    const { container } = render(<SlideRenderer slide={mockSlide} isActive={false} jargon={[]} />);
    const outer = container.firstElementChild as HTMLElement;
    expect(outer.className).toContain('opacity-0');
  });

  it('inactive slide has aria-hidden="true"', () => {
    const { container } = render(<SlideRenderer slide={mockSlide} isActive={false} jargon={[]} />);
    const outer = container.firstElementChild as HTMLElement;
    expect(outer.getAttribute('aria-hidden')).toBe('true');
  });

  it('active slide does NOT have aria-hidden', () => {
    const { container } = render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const outer = container.firstElementChild as HTMLElement;
    expect(outer.getAttribute('aria-hidden')).toBeNull();
  });

  it('inactive slide has pointer-events-none class', () => {
    const { container } = render(<SlideRenderer slide={mockSlide} isActive={false} jargon={[]} />);
    const outer = container.firstElementChild as HTMLElement;
    expect(outer.className).toContain('pointer-events-none');
  });
});

describe('SlideRenderer — image handling', () => {
  it('renders an img element when image_url is set', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    expect(screen.getByTestId('slide-image')).toBeDefined();
    expect(screen.queryByTestId('slide-image-placeholder')).toBeNull();
  });

  it('shows placeholder when both image_url and fallback_image_url are null', () => {
    render(<SlideRenderer slide={nullImageSlide} isActive jargon={[]} />);
    expect(screen.getByTestId('slide-image-placeholder')).toBeDefined();
    expect(screen.queryByTestId('slide-image')).toBeNull();
  });

  it('swaps to fallback_image_url on image error', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const img = screen.getByTestId('slide-image') as HTMLImageElement;
    expect(img.src).toContain('slide_0.jpg');

    fireEvent.error(img);

    expect(img.src).toContain('slide_0_fallback.jpg');
  });

  it('shows placeholder when fallback also errors', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const img = screen.getByTestId('slide-image') as HTMLImageElement;

    fireEvent.error(img);        // primary → fallback
    fireEvent.error(img);        // fallback → placeholder

    expect(screen.getByTestId('slide-image-placeholder')).toBeDefined();
    expect(screen.queryByTestId('slide-image')).toBeNull();
  });
});
