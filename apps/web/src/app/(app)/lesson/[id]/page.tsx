import { createClient } from '@/lib/supabase/server'
import { redirect, notFound } from 'next/navigation'
import type { LessonRecord } from '@transformed/shared/types/lesson'
import { PlayerLoader } from '@/features/player/PlayerLoader'

interface PageProps {
  params: { id: string }
}

export default async function LessonPage({ params }: PageProps) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) {
    redirect('/login')
  }

  const { data: lesson, error } = await supabase
    .from('lessons')
    .select('*')
    .eq('lesson_id', params.id)
    .eq('user_id', user.id)
    .single()

  if (error || !lesson) {
    notFound()
  }

  const lessonRecord = lesson as LessonRecord

  if (lessonRecord.status === 'generating') {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-900 text-white">
        <div className="mb-4 h-8 w-8 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
        <h1 className="mb-2 text-xl font-semibold">Lesson is being generated…</h1>
        <p className="text-sm text-slate-400">
          This can take up to 15 minutes. Refresh this page to check the status.
        </p>
      </div>
    )
  }

  if (lessonRecord.status === 'failed') {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-slate-900 text-white">
        <h1 className="mb-2 text-xl font-semibold text-red-400">Lesson generation failed</h1>
        <p className="text-sm text-slate-400">
          Something went wrong. Please try uploading again.
        </p>
      </div>
    )
  }

  if (!lessonRecord.content) {
    notFound()
  }

  return <PlayerLoader lesson={lessonRecord.content} />
}
