import Link from 'next/link'
import { createClient } from '@/lib/supabase/server'
import { redirect } from 'next/navigation'
import type { LessonRecord } from '@transformed/shared/types/lesson'
import { Plus, BookOpen } from 'lucide-react'

function StatusBadge({ status }: { status: LessonRecord['status'] }) {
  const styles = {
    ready:      'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
    generating: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
    failed:     'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  }
  const labels = { ready: 'Ready', generating: 'Generating…', failed: 'Failed' }
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[status]}`}>
      {labels[status]}
    </span>
  )
}

function LessonCardSkeleton() {
  return (
    <div className="animate-pulse rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800">
      <div className="mb-3 h-4 w-3/4 rounded bg-slate-200 dark:bg-slate-700" />
      <div className="mb-4 h-3 w-1/4 rounded bg-slate-200 dark:bg-slate-700" />
      <div className="h-3 w-1/3 rounded bg-slate-200 dark:bg-slate-700" />
    </div>
  )
}

function EmptyState() {
  return (
    <div className="col-span-full flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-200 bg-slate-50 py-16 dark:border-slate-700 dark:bg-slate-800/50">
      <BookOpen className="mb-4 h-12 w-12 text-slate-300 dark:text-slate-600" />
      <h3 className="mb-1 text-lg font-semibold text-slate-700 dark:text-slate-300">
        No lessons yet
      </h3>
      <p className="mb-6 text-sm text-slate-500 dark:text-slate-400">
        Upload a PDF to generate your first AI lesson.
      </p>
      <Link
        href="/upload"
        className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-primary-700 transition-colors"
      >
        <Plus className="h-4 w-4" />
        Upload New Lesson
      </Link>
    </div>
  )
}

export default async function DashboardPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) {
    redirect('/login')
  }

  const { data: lessons } = await supabase
    .from('lessons')
    .select('lesson_id, title, status, created_at')
    .eq('user_id', user.id)
    .order('created_at', { ascending: false })

  const lessonList = (lessons ?? []) as Pick<LessonRecord, 'lesson_id' | 'title' | 'status' | 'created_at'>[]

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-900">
      <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <span className="text-xl font-bold text-primary-600">TransformED AI</span>
          <div className="text-sm text-slate-500 dark:text-slate-400">{user.email}</div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-10">
        <div className="mb-8 flex items-center justify-between">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">My Lessons</h1>
          <Link
            href="/upload"
            className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700 transition-colors"
          >
            <Plus className="h-4 w-4" />
            Upload New Lesson
          </Link>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {lessonList.length === 0 ? (
            <EmptyState />
          ) : (
            lessonList.map((lesson) => (
              <Link
                key={lesson.lesson_id}
                href={lesson.status === 'ready' ? `/lesson/${lesson.lesson_id}` : '#'}
                className={`group rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition-shadow hover:shadow-md dark:border-slate-700 dark:bg-slate-800 ${
                  lesson.status !== 'ready' ? 'pointer-events-none opacity-75' : ''
                }`}
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <h2 className="line-clamp-2 text-sm font-semibold text-slate-900 group-hover:text-primary-600 dark:text-white dark:group-hover:text-primary-400">
                    {lesson.title}
                  </h2>
                  <StatusBadge status={lesson.status} />
                </div>
                <p className="text-xs text-slate-400 dark:text-slate-500">
                  {new Date(lesson.created_at).toLocaleDateString('en-US', {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                  })}
                </p>
              </Link>
            ))
          )}
        </div>
      </main>
    </div>
  )
}
