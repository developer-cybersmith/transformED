'use client';

import { useRef, useState } from 'react';
import type { Slide, JargonEntry } from '@hie/shared/types/lesson';
import { JargonHover } from './JargonHover';
import { refreshSignedUrl } from '@/lib/media/refreshSignedUrl';

// ── SlideImage ────────────────────────────────────────────────────────────────

interface SlideImageProps {
  imageUrl: string | null;
  fallbackUrl: string | null;
  title: string;
}

function SlideImage({ imageUrl, fallbackUrl, title }: SlideImageProps) {
  // Start from primary; fall back to fallback if primary is null
  const [src, setSrc] = useState<string | null>(imageUrl ?? fallbackUrl);
  const [failed, setFailed] = useState(false);
  // Story 2-45 AC3/AC4: at most one automatic re-sign attempt for the
  // primary imageUrl, ever, before falling back to fallbackUrl/placeholder.
  // A plain ref (not a Set) is enough — the parent keys this component by
  // imageUrl (review fix), so a genuinely new asset always gets a fresh
  // mount and a fresh ref, and one instance is only ever responsible for
  // exactly one primary URL for its whole lifetime.
  const attemptedResignRef = useRef(false);

  // No URLs at all — render nothing rather than a blank space-eating placeholder
  if (!imageUrl && !fallbackUrl) return null;

  if (failed || !src) {
    return (
      <div
        data-testid="slide-image-placeholder"
        className="w-full h-full bg-neutral-100 flex items-center justify-center"
      >
        <span className="text-neutral-400 text-sm">No image</span>
      </div>
    );
  }

  function handleImageError() {
    // Most failures here are a signed URL that expired while the student
    // was away, not a genuinely dead object — try one automatic re-sign of
    // the primary before falling through to the existing fallback chain.
    if (imageUrl && src === imageUrl && !attemptedResignRef.current) {
      attemptedResignRef.current = true;
      void refreshSignedUrl(imageUrl).then((fresh) => {
        if (fresh) {
          setSrc(fresh);
        } else if (fallbackUrl && fallbackUrl !== imageUrl) {
          setSrc(fallbackUrl);
        } else {
          setFailed(true);
        }
      });
      return;
    }
    if (fallbackUrl && src !== fallbackUrl) {
      setSrc(fallbackUrl);
    } else {
      setFailed(true);
    }
  }

  return (
    <img
      data-testid="slide-image"
      src={src}
      alt={title}
      // S4-37: image fills the 75% panel height without any fixed cap.
      // object-contain preserves full infographic without cropping.
      className="w-full h-full object-contain block"
      onError={handleImageError}
    />
  );
}

// ── SlideRenderer ─────────────────────────────────────────────────────────────

interface SlideRendererProps {
  slide: Slide;
  isActive: boolean;
  jargon: JargonEntry[];
}

// [DEV1-SPRINT2-PENDING] This depends on the real LessonPackage from Dev 1's
// package_builder (Story S2-11, not yet built). Do not build a parallel
// real-content path here -- this will be reconciled when Sprint 2 lands.
// Ping Dev 1 (developer1-cybersmith) before changing this shape.
export function SlideRenderer({ slide, isActive, jargon }: SlideRendererProps) {
  const hasImage = !!(slide.image_url ?? slide.fallback_image_url);

  const textContent = (
    <>
      <h3 className="font-serif text-xl font-semibold text-neutral-900 mt-5 mb-3 text-wrap-balance">
        {slide.title}
      </h3>
      <ul className="space-y-2.5" role="list">
        {slide.bullets.map((bullet, i) => (
          <li key={i} className="flex items-start gap-2.5 text-neutral-600 text-[15px] leading-relaxed">
            <span className="mt-2 w-1.5 h-1.5 rounded-full bg-[var(--accent-primary)] shrink-0" aria-hidden />
            <span>
              <JargonHover text={bullet} jargon={jargon} />
            </span>
          </li>
        ))}
      </ul>
    </>
  );

  return (
    <div
      className={[
        'absolute inset-0 flex transition-opacity duration-150',
        isActive ? 'opacity-100' : 'opacity-0 pointer-events-none',
      ].join(' ')}
      aria-hidden={isActive ? undefined : true}
    >
      {hasImage ? (
        <>
          <div
            data-testid="slide-image-panel"
            aria-label="Slide illustration"
            className="w-3/4 h-full overflow-hidden"
          >
            <SlideImage
              // Story 2-45 review fix: keyed on imageUrl so a content refresh that
              // swaps this slide's image (same slide_id, different image_url)
              // fully remounts SlideImage, resetting its src/failed state and
              // one-attempt re-sign guard for the genuinely new asset.
              key={slide.image_url ?? slide.fallback_image_url ?? 'none'}
              imageUrl={slide.image_url}
              fallbackUrl={slide.fallback_image_url}
              title={slide.title}
            />
          </div>
          {/* data-lenis-prevent: SmoothScroll.tsx's Lenis hijacks wheel events
              globally — this attribute tells it to delegate to the sidebar's
              own overflow-y-auto instead. */}
          <div
            data-testid="slide-text-sidebar"
            data-lenis-prevent
            aria-label="Slide content"
            className="w-1/4 h-full overflow-y-auto overscroll-y-contain p-5 border-l border-neutral-100"
          >
            {textContent}
          </div>
        </>
      ) : (
        <div
          data-testid="slide-content-full"
          data-lenis-prevent
          className="flex-1 h-full overflow-y-auto overscroll-y-contain p-6"
        >
          {textContent}
        </div>
      )}
    </div>
  );
}
