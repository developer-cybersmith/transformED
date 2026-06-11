'use client'

import { useState, useRef, useCallback, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Upload, FileText, X, Loader2 } from 'lucide-react'
import { createClient } from '@/lib/supabase/client'
import { apiClient } from '@/lib/api/client'
import type { GenerationProgressMessage } from '@transformed/shared/types/ws'

const MAX_FILE_SIZE = 100 * 1024 * 1024 // 100 MB

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

type UploadState = 'idle' | 'selected' | 'uploading' | 'generating' | 'done' | 'error'

export default function UploadPage() {
  const router = useRouter()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const wsRef = useRef<WebSocket | null>(null)

  const [uploadState, setUploadState] = useState<UploadState>('idle')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)
  const [progressMessage, setProgressMessage] = useState('')
  const [lessonId, setLessonId] = useState<string | null>(null)

  // Drag state
  const [isDragging, setIsDragging] = useState(false)

  const handleFileSelect = useCallback((file: File) => {
    setError(null)
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setError('Only PDF files are supported.')
      return
    }
    if (file.size > MAX_FILE_SIZE) {
      setError(`File is too large. Maximum size is 100 MB. Your file is ${formatBytes(file.size)}.`)
      return
    }
    setSelectedFile(file)
    setUploadState('selected')
  }, [])

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragging(false)
      const file = e.dataTransfer.files[0]
      if (file) handleFileSelect(file)
    },
    [handleFileSelect],
  )

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) handleFileSelect(file)
  }

  // WebSocket listener for generation progress
  function connectProgressWs(id: string) {
    const supabase = createClient()
    supabase.auth.getSession().then(({ data }) => {
      const token = data.session?.access_token
      const wsUrl = `${process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000'}/ws/generation/${id}?token=${token ?? ''}`
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data as string) as GenerationProgressMessage
          if (msg.type === 'generation_progress') {
            setProgress(msg.payload.progress)
            setProgressMessage(msg.payload.message)
          }
          if (msg.payload.progress >= 100) {
            setUploadState('done')
            setTimeout(() => router.push(`/lesson/${id}`), 1500)
          }
        } catch {
          // ignore malformed messages
        }
      }

      ws.onerror = () => {
        // WS unavailable — just show spinner, user can navigate manually
      }
    })
  }

  async function handleSubmit() {
    if (!selectedFile) return
    setError(null)
    setUploadState('uploading')

    try {
      const formData = new FormData()
      formData.append('file', selectedFile)

      const response = await apiClient.postForm<{ lesson_id: string }>('/api/content/lessons', formData)
      setLessonId(response.lesson_id)
      setUploadState('generating')
      setProgress(0)
      setProgressMessage('Starting lesson generation…')
      connectProgressWs(response.lesson_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed. Please try again.')
      setUploadState('selected')
    }
  }

  useEffect(() => {
    return () => {
      wsRef.current?.close()
    }
  }, [])

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-900">
      <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="mx-auto flex max-w-4xl items-center px-6 py-4">
          <span className="text-xl font-bold text-primary-600">TransformED AI</span>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-12">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Upload a PDF</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Upload any textbook chapter or paper (max 100 MB). We&apos;ll generate an interactive lesson in ~15 minutes.
          </p>
        </div>

        {uploadState === 'generating' || uploadState === 'done' ? (
          <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center shadow-sm dark:border-slate-700 dark:bg-slate-800">
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-primary-100 dark:bg-primary-900/30">
              {uploadState === 'done' ? (
                <span className="text-3xl">🎉</span>
              ) : (
                <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
              )}
            </div>
            <h2 className="mb-2 text-xl font-semibold text-slate-900 dark:text-white">
              {uploadState === 'done' ? 'Lesson ready!' : 'Generating your lesson…'}
            </h2>
            <p className="mb-6 text-sm text-slate-500 dark:text-slate-400">
              {uploadState === 'done'
                ? 'Redirecting you to your lesson…'
                : 'This may take up to 15 minutes. You can keep this tab open.'}
            </p>

            {uploadState === 'generating' && (
              <div className="space-y-2">
                <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                  <div
                    className="h-full rounded-full bg-primary-600 transition-all duration-500"
                    style={{ width: `${Math.max(progress, 3)}%` }}
                  />
                </div>
                <p className="text-xs text-slate-400 dark:text-slate-500">
                  {progressMessage || 'Processing…'}
                </p>
              </div>
            )}

            {lessonId && uploadState === 'generating' && (
              <button
                onClick={() => router.push(`/lesson/${lessonId}`)}
                className="mt-6 text-sm text-primary-600 underline hover:text-primary-700"
              >
                Check lesson status →
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-6">
            {/* Drop zone */}
            <div
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={onDrop}
              className={`cursor-pointer rounded-2xl border-2 border-dashed p-12 text-center transition-colors ${
                isDragging
                  ? 'border-primary-400 bg-primary-50 dark:border-primary-500 dark:bg-primary-900/10'
                  : 'border-slate-300 bg-white hover:border-primary-300 hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:hover:border-primary-700'
              }`}
            >
              <Upload className="mx-auto mb-4 h-10 w-10 text-slate-400 dark:text-slate-500" />
              <p className="mb-1 text-sm font-medium text-slate-700 dark:text-slate-300">
                Drag and drop your PDF here, or click to browse
              </p>
              <p className="text-xs text-slate-400 dark:text-slate-500">PDF only · Max 100 MB</p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf"
                onChange={onInputChange}
                className="hidden"
              />
            </div>

            {/* Selected file info */}
            {selectedFile && (
              <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-3 dark:border-slate-700 dark:bg-slate-800">
                <div className="flex items-center gap-3">
                  <FileText className="h-5 w-5 text-primary-600 dark:text-primary-400" />
                  <div>
                    <p className="text-sm font-medium text-slate-900 dark:text-white">{selectedFile.name}</p>
                    <p className="text-xs text-slate-400">{formatBytes(selectedFile.size)}</p>
                  </div>
                </div>
                <button
                  onClick={() => { setSelectedFile(null); setUploadState('idle') }}
                  className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-700"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            )}

            {/* Error */}
            {error && (
              <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
                {error}
              </div>
            )}

            {/* Submit */}
            <button
              onClick={handleSubmit}
              disabled={!selectedFile || uploadState === 'uploading'}
              className="w-full rounded-xl bg-primary-600 py-3 text-sm font-semibold text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
            >
              {uploadState === 'uploading' ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Uploading…
                </span>
              ) : (
                'Generate Lesson'
              )}
            </button>
          </div>
        )}
      </main>
    </div>
  )
}
