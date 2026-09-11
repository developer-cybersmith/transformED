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

// S4-37 review finding (Scale & Load): neither bullet count nor title length is
// capped anywhere upstream (_MAX_SLIDE_BULLET_CHARS bounds a single bullet's own
// length, but nothing bounds how many bullets a slide has, or how long its title
// is). At the sidebar's narrow 25% width that can silently render into a cramped,
// heavily-wrapped column with no visual signal anything changed. Rather than wait
// on an upstream pipeline cap (a separate, backend decision), this is an explicit,
// surfaced degradation: past this threshold the sidebar switches to smaller text
// so more of the real content is visibly readable at once, instead of silently
// leaving it exactly as-is only more cramped.
const _DENSE_CONTENT_CHAR_THRESHOLD = 400;

function isDenseSlideContent(slide: Slide): boolean {
  const totalChars =
    slide.title.length + slide.bullets.reduce((sum, bullet) => sum + bullet.length, 0);
  return totalChars > _DENSE_CONTENT_CHAR_THRESHOLD;
}

// [DEV1-SPRINT2-PENDING] This depends on the real LessonPackage from Dev 1's
// package_builder (Story S2-11, not yet built). Do not build a parallel
// real-content path here -- this will be reconciled when Sprint 2 lands.
// Ping Dev 1 (developer1-cybersmith) before changing this shape.
export function SlideRenderer({ slide, isActive, jargon }: SlideRendererProps) {
  const hasImage = !!(slide.image_url ?? slide.fallback_image_url);
  // Density-based sizing only applies in the narrow 25% sidebar -- the full-width
  // (no-image) layout has 4x the room and was never the shape this gap was found in.
  const isDense = hasImage && isDenseSlideContent(slide);

  const textContent = (
    <>
      <h3
        className={[
          'font-serif font-semibold text-neutral-900 mb-3 text-wrap-balance',
          isDense ? 'text-lg mt-3' : 'text-xl mt-5',
        ].join(' ')}
      >
        {slide.title}
      </h3>
      <ul className={isDense ? 'space-y-1.5' : 'space-y-2.5'} role="list">
        {slide.bullets.map((bullet, i) => (
          <li
            key={i}
            data-testid="slide-bullet-item"
            className={[
              'flex items-start gap-2.5 text-neutral-600 min-w-0',
              isDense ? 'text-[13px] leading-snug' : 'text-[15px] leading-relaxed',
            ].join(' ')}
          >
            <span className="mt-2 w-1.5 h-1.5 rounded-full bg-[var(--accent-primary)] shrink-0" aria-hidden />
            <span className="min-w-0 break-words">
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
            role="group"
            aria-label="Slide illustration"
            className="w-3/4 h-full min-w-0 overflow-hidden"
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
              own overflow-y-auto instead. min-w-0 overrides the flex-item
              default of min-width:auto (its min-content width), which a long
              unbroken word/URL/jargon-term would otherwise use to force this
              panel past w-1/4 -- break-words on the bullet text (above) is
              the other half of that same fix. pb-24 reserves clearance at the
              bottom for CaptionOverlay (Player.tsx), a sibling absolutely
              positioned at max-h-[30%] across the full width -- without it,
              a full-height bullet list's last lines render underneath the
              caption bar with no way to scroll clear of it (review finding). */}
          <div
            data-testid="slide-text-sidebar"
            data-lenis-prevent
            role="group"
            aria-label="Slide content"
            className="w-1/4 h-full min-w-0 overflow-y-auto overscroll-y-contain p-5 pb-24 border-l border-neutral-100"
          >
            {textContent}
          </div>
        </>
      ) : (
        <div
          data-testid="slide-content-full"
          data-lenis-prevent
          className="flex-1 h-full overflow-y-auto overscroll-y-contain p-6 pb-24"
        >
          {textContent}
        </div>
      )}
    </div>
  );
}
