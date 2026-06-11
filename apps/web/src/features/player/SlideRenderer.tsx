'use client'

import Image from 'next/image'
import { useState } from 'react'
import type { Slide, JargonEntry } from '@transformed/shared/types/lesson'
import { JargonHover } from './JargonHover'

interface SlideRendererProps {
  slide: Slide
  jargon: JargonEntry[]
}

function highlightJargon(text: string, jargon: JargonEntry[]): React.ReactNode {
  if (!jargon.length) return text

  // Build a regex that matches any jargon term (case-insensitive, whole-word)
  const escaped = jargon.map((j) => j.term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const pattern = new RegExp(`\\b(${escaped.join('|')})\\b`, 'gi')

  const parts = text.split(pattern)
  return parts.map((part, i) => {
    const entry = jargon.find((j) => j.term.toLowerCase() === part.toLowerCase())
    if (entry) {
      return (
        <JargonHover key={i} term={entry.term} definition={entry.definition}>
          {part}
        </JargonHover>
      )
    }
    return part
  })
}

export function SlideRenderer({ slide, jargon }: SlideRendererProps) {
  const [imgError, setImgError] = useState(false)

  const imageUrl = !imgError && slide.image_url ? slide.image_url : slide.fallback_image_url

  return (
    <div className="flex h-full flex-col justify-between rounded-xl bg-white p-8 shadow-sm dark:bg-slate-800">
      {/* Title */}
      <div>
        <h2 className="mb-6 text-2xl font-bold leading-snug text-slate-900 dark:text-white">
          {slide.title}
        </h2>

        {/* Bullets */}
        {slide.bullets.length > 0 && (
          <ul className="space-y-3">
            {slide.bullets.map((bullet, idx) => (
              <li
                key={idx}
                className="flex items-start gap-3 text-base leading-relaxed text-slate-700 dark:text-slate-300"
              >
                <span className="mt-1.5 h-2 w-2 flex-shrink-0 rounded-full bg-primary-500" />
                <span>{highlightJargon(bullet, jargon)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Image */}
      {imageUrl && (
        <div className="mt-6 overflow-hidden rounded-lg">
          <div className="relative h-48 w-full">
            <Image
              src={imageUrl}
              alt={slide.title}
              fill
              className="object-contain"
              onError={() => setImgError(true)}
              sizes="(max-width: 768px) 100vw, 50vw"
            />
          </div>
        </div>
      )}
    </div>
  )
}
