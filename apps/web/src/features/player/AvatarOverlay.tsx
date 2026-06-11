'use client'

import { useEffect, useRef } from 'react'
import type { PlayerState } from './player.machine'

interface AvatarOverlayProps {
  playerState: PlayerState
  segmentTitle: string
}

export function AvatarOverlay({ playerState, segmentTitle }: AvatarOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  // Animate a simple breathing/idle effect on the avatar placeholder
  // In production this would render the actual avatar sprite or video
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animationId: number
    let frame = 0

    function draw() {
      if (!ctx || !canvas) return
      ctx.clearRect(0, 0, canvas.width, canvas.height)

      const cx = canvas.width / 2
      const cy = canvas.height / 2

      // Subtle breathing scale
      const breathe = playerState === 'PLAYING' ? 1 + Math.sin(frame * 0.03) * 0.015 : 1

      // Avatar circle (placeholder)
      ctx.save()
      ctx.translate(cx, cy)
      ctx.scale(breathe, breathe)

      // Outer glow when playing
      if (playerState === 'PLAYING') {
        const grd = ctx.createRadialGradient(0, 0, 50, 0, 0, 80)
        grd.addColorStop(0, 'rgba(37,99,235,0.15)')
        grd.addColorStop(1, 'rgba(37,99,235,0)')
        ctx.fillStyle = grd
        ctx.beginPath()
        ctx.arc(0, 0, 80, 0, Math.PI * 2)
        ctx.fill()
      }

      // Face
      ctx.fillStyle = '#dbeafe'
      ctx.beginPath()
      ctx.arc(0, 0, 52, 0, Math.PI * 2)
      ctx.fill()

      ctx.strokeStyle = '#2563eb'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.arc(0, 0, 52, 0, Math.PI * 2)
      ctx.stroke()

      // Eyes
      const eyeY = -12
      const blink = playerState === 'PLAYING' && Math.sin(frame * 0.04) > 0.97 ? 1 : 0
      const eyeH = blink ? 1 : 7

      ctx.fillStyle = '#1e40af'
      ctx.beginPath()
      ctx.ellipse(-16, eyeY, 6, eyeH, 0, 0, Math.PI * 2)
      ctx.fill()
      ctx.beginPath()
      ctx.ellipse(16, eyeY, 6, eyeH, 0, 0, Math.PI * 2)
      ctx.fill()

      // Mouth
      const mouthOpen = playerState === 'PLAYING' ? Math.abs(Math.sin(frame * 0.08)) * 4 : 0
      ctx.strokeStyle = '#1e40af'
      ctx.lineWidth = 2.5
      ctx.lineCap = 'round'
      ctx.beginPath()
      ctx.moveTo(-14, 18)
      ctx.quadraticCurveTo(0, 26 + mouthOpen, 14, 18)
      ctx.stroke()

      ctx.restore()
      frame++
      animationId = requestAnimationFrame(draw)
    }

    draw()
    return () => cancelAnimationFrame(animationId)
  }, [playerState])

  return (
    <div className="flex h-full flex-col items-center justify-center rounded-xl bg-slate-900 p-6">
      <canvas
        ref={canvasRef}
        width={180}
        height={180}
        className="mb-4"
        aria-hidden
      />
      <p className="text-center text-sm font-medium text-slate-400">
        {playerState === 'PLAYING' ? 'Teaching…' : playerState === 'PAUSED' ? 'Paused' : 'Ready'}
      </p>
      {segmentTitle && (
        <p className="mt-1 line-clamp-2 text-center text-xs text-slate-500">{segmentTitle}</p>
      )}
    </div>
  )
}
