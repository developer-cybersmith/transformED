import Link from 'next/link'
import { BookOpen, BarChart2, Brain } from 'lucide-react'

const features = [
  {
    icon: BookOpen,
    title: 'AI Lesson Generation',
    description:
      'Upload any PDF textbook or paper. Our AI breaks it into structured segments with narrated slides, quizzes, and jargon definitions — in under 15 minutes.',
  },
  {
    icon: BarChart2,
    title: 'Real-time Engagement Monitoring',
    description:
      'On-device attention tracking uses your camera locally — no video ever leaves your browser. The AI tutor adapts pacing and intervenes when you need it most.',
  },
  {
    icon: Brain,
    title: 'Personalized Learner DNA',
    description:
      'A one-time 20-question assessment maps your cognitive style, emotional preferences, and self-direction level. Every lesson is tailored to your unique profile.',
  },
]

export default function HomePage() {
  return (
    <div className="flex min-h-screen flex-col">
      {/* Nav */}
      <header className="border-b border-slate-200 bg-white/80 backdrop-blur-sm dark:border-slate-800 dark:bg-slate-900/80">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <span className="text-xl font-bold text-primary-600">TransformED AI</span>
          <nav className="flex items-center gap-4">
            <Link
              href="/login"
              className="text-sm font-medium text-slate-600 hover:text-primary-600 dark:text-slate-400 dark:hover:text-primary-400"
            >
              Sign In
            </Link>
            <Link
              href="/signup"
              className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-700 transition-colors"
            >
              Get Started
            </Link>
          </nav>
        </div>
      </header>

      <main className="flex-1">
        {/* Hero */}
        <section className="mx-auto max-w-6xl px-6 py-24 text-center">
          <div className="mx-auto max-w-3xl">
            <div className="mb-6 inline-flex items-center rounded-full border border-primary-200 bg-primary-50 px-4 py-1.5 text-sm font-medium text-primary-700">
              Now in Beta
            </div>
            <h1 className="mb-6 text-5xl font-bold leading-tight tracking-tight text-slate-900 dark:text-white sm:text-6xl">
              TransformED AI
            </h1>
            <p className="mb-10 text-xl leading-relaxed text-slate-600 dark:text-slate-400">
              Your personal AI tutor — upload any textbook, start learning.
            </p>
            <div className="flex flex-col items-center justify-center gap-4 sm:flex-row">
              <Link
                href="/signup"
                className="w-full rounded-xl bg-primary-600 px-8 py-3.5 text-base font-semibold text-white shadow-md hover:bg-primary-700 transition-colors sm:w-auto"
              >
                Start Learning
              </Link>
              <Link
                href="/login"
                className="w-full rounded-xl border border-slate-300 bg-white px-8 py-3.5 text-base font-semibold text-slate-700 hover:bg-slate-50 transition-colors dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700 sm:w-auto"
              >
                Sign In
              </Link>
            </div>
          </div>
        </section>

        {/* Feature Grid */}
        <section className="border-t border-slate-100 bg-slate-50 px-6 py-20 dark:border-slate-800 dark:bg-slate-900/50">
          <div className="mx-auto max-w-6xl">
            <h2 className="mb-12 text-center text-3xl font-bold text-slate-900 dark:text-white">
              Learning, reimagined
            </h2>
            <div className="grid gap-8 sm:grid-cols-3">
              {features.map(({ icon: Icon, title, description }) => (
                <div
                  key={title}
                  className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm dark:border-slate-700 dark:bg-slate-800"
                >
                  <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-xl bg-primary-100 dark:bg-primary-900/40">
                    <Icon className="h-6 w-6 text-primary-600 dark:text-primary-400" />
                  </div>
                  <h3 className="mb-3 text-lg font-semibold text-slate-900 dark:text-white">
                    {title}
                  </h3>
                  <p className="text-sm leading-relaxed text-slate-600 dark:text-slate-400">
                    {description}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-slate-200 py-8 text-center text-sm text-slate-500 dark:border-slate-800">
        © {new Date().getFullYear()} TransformED AI. All rights reserved.
      </footer>
    </div>
  )
}
