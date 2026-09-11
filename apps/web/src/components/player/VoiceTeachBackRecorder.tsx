'use client';

import { useEffect, useRef, useState } from 'react';
import { Mic, Square, RotateCcw } from 'lucide-react';
import { FOCUS_RING } from '@/lib/a11y/focusRing';

// Story 2-63 / BR-6. Reasonable ceiling on a single teach-back recording --
// well under Whisper's 25 MB / ~100 min API limit at typical browser
// bitrates (Story F2-4's own stt_max_file_mb=25 default), but far beyond any
// real teach-back explanation. Auto-stop is an explicit, surfaced
// degradation (a one-time notice shown after the fact, see `autoStopped`
// below) -- never a live countdown, which would violate CLAUDE.md's "No
// teach-back timer -- creates test anxiety."
const MAX_RECORDING_MS = 5 * 60 * 1000;

// MediaRecorder's own supported mimeType varies by browser (Chrome/Firefox
// default to webm/opus, Safari to mp4/aac) -- the backend's audio endpoint
// (Story F2-4) explicitly accepts both, so try each in preference order and
// fall through to the browser's own default (undefined options) if every
// candidate is unsupported or the check itself throws (older browser) --
// same fallback-chain idiom as this codebase's TTS provider chain, never a
// hard failure on mimeType selection.
const PREFERRED_MIME_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];

function pickSupportedMimeType(): string {
  if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') {
    return '';
  }
  for (const type of PREFERRED_MIME_TYPES) {
    try {
      if (MediaRecorder.isTypeSupported(type)) return type;
    } catch {
      // Some older browsers throw rather than return false for an unknown
      // type string -- treat exactly like "not supported" and keep trying.
    }
  }
  return '';
}

/** Exported so TeachBackModal can hide the Record tab entirely on an
 * unsupported browser (explicit degradation to typed-only), rather than
 * showing a button that would only fail when clicked. */
export function isVoiceRecordingSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === 'function' &&
    typeof MediaRecorder !== 'undefined'
  );
}

type RecorderStatus = 'idle' | 'requesting' | 'recording' | 'recorded' | 'permission-denied';

interface VoiceTeachBackRecorderProps {
  onSubmit: (audioBlob: Blob, mimeType: string) => void;
  isSubmitting: boolean;
}

export function VoiceTeachBackRecorder({ onSubmit, isSubmitting }: VoiceTeachBackRecorderProps) {
  const [status, setStatus] = useState<RecorderStatus>('idle');
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [autoStopped, setAutoStopped] = useState(false);

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const mimeTypeRef = useRef('');
  const maxDurationTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const audioBlobRef = useRef<Blob | null>(null);
  const audioUrlRef = useRef<string | null>(null);

  // AC9: the mic stream is always released as soon as it's no longer needed
  // -- recording stop, re-record, or unmount -- never left running with the
  // browser's mic-in-use indicator lit after recording ends.
  function releaseStream() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  useEffect(() => {
    return () => {
      if (maxDurationTimerRef.current) clearTimeout(maxDurationTimerRef.current);
      releaseStream();
      if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
    };
  }, []);

  async function startRecording() {
    setStatus('requesting');
    setAutoStopped(false);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const mimeType = pickSupportedMimeType();
      mimeTypeRef.current = mimeType;
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, {
          type: mimeTypeRef.current || recorder.mimeType || 'audio/webm',
        });
        audioBlobRef.current = blob;
        if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
        const url = URL.createObjectURL(blob);
        audioUrlRef.current = url;
        setAudioUrl(url);
        setStatus('recorded');
        releaseStream();
      };

      recorderRef.current = recorder;
      recorder.start();
      setStatus('recording');

      maxDurationTimerRef.current = setTimeout(() => {
        if (recorderRef.current?.state === 'recording') {
          setAutoStopped(true);
          recorderRef.current.stop();
        }
      }, MAX_RECORDING_MS);
    } catch {
      // Permission denied, no mic device, or an insecure (non-HTTPS) context
      // -- never block the student's progress; the parent's Type tab stays
      // available regardless, and Start Recording remains here to retry.
      releaseStream();
      setStatus('permission-denied');
    }
  }

  function stopRecording() {
    if (maxDurationTimerRef.current) clearTimeout(maxDurationTimerRef.current);
    recorderRef.current?.stop();
  }

  function reRecord() {
    if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
    audioUrlRef.current = null;
    setAudioUrl(null);
    audioBlobRef.current = null;
    setAutoStopped(false);
    setStatus('idle');
  }

  function handleSubmit() {
    if (audioBlobRef.current) {
      onSubmit(audioBlobRef.current, mimeTypeRef.current || 'audio/webm');
    }
  }

  if (status === 'permission-denied') {
    return (
      <div className="px-6 py-4">
        <p className="text-sm text-neutral-500 mb-3">
          We couldn&apos;t access your microphone. It may have been blocked or is unavailable — you
          can try again, or use the Type tab above instead.
        </p>
        <button
          onClick={startRecording}
          className={`flex items-center gap-2 px-4 py-2 rounded-full bg-neutral-100 hover:bg-neutral-200
                     text-neutral-700 text-sm font-medium transition-colors ${FOCUS_RING}`}
        >
          <Mic className="w-4 h-4" />
          Start Recording
        </button>
      </div>
    );
  }

  if (status === 'recorded') {
    return (
      <div className="px-6 py-4">
        {autoStopped && (
          <p className="text-xs text-neutral-500 mb-3">
            Recording stopped automatically after 5 minutes. You can review it below, submit it, or
            re-record.
          </p>
        )}
        {audioUrl && <audio controls src={audioUrl} className="w-full mb-4" />}
        <div className="flex justify-between items-center gap-3">
          <button
            onClick={reRecord}
            disabled={isSubmitting}
            className={`flex items-center gap-1.5 text-neutral-500 hover:text-neutral-900 text-sm
                       transition-colors rounded disabled:opacity-40 disabled:cursor-not-allowed ${FOCUS_RING}`}
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Re-record
          </button>
          <button
            onClick={handleSubmit}
            disabled={isSubmitting}
            className={`px-5 py-2 rounded-full bg-[var(--accent-secondary)] hover:brightness-105
                       text-primary text-sm font-semibold transition-all
                       disabled:opacity-40 disabled:cursor-not-allowed ${FOCUS_RING}`}
          >
            {isSubmitting ? 'Scoring…' : 'Submit Recording'}
          </button>
        </div>
      </div>
    );
  }

  if (status === 'recording') {
    return (
      <div className="px-6 py-4 flex flex-col items-center gap-4">
        {/* No elapsed-time display here, ever -- CLAUDE.md: "No teach-back
            timer -- creates test anxiety." A pulsing dot signals "recording
            is live" without any numeric countdown. */}
        <div className="flex items-center gap-2 text-neutral-600 text-sm">
          <span className="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse" aria-hidden />
          Recording…
        </div>
        <button
          onClick={stopRecording}
          className={`flex items-center gap-2 px-5 py-2 rounded-full bg-neutral-900 hover:bg-neutral-800
                     text-white text-sm font-semibold transition-colors ${FOCUS_RING}`}
        >
          <Square className="w-3.5 h-3.5" />
          Stop Recording
        </button>
      </div>
    );
  }

  // idle / requesting
  return (
    <div className="px-6 py-4 flex justify-center">
      <button
        onClick={startRecording}
        disabled={status === 'requesting'}
        className={`flex items-center gap-2 px-5 py-2 rounded-full bg-[var(--accent-secondary)] hover:brightness-105
                   text-primary text-sm font-semibold transition-all
                   disabled:opacity-40 disabled:cursor-not-allowed ${FOCUS_RING}`}
      >
        <Mic className="w-4 h-4" />
        {status === 'requesting' ? 'Requesting microphone…' : 'Start Recording'}
      </button>
    </div>
  );
}
