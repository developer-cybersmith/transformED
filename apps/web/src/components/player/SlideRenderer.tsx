'use client';

import { useState } from 'react';
import type { Slide, JargonEntry } from '@hie/shared/types/lesson';
import { JargonHover } from './JargonHover';

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

  // No URLs at all — render nothing rather than a blank space-eating placeholder
  if (!imageUrl && !fallbackUrl) return null;

  if (failed || !src) {
    return (
      <div
        data-testid="slide-image-placeholder"
        className="w-full aspect-video rounded-xl bg-neutral-800/50 flex items-center justify-center"
      >
        <span className="text-neutral-600 text-sm">No image</span>
      </div>
    );
  }

  return (
    <img
      data-testid="slide-image"
      src={src}
      alt={title}
      className="w-full aspect-video object-cover rounded-xl"
      onError={() => {
        if (fallbackUrl && src !== fallbackUrl) {
          setSrc(fallbackUrl);
        } else {
          setFailed(true);
        }
      }}
    />
  );
}

// ── SlideRenderer ─────────────────────────────────────────────────────────────

interface SlideRendererProps {
  slide: Slide;
  isActive: boolean;
  jargon: JargonEntry[];
}

export function SlideRenderer({ slide, isActive, jargon }: SlideRendererProps) {
  return (
    <div
      className={[
        'absolute inset-0 overflow-y-auto overscroll-y-contain p-6 transition-opacity duration-150',
        isActive ? 'opacity-100' : 'opacity-0 pointer-events-none',
      ].join(' ')}
      aria-hidden={isActive ? undefined : true}
    >
      <SlideImage
        imageUrl={slide.image_url}
        fallbackUrl={slide.fallback_image_url}
        title={slide.title}
      />

      <h3 className="text-xl font-semibold text-white mt-5 mb-3 text-wrap-balance">
        {slide.title}
      </h3>

      <ul className="space-y-2.5" role="list">
        {slide.bullets.map((bullet, i) => (
          <li key={i} className="flex items-start gap-2.5 text-neutral-300 text-[15px] leading-relaxed">
            <span className="mt-2 w-1.5 h-1.5 rounded-full bg-[var(--accent-primary)] shrink-0" aria-hidden />
            <span>
              <JargonHover text={bullet} jargon={jargon} />
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
