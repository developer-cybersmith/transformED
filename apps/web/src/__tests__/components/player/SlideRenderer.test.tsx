import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { API_BASE } from '@/test/handlers';
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

  it('renders no image element (not even a placeholder) when both image_url and fallback_image_url are null', () => {
    // Intentional design: skip the placeholder entirely rather than a blank
    // space-eating box — see SlideImage's early `return null` in SlideRenderer.tsx.
    render(<SlideRenderer slide={nullImageSlide} isActive jargon={[]} />);
    expect(screen.queryByTestId('slide-image-placeholder')).toBeNull();
    expect(screen.queryByTestId('slide-image')).toBeNull();
  });

  it('swaps to fallback_image_url on image error, after an automatic re-sign attempt fails (Story 2-45 -- no signed-url endpoint mocked here, so the attempt fails and falls through)', async () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const img = screen.getByTestId('slide-image') as HTMLImageElement;
    expect(img.src).toContain('slide_0.jpg');

    fireEvent.error(img);

    await waitFor(() => {
      expect((screen.getByTestId('slide-image') as HTMLImageElement).src).toContain('slide_0_fallback.jpg');
    });
  });

  it('shows placeholder when fallback also errors', async () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const img = screen.getByTestId('slide-image') as HTMLImageElement;

    fireEvent.error(img); // primary errors -> automatic re-sign attempt (fails, no endpoint mocked) -> fallback

    await waitFor(() => {
      expect((screen.getByTestId('slide-image') as HTMLImageElement).src).toContain('slide_0_fallback.jpg');
    });

    fireEvent.error(screen.getByTestId('slide-image')); // fallback errors -> placeholder (already attempted, no second re-sign)

    expect(screen.getByTestId('slide-image-placeholder')).toBeDefined();
    expect(screen.queryByTestId('slide-image')).toBeNull();
  });

  it('swaps in a fresh signed URL and does not fall back, when the automatic re-sign succeeds (Story 2-45)', async () => {
    const signedSlide: Slide = {
      ...mockSlide,
      slide_id: 'sl_signed',
      image_url:
        'https://project.supabase.co/storage/v1/object/sign/lesson-images/lesson-1/slide-0.jpg?token=expired',
    };
    server.use(
      http.get(`${API_BASE}/media/signed-url`, () =>
        HttpResponse.json({ signed_url: 'https://project.supabase.co/fresh-signed-jpg', expires_in: 3600 }),
      ),
    );

    render(<SlideRenderer slide={signedSlide} isActive jargon={[]} />);
    const img = screen.getByTestId('slide-image') as HTMLImageElement;

    fireEvent.error(img);

    await waitFor(() => {
      expect((screen.getByTestId('slide-image') as HTMLImageElement).src).toContain('fresh-signed-jpg');
    });
    expect(screen.queryByTestId('slide-image-placeholder')).toBeNull();
  });

  it('does not attempt a re-sign for an image_url that is not a Supabase signed-url shape', async () => {
    // mockSlide's default image_url does not match the signed-url shape.
    let signedUrlCallCount = 0;
    server.use(
      http.get(`${API_BASE}/media/signed-url`, () => {
        signedUrlCallCount += 1;
        return HttpResponse.json({ signed_url: 'https://project.supabase.co/fresh', expires_in: 3600 });
      }),
    );

    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    fireEvent.error(screen.getByTestId('slide-image'));

    await waitFor(() => {
      expect((screen.getByTestId('slide-image') as HTMLImageElement).src).toContain('slide_0_fallback.jpg');
    });
    expect(signedUrlCallCount).toBe(0);
  });
});
