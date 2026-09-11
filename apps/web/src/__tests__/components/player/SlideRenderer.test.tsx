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

const fallbackOnlySlide: Slide = {
  ...mockSlide,
  slide_id: 'sl_fallback_only',
  image_url: null,
  fallback_image_url: 'https://cdn.hie.ai/mock/slide_0_fallback.jpg',
};

function makeSlide(overrides: Partial<Slide>): Slide {
  return { ...mockSlide, ...overrides };
}

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

describe('SlideRenderer — S4-37 layout', () => {
  it('renders 75/25 split panels when image is present', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    expect(screen.getByTestId('slide-image-panel')).toBeDefined();
    expect(screen.getByTestId('slide-text-sidebar')).toBeDefined();
    expect(screen.queryByTestId('slide-content-full')).toBeNull();
  });

  it('renders full-width layout when both image URLs are null', () => {
    render(<SlideRenderer slide={nullImageSlide} isActive jargon={[]} />);
    expect(screen.getByTestId('slide-content-full')).toBeDefined();
    expect(screen.queryByTestId('slide-image-panel')).toBeNull();
    expect(screen.queryByTestId('slide-text-sidebar')).toBeNull();
  });

  it('image panel does not have overflow-y-auto (image never scrolls)', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const panel = screen.getByTestId('slide-image-panel') as HTMLElement;
    expect(panel.className).not.toContain('overflow-y-auto');
  });

  it('text sidebar has overflow-y-auto (sidebar scrolls independently)', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const sidebar = screen.getByTestId('slide-text-sidebar') as HTMLElement;
    expect(sidebar.className).toContain('overflow-y-auto');
  });

  it('full-width content div has overflow-y-auto when no image', () => {
    render(<SlideRenderer slide={nullImageSlide} isActive jargon={[]} />);
    const full = screen.getByTestId('slide-content-full') as HTMLElement;
    expect(full.className).toContain('overflow-y-auto');
  });

  it('title and bullets render inside text sidebar when image present', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const sidebar = screen.getByTestId('slide-text-sidebar');
    expect(sidebar.querySelector('h3')).toBeDefined();
    expect(sidebar.querySelector('ul')).toBeDefined();
  });

  it('title and bullets render inside full-width div when no image', () => {
    render(<SlideRenderer slide={nullImageSlide} isActive jargon={[]} />);
    const full = screen.getByTestId('slide-content-full');
    expect(full.querySelector('h3')).toBeDefined();
    expect(full.querySelector('ul')).toBeDefined();
  });

  // P1 — AC3: image class regression guard
  it('slide image has h-full class and no max-h-[38vh] cap (AC3)', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const img = screen.getByTestId('slide-image') as HTMLElement;
    expect(img.className).toContain('h-full');
    expect(img.className).not.toContain('max-h-[38vh]');
  });

  // P2 — AC5: data-lenis-prevent attribute guards
  it('text sidebar has data-lenis-prevent attribute (AC5)', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const sidebar = screen.getByTestId('slide-text-sidebar');
    expect(sidebar.hasAttribute('data-lenis-prevent')).toBe(true);
  });

  it('full-width content div has data-lenis-prevent attribute (AC5)', () => {
    render(<SlideRenderer slide={nullImageSlide} isActive jargon={[]} />);
    const full = screen.getByTestId('slide-content-full');
    expect(full.hasAttribute('data-lenis-prevent')).toBe(true);
  });

  it('outer container does NOT have data-lenis-prevent — only scrollable children do (AC5)', () => {
    const { container } = render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const outer = container.firstElementChild as HTMLElement;
    expect(outer.hasAttribute('data-lenis-prevent')).toBe(false);
  });

  // P3 — AC1: width and flex class guards
  it('image panel has w-3/4 and text sidebar has w-1/4 class (AC1)', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const panel = screen.getByTestId('slide-image-panel') as HTMLElement;
    const sidebar = screen.getByTestId('slide-text-sidebar') as HTMLElement;
    expect(panel.className).toContain('w-3/4');
    expect(sidebar.className).toContain('w-1/4');
  });

  it('outer container has flex class for horizontal layout (AC1)', () => {
    const { container } = render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const outer = container.firstElementChild as HTMLElement;
    expect(outer.className).toContain('flex');
  });

  // P4 — AC4: overscroll-y-contain guard
  it('text sidebar has overscroll-y-contain class (AC4)', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const sidebar = screen.getByTestId('slide-text-sidebar') as HTMLElement;
    expect(sidebar.className).toContain('overscroll-y-contain');
  });

  // P5 — A11y: aria-labels on split panels
  it('image panel has aria-label for screen reader identification (a11y)', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const panel = screen.getByTestId('slide-image-panel') as HTMLElement;
    expect(panel.getAttribute('aria-label')).not.toBeNull();
  });

  it('text sidebar has aria-label for screen reader identification (a11y)', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const sidebar = screen.getByTestId('slide-text-sidebar') as HTMLElement;
    expect(sidebar.getAttribute('aria-label')).not.toBeNull();
  });

  // Review fix: aria-label on a bare <div> (role "generic") does not support
  // name-from-author -- role="group" makes the label actually reach the
  // accessibility tree, not just sit inertly in the DOM.
  it('review fix: image panel and text sidebar carry role="group" so aria-label is exposed to AT', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    expect(screen.getByTestId('slide-image-panel').getAttribute('role')).toBe('group');
    expect(screen.getByTestId('slide-text-sidebar').getAttribute('role')).toBe('group');
  });

  // Review fix (AC Completeness gap): regression guard for the exact defect
  // this story fixes -- object-cover would crop the infographic to fill the
  // panel instead of showing it in full.
  it('review fix: slide image uses object-contain, never object-cover (AC3)', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const img = screen.getByTestId('slide-image') as HTMLElement;
    expect(img.className).toContain('object-contain');
    expect(img.className).not.toContain('object-cover');
  });

  // Review fix (Test Coverage gap): AC1 says "has image_url OR fallback_image_url" --
  // only the fallback-only ("or" via the second operand) branch was untested.
  it('review fix: renders the 75/25 split when only fallback_image_url is set (AC1 "or" branch)', () => {
    render(<SlideRenderer slide={fallbackOnlySlide} isActive jargon={[]} />);
    expect(screen.getByTestId('slide-image-panel')).toBeDefined();
    expect(screen.getByTestId('slide-text-sidebar')).toBeDefined();
    expect(screen.queryByTestId('slide-content-full')).toBeNull();
  });

  // Review fix (Test Coverage + Blind Hunter): hasImage flipping on a re-render
  // swaps the fragment shape (two-div split <-> one-div full-width), which React
  // can only handle by unmounting/remounting -- confirm the layout actually
  // swaps correctly rather than leaving stale panels behind.
  it('review fix: layout swaps correctly when hasImage flips true -> false on re-render', () => {
    const { rerender } = render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    expect(screen.getByTestId('slide-image-panel')).toBeDefined();

    rerender(<SlideRenderer slide={nullImageSlide} isActive jargon={[]} />);

    expect(screen.queryByTestId('slide-image-panel')).toBeNull();
    expect(screen.queryByTestId('slide-text-sidebar')).toBeNull();
    expect(screen.getByTestId('slide-content-full')).toBeDefined();
    expect(screen.getByText('Defining AI')).toBeDefined();
  });

  it('review fix: layout swaps correctly when hasImage flips false -> true on re-render', () => {
    const { rerender } = render(<SlideRenderer slide={nullImageSlide} isActive jargon={[]} />);
    expect(screen.getByTestId('slide-content-full')).toBeDefined();

    rerender(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);

    expect(screen.queryByTestId('slide-content-full')).toBeNull();
    expect(screen.getByTestId('slide-image-panel')).toBeDefined();
    expect(screen.getByTestId('slide-text-sidebar')).toBeDefined();
  });

  // Review fix (Edge Case Hunter): CaptionOverlay (Player.tsx sibling, absolute
  // bottom-0, full width, max-h-[30%]) has no clearance reserved without this --
  // confirm the scrollable regions now reserve bottom padding for it.
  it('review fix: text sidebar and full-width content reserve bottom clearance for CaptionOverlay', () => {
    const { rerender } = render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    expect(screen.getByTestId('slide-text-sidebar').className).toContain('pb-24');

    rerender(<SlideRenderer slide={nullImageSlide} isActive jargon={[]} />);
    expect(screen.getByTestId('slide-content-full').className).toContain('pb-24');
  });

  // Review fix (Blind Hunter + Edge Case Hunter): min-w-0 + break-words guard
  // against a long unbroken token (URL/jargon term) forcing the sidebar past
  // its w-1/4 share via the flex-item default min-width:auto.
  it('review fix: image panel and text sidebar have min-w-0 to prevent flex overflow', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    expect(screen.getByTestId('slide-image-panel').className).toContain('min-w-0');
    expect(screen.getByTestId('slide-text-sidebar').className).toContain('min-w-0');
  });

  it('review fix: bullet text wraps long unbroken tokens instead of forcing overflow', () => {
    const longTokenSlide = makeSlide({ bullets: ['a'.repeat(150)] });
    render(<SlideRenderer slide={longTokenSlide} isActive jargon={[]} />);
    const bullet = screen.getByText('a'.repeat(150));
    expect(bullet.className).toContain('break-words');
  });
});

// ── Dense-content safety net (Story S4-37 review fix, Scale & Load finding) ─────
//
// Neither bullet count nor title length is capped upstream in the content
// pipeline (only a single bullet's own character length is). At the sidebar's
// narrow 25% width, real content near that per-bullet ceiling can silently
// render into a cramped, heavily-wrapped column with no visual signal anything
// changed. Past a combined-content-length threshold, the sidebar switches to
// smaller text so more of the real content is visibly readable -- an explicit,
// surfaced degradation rather than a silent one.
describe('SlideRenderer — dense content safety net', () => {
  it('uses default text sizing for a short, typical slide', () => {
    render(<SlideRenderer slide={mockSlide} isActive jargon={[]} />);
    const bullet = screen.getAllByTestId('slide-bullet-item')[0];
    expect(bullet.className).toContain('text-[15px]');
    expect(bullet.className).not.toContain('text-[13px]');
  });

  it('switches to smaller, denser text once combined title+bullet length exceeds the threshold', () => {
    // title (11 chars) + 3 bullets at 150 chars each = 461 chars > 400 threshold.
    const denseSlide = makeSlide({ bullets: ['b'.repeat(150), 'c'.repeat(150), 'd'.repeat(150)] });
    render(<SlideRenderer slide={denseSlide} isActive jargon={[]} />);
    const bullet = screen.getAllByTestId('slide-bullet-item')[0];
    expect(bullet.className).toContain('text-[13px]');
    expect(bullet.className).not.toContain('text-[15px]');
  });

  it('does not apply dense sizing to the full-width (no-image) layout even with the same long content', () => {
    // Same combined length as the dense case above, but no image -- full width
    // has 4x the room, so this was never the shape the gap was found in.
    const denseNoImageSlide = makeSlide({
      image_url: null,
      fallback_image_url: null,
      bullets: ['b'.repeat(150), 'c'.repeat(150), 'd'.repeat(150)],
    });
    render(<SlideRenderer slide={denseNoImageSlide} isActive jargon={[]} />);
    const bullet = screen.getAllByTestId('slide-bullet-item')[0];
    expect(bullet.className).toContain('text-[15px]');
  });

  it('applies dense sizing right at the boundary (401 chars dense, 400 chars not)', () => {
    // title "Defining AI" = 11 chars. One bullet of 389 chars -> 400 total (not dense).
    const atThreshold = makeSlide({ bullets: ['e'.repeat(389)] });
    const { rerender } = render(<SlideRenderer slide={atThreshold} isActive jargon={[]} />);
    expect(screen.getByTestId('slide-bullet-item').className).toContain('text-[15px]');

    // One bullet of 390 chars -> 401 total (dense).
    const overThreshold = makeSlide({ bullets: ['f'.repeat(390)] });
    rerender(<SlideRenderer slide={overThreshold} isActive jargon={[]} />);
    expect(screen.getByTestId('slide-bullet-item').className).toContain('text-[13px]');
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
      // Origin must match test/setup.ts's NEXT_PUBLIC_SUPABASE_URL for
      // parseSignedUrl's origin check (review finding) to accept this fixture.
      image_url:
        'http://localhost:54321/storage/v1/object/sign/lesson-images/lesson-1/slide-0.jpg?token=expired',
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

  it('attempts the automatic re-sign at most once for a real signed-url-shaped primary — a second error after falling back to fallback does not re-trigger (AC4, review fix)', async () => {
    // Test Coverage gap (review finding): the pre-existing "shows placeholder
    // when fallback also errors" test never used a signed-url-shaped
    // primary, so it could not distinguish "the guard worked" from "the URL
    // never matched the shape at all". This uses a real signed-url-shaped
    // primary and pins the network-call count.
    const signedSlide: Slide = {
      ...mockSlide,
      slide_id: 'sl_signed_guard',
      image_url: 'http://localhost:54321/storage/v1/object/sign/lesson-images/lesson-1/slide-guard.jpg?token=expired',
    };
    let signedUrlCallCount = 0;
    server.use(
      http.get(`${API_BASE}/media/signed-url`, () => {
        signedUrlCallCount += 1;
        return HttpResponse.json({ detail: 'Storage object not found' }, { status: 404 });
      }),
    );

    render(<SlideRenderer slide={signedSlide} isActive jargon={[]} />);
    fireEvent.error(screen.getByTestId('slide-image')); // primary errors -> real re-sign attempt (fails) -> fallback

    await waitFor(() => {
      expect((screen.getByTestId('slide-image') as HTMLImageElement).src).toContain('slide_0_fallback.jpg');
    });
    expect(signedUrlCallCount).toBe(1);

    fireEvent.error(screen.getByTestId('slide-image')); // fallback errors -> placeholder, no second attempt

    expect(screen.getByTestId('slide-image-placeholder')).toBeDefined();
    expect(signedUrlCallCount).toBe(1);
  });

  it('resets the attempt-guard when the SAME slide gets a genuinely new image_url (e.g. a content refresh) — the new asset gets its own automatic attempt (review fix)', async () => {
    const initialSlide: Slide = {
      ...mockSlide,
      slide_id: 'sl_refresh',
      image_url: 'http://localhost:54321/storage/v1/object/sign/lesson-images/lesson-1/before.jpg?token=old',
    };
    let signedUrlCallCount = 0;
    server.use(
      http.get(`${API_BASE}/media/signed-url`, () => {
        signedUrlCallCount += 1;
        return HttpResponse.json({ detail: 'Storage object not found' }, { status: 404 });
      }),
    );

    const { rerender } = render(<SlideRenderer slide={initialSlide} isActive jargon={[]} />);
    fireEvent.error(screen.getByTestId('slide-image'));

    await waitFor(() => {
      expect((screen.getByTestId('slide-image') as HTMLImageElement).src).toContain('slide_0_fallback.jpg');
    });
    expect(signedUrlCallCount).toBe(1);

    // Same slide_id, genuinely new image_url -- simulates a lesson content
    // refresh replacing this slide's image without SlideRenderer's own key
    // (slide_id) changing.
    const refreshedSlide: Slide = {
      ...initialSlide,
      image_url: 'http://localhost:54321/storage/v1/object/sign/lesson-images/lesson-1/after.jpg?token=new',
    };
    rerender(<SlideRenderer slide={refreshedSlide} isActive jargon={[]} />);
    fireEvent.error(screen.getByTestId('slide-image'));

    // Without the fix, the stale attemptedResignRef from "before.jpg" would
    // survive the rerender and this would skip straight to the fallback
    // with no second network call.
    await waitFor(() => {
      expect(signedUrlCallCount).toBe(2);
    });
  });
});
