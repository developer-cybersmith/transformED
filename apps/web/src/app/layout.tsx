import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'TransformED AI',
  description:
    'Your personal AI tutor — upload any textbook, start learning. Adaptive lessons with real-time engagement monitoring.',
  keywords: ['AI tutor', 'EdTech', 'personalized learning', 'adaptive education'],
  openGraph: {
    title: 'TransformED AI',
    description: 'Your personal AI tutor — upload any textbook, start learning.',
    type: 'website',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <body className="min-h-screen bg-white antialiased dark:bg-slate-900">
        {children}
      </body>
    </html>
  )
}
