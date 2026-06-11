'use client'

import * as Tooltip from '@radix-ui/react-tooltip'

interface JargonHoverProps {
  term: string
  definition: string
  children: React.ReactNode
}

export function JargonHover({ term, definition, children }: JargonHoverProps) {
  return (
    <Tooltip.Provider delayDuration={200}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <span
            className="cursor-help border-b border-dashed border-primary-400 font-medium text-primary-600 hover:text-primary-700 dark:border-primary-500 dark:text-primary-400 dark:hover:text-primary-300"
            aria-label={`${term}: ${definition}`}
          >
            {children}
          </span>
        </Tooltip.Trigger>

        <Tooltip.Portal>
          <Tooltip.Content
            side="top"
            align="start"
            sideOffset={6}
            className="z-50 max-w-xs rounded-lg border border-slate-200 bg-white px-3.5 py-2.5 shadow-lg dark:border-slate-700 dark:bg-slate-800"
          >
            <p className="mb-0.5 text-xs font-semibold uppercase tracking-wide text-primary-600 dark:text-primary-400">
              {term}
            </p>
            <p className="text-sm leading-relaxed text-slate-700 dark:text-slate-300">
              {definition}
            </p>
            <Tooltip.Arrow className="fill-white dark:fill-slate-800" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  )
}
