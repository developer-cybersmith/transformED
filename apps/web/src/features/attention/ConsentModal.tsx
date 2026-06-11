'use client'

import * as Dialog from '@radix-ui/react-dialog'
import { Camera, ShieldCheck } from 'lucide-react'

interface ConsentModalProps {
  onAllow: () => void
  onDecline: () => void
}

export function ConsentModal({ onAllow, onDecline }: ConsentModalProps) {
  return (
    <Dialog.Root open>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-slate-700 bg-slate-800 p-8 shadow-2xl"
          onEscapeKeyDown={onDecline}
          onInteractOutside={onDecline}
        >
          {/* Icon */}
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary-900/40">
            <Camera className="h-7 w-7 text-primary-400" />
          </div>

          <Dialog.Title className="mb-3 text-center text-xl font-semibold text-white">
            Enable Engagement Monitoring?
          </Dialog.Title>

          <Dialog.Description asChild>
            <div className="mb-6 space-y-3 text-sm text-slate-300">
              <p>
                TransformED AI can use your camera to detect when you might be distracted, confused, or fatigued —
                so your AI tutor can step in at the right moment.
              </p>

              <div className="rounded-xl border border-slate-600 bg-slate-700/50 p-4">
                <div className="mb-2 flex items-center gap-2 font-semibold text-green-400">
                  <ShieldCheck className="h-4 w-4" />
                  Your privacy is protected
                </div>
                <ul className="space-y-1.5 text-slate-300">
                  <li className="flex items-start gap-2">
                    <span className="mt-0.5 text-green-500">✓</span>
                    Only <strong>head pose and blink rate</strong> are tracked — no faces, no images
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="mt-0.5 text-green-500">✓</span>
                    All processing happens <strong>on your device</strong>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="mt-0.5 text-green-500">✓</span>
                    <strong>No video is ever stored or transmitted</strong> — only 3 numbers every 5 seconds
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="mt-0.5 text-green-500">✓</span>
                    You can decline and still learn with full functionality
                  </li>
                </ul>
              </div>

              <p className="text-xs text-slate-400">
                By allowing, you consent to on-device attention monitoring as described above.
                You can revoke consent at any time from your account settings.
              </p>
            </div>
          </Dialog.Description>

          <div className="flex gap-3">
            <button
              onClick={onDecline}
              className="flex-1 rounded-xl border border-slate-600 bg-transparent py-2.5 text-sm font-medium text-slate-300 hover:bg-slate-700 transition-colors"
            >
              Decline
            </button>
            <button
              onClick={onAllow}
              className="flex-1 rounded-xl bg-primary-600 py-2.5 text-sm font-semibold text-white hover:bg-primary-700 transition-colors"
            >
              Allow
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
