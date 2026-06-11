import type { ServerMessage, ClientMessage } from '@transformed/shared/types/ws'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type MessageHandler = (msg: ServerMessage) => void

// ---------------------------------------------------------------------------
// WebSocket client with auto-reconnect (exponential backoff, max 5 retries)
// ---------------------------------------------------------------------------

const MAX_RETRIES = 5
const BASE_DELAY_MS = 1000
const MAX_DELAY_MS = 30_000

class WebSocketClient {
  private ws: WebSocket | null = null
  private sessionId: string | null = null
  private token: string | null = null
  private handlers: MessageHandler[] = []
  private retryCount = 0
  private retryTimer: ReturnType<typeof setTimeout> | null = null
  private intentionalClose = false

  // ── connect ──────────────────────────────────────────────────────────────

  connect(sessionId: string, token: string): void {
    this.sessionId = sessionId
    this.token = token
    this.intentionalClose = false
    this.retryCount = 0
    this.openConnection()
  }

  private openConnection(): void {
    if (!this.sessionId) return

    const baseUrl = process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000'
    const url = `${baseUrl}/ws/session/${this.sessionId}?token=${this.token ?? ''}`

    try {
      this.ws = new WebSocket(url)
    } catch (err) {
      console.warn('[WSClient] Failed to create WebSocket:', err)
      this.scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      console.info(`[WSClient] Connected (session=${this.sessionId})`)
      this.retryCount = 0
    }

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data as string) as ServerMessage
        this.handlers.forEach((h) => h(msg))
      } catch (err) {
        console.warn('[WSClient] Failed to parse message:', err)
      }
    }

    this.ws.onerror = (event) => {
      console.warn('[WSClient] WebSocket error:', event)
    }

    this.ws.onclose = (event) => {
      console.info(`[WSClient] Closed (code=${event.code}, intentional=${this.intentionalClose})`)
      if (!this.intentionalClose) {
        this.scheduleReconnect()
      }
    }
  }

  // ── disconnect ────────────────────────────────────────────────────────────

  disconnect(): void {
    this.intentionalClose = true
    if (this.retryTimer) {
      clearTimeout(this.retryTimer)
      this.retryTimer = null
    }
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect')
      this.ws = null
    }
  }

  // ── send ──────────────────────────────────────────────────────────────────

  send(message: ClientMessage): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('[WSClient] Cannot send — socket not open')
      return
    }
    this.ws.send(JSON.stringify(message))
  }

  // ── onMessage ─────────────────────────────────────────────────────────────

  onMessage(handler: MessageHandler): () => void {
    this.handlers.push(handler)
    return () => {
      this.handlers = this.handlers.filter((h) => h !== handler)
    }
  }

  // ── reconnect logic ───────────────────────────────────────────────────────

  private scheduleReconnect(): void {
    if (this.retryCount >= MAX_RETRIES) {
      console.warn('[WSClient] Max retries reached — giving up')
      return
    }

    const delay = Math.min(BASE_DELAY_MS * 2 ** this.retryCount, MAX_DELAY_MS)
    this.retryCount++

    console.info(`[WSClient] Reconnecting in ${delay}ms (attempt ${this.retryCount}/${MAX_RETRIES})`)

    this.retryTimer = setTimeout(() => {
      this.retryTimer = null
      this.openConnection()
    }, delay)
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }
}

// ── Singleton instance exported for use across the app ─────────────────────
export const wsClient = new WebSocketClient()
