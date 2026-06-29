---
baseline_commit: 3f727b3823804b8af83c514b6f203373cdd150e5
---

# Story S1-07 — Real WebSocket Client (Lesson Socket)

**Epic:** Sprint 1 — Core Player  
**Priority:** P1  
**Status:** done

---

## Story

As the lesson player, I need a real WebSocket client that connects to Dev 4's live `/ws/{session_id}` endpoint — with exponential-backoff reconnection, typed message dispatch to the player store, and a 5-second attention-signal heartbeat — so the tutor engine can push interventions and CES updates into the running lesson without freezing playback if the connection drops.

---

## Acceptance Criteria

- [x] AC1: `LessonSocket.connect(sessionId, token, callbacks)` opens a native `WebSocket` to `${NEXT_PUBLIC_WS_URL}/ws/${sessionId}` with Bearer token passed as a subprotocol
- [x] AC2: On WebSocket `close`, reconnects with exponential backoff: `delay = 2^attempt × 1000 ms`, max 5 attempts. After max attempts, sets `connectionStatus = 'offline'` and stops retrying — lesson continues uninterrupted
- [x] AC3: Received `tutor_intervene` message is dispatched to the player store via the `onTutorIntervene` callback
- [x] AC4: Received `ces_update` message updates `playerStore.cesScore` via `store.updateCes(ces)`
- [x] AC5: Received `state_change` message calls `store.setTutorState(to_state)`
- [x] AC6: `useLessonSocket` hook sends `AttentionSignalMessage` every 5 seconds while connected
- [x] AC7: Lesson playback (audio, slides, store state machine) is NEVER blocked or paused by WebSocket unavailability
- [x] AC8: `npx tsc --noEmit` — zero TypeScript errors across all modified/created files

---

## Tasks / Subtasks

- [x] Task 1: Extend `stores/player.machine.ts` — add CES field + action
  - [x] 1a: Add `cesScore: number | null` to `PlayerStore` interface
  - [x] 1b: Add `updateCes: (ces: number) => void` to `PlayerStore` interface
  - [x] 1c: Initialize `cesScore: null` in the `create()` block
  - [x] 1d: Implement `updateCes: (ces) => set({ cesScore: ces })` action
  - [x] 1e: Confirm `stores/player.machine.ts` still passes `npx tsc --noEmit`

- [x] Task 2: Write failing tests for `LessonSocket` class (RED phase)
  - [x] 2a: Create `apps/web/src/__tests__/lib/ws/lessonSocket.test.ts`
  - [x] 2b: Stub global `WebSocket` in `beforeEach` (see Dev Notes — `MockWebSocket` shape)
  - [x] 2c: Test: `connect()` constructs WebSocket with correct URL (`${NEXT_PUBLIC_WS_URL}/ws/${sessionId}`)
  - [x] 2d: Test: `connect()` passes `['Bearer', token]` as second argument (subprotocol array)
  - [x] 2e: Test: `handleClose` schedules reconnect with `delay = 2^attempt × 1000` for attempt 0 (delay 1000ms)
  - [x] 2f: Test: `handleClose` schedules reconnect with `delay = 4000ms` for attempt 2
  - [x] 2g: Test: after 5 failed attempts, `connectionStatus` becomes `'offline'` and no further reconnect scheduled
  - [x] 2h: Test: `send()` calls `ws.send(JSON.stringify(msg))`
  - [x] 2i: Test: `send()` is a no-op when `ws` is null or `readyState !== OPEN`
  - [x] 2j: Test: incoming `tutor_intervene` message triggers `onTutorIntervene` callback
  - [x] 2k: Test: incoming `ces_update` message triggers `onCesUpdate` callback with correct `ces` value
  - [x] 2l: Test: incoming `state_change` message triggers `onStateChange` callback with `to_state`
  - [x] 2m: Test: `disconnect()` calls `ws.close()` and clears pending reconnect timer

- [x] Task 3: Create `src/lib/ws/lessonSocket.ts` (GREEN phase)
  - [x] 3a: Define `LessonSocketCallbacks` interface (see Dev Notes)
  - [x] 3b: Define `ConnectionStatus` type: `'connecting' | 'connected' | 'reconnecting' | 'offline'`
  - [x] 3c: Implement `LessonSocket` class with private `ws`, `reconnectAttempts`, `maxAttempts = 5`, `reconnectTimer`, `callbacks`
  - [x] 3d: Implement `connect(sessionId, token, callbacks)` — build URL from `NEXT_PUBLIC_WS_URL`, open WebSocket with Bearer subprotocol
  - [x] 3e: Implement `ws.onopen` handler — resets `reconnectAttempts` to 0, sets `connectionStatus = 'connected'`
  - [x] 3f: Implement `ws.onmessage` handler — `JSON.parse`, discriminate by `msg.type`, dispatch to callbacks
  - [x] 3g: Implement `ws.onclose` handler — exponential backoff (see formula in Dev Notes), set `'reconnecting'` or `'offline'`
  - [x] 3h: Implement `send(msg: ClientMessage)` — guard: skip if `!ws || ws.readyState !== WebSocket.OPEN`
  - [x] 3i: Implement `disconnect()` — call `ws.close()`, clear `reconnectTimer`, reset `reconnectAttempts`
  - [x] 3j: Export `lessonSocket` singleton instance
  - [x] 3k: Confirm all 2x–2m tests now pass

- [x] Task 4: Write failing tests for `useLessonSocket` hook (RED phase)
  - [x] 4a: Create `apps/web/src/__tests__/hooks/useLessonSocket.test.ts`
  - [x] 4b: Mock `lessonSocket` singleton (jest/vitest `vi.mock`)
  - [x] 4c: Mock `@/lib/supabase/client` `createClient().auth.getSession()` to return a fake token
  - [x] 4d: Test: hook calls `lessonSocket.connect(sessionId, token, callbacks)` on mount
  - [x] 4e: Test: hook calls `lessonSocket.disconnect()` on unmount
  - [x] 4f: Test: hook schedules `lessonSocket.send(AttentionSignalMessage)` on a 5000ms interval
  - [x] 4g: Test: hook dispatches `store.setTutorState()` when `onStateChange` callback fires
  - [x] 4h: Test: hook dispatches `store.updateCes()` when `onCesUpdate` callback fires

- [x] Task 5: Create `src/hooks/useLessonSocket.ts` (GREEN phase)
  - [x] 5a: Implement `useLessonSocket(sessionId: string)` hook
  - [x] 5b: On mount: get JWT from `createClient().auth.getSession()`, call `lessonSocket.connect()`
  - [x] 5c: Wire `onTutorIntervene` callback → `usePlayerStore.getState().setTutorState('INTERVENING')` (store tutor state update; actual card rendered Sprint 3)
  - [x] 5d: Wire `onCesUpdate` callback → `usePlayerStore.getState().updateCes(payload.ces)`
  - [x] 5e: Wire `onStateChange` callback → `usePlayerStore.getState().setTutorState(payload.to_state)`
  - [x] 5f: Set up 5-second interval that calls `lessonSocket.send(attentionSignal)` (Sprint 1 defaults — see Dev Notes)
  - [x] 5g: On unmount: call `lessonSocket.disconnect()`, clear interval
  - [x] 5h: Return `{ connectionStatus }` from hook for future UI use
  - [x] 5i: Confirm all 4d–4h tests now pass

- [x] Task 6: Add `NEXT_PUBLIC_WS_URL` to `.env.local`
  - [x] 6a: Append `NEXT_PUBLIC_WS_URL=ws://localhost:8000` to `apps/web/.env.local`

- [x] Task 7: Run full validation
  - [x] 7a: `npx tsc --noEmit` — zero errors (must pass for all new + modified files)
  - [x] 7b: `pnpm test` — all tests pass, no regressions
  - [x] 7c: Confirm player store still has same API surface (nothing removed from public interface)

---

## Dev Notes

### Architecture decision: LessonSocket as a class + singleton

`LessonSocket` is a plain TypeScript class, not a React hook. This keeps the reconnect/timer logic completely decoupled from React's render cycle. The `lessonSocket` singleton is exported from the module and used by `useLessonSocket`. Hooks manage the lifecycle; the class manages the connection.

```
lib/ws/lessonSocket.ts ← pure TS, no React imports
hooks/useLessonSocket.ts ← React lifecycle wrapper, reads from store
```

### Files to create

| File | Status |
|---|---|
| `apps/web/src/lib/ws/lessonSocket.ts` | NEW |
| `apps/web/src/hooks/useLessonSocket.ts` | NEW |
| `apps/web/src/__tests__/lib/ws/lessonSocket.test.ts` | NEW |
| `apps/web/src/__tests__/hooks/useLessonSocket.test.ts` | NEW |

### Files to modify

| File | Change |
|---|---|
| `apps/web/src/stores/player.machine.ts` | Add `cesScore`, `updateCes` (Task 1) |
| `apps/web/.env.local` | Add `NEXT_PUBLIC_WS_URL` (Task 6) |

### LessonSocketCallbacks interface

```typescript
export interface LessonSocketCallbacks {
  onTutorIntervene: (payload: TutorInterveneMessage['payload']) => void;
  onCesUpdate: (payload: CesUpdateMessage['payload']) => void;
  onStateChange: (payload: StateChangeMessage['payload']) => void;
}
```

Import types from `@hie/shared/types/ws` — never from `@/lib/websocket/*` (those are the mock layer).

### LessonSocket class skeleton

```typescript
import type { ClientMessage, ServerMessage, TutorInterveneMessage, CesUpdateMessage, StateChangeMessage } from '@hie/shared/types/ws';

export type ConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'offline';

export interface LessonSocketCallbacks { /* ... */ }

export class LessonSocket {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private readonly maxAttempts = 5;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private sessionId = '';
  private token = '';
  private callbacks: LessonSocketCallbacks | null = null;
  connectionStatus: ConnectionStatus = 'connecting';

  connect(sessionId: string, token: string, callbacks: LessonSocketCallbacks): void {
    this.sessionId = sessionId;
    this.token = token;
    this.callbacks = callbacks;
    const url = `${process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000'}/ws/${sessionId}`;
    this.ws = new WebSocket(url, ['Bearer', token]);
    this.ws.onopen = () => { this.reconnectAttempts = 0; this.connectionStatus = 'connected'; };
    this.ws.onmessage = (e) => this.handleMessage(e);
    this.ws.onclose = () => this.handleClose();
  }

  private handleMessage(e: MessageEvent): void {
    try {
      const msg: ServerMessage = JSON.parse(e.data as string);
      if (msg.type === 'tutor_intervene') this.callbacks?.onTutorIntervene(msg.payload);
      else if (msg.type === 'ces_update') this.callbacks?.onCesUpdate(msg.payload);
      else if (msg.type === 'state_change') this.callbacks?.onStateChange(msg.payload);
      // Other message types (lesson_ready, generation_progress, etc.) ignored here
    } catch { /* malformed JSON — ignore */ }
  }

  private handleClose(): void {
    if (this.reconnectAttempts < this.maxAttempts) {
      const delay = Math.pow(2, this.reconnectAttempts) * 1000;
      this.connectionStatus = 'reconnecting';
      this.reconnectTimer = setTimeout(() => {
        this.reconnectAttempts++;
        this.connect(this.sessionId, this.token, this.callbacks!);
      }, delay);
    } else {
      this.connectionStatus = 'offline';
      // Lesson continues — no throw, no freeze
    }
  }

  send(msg: ClientMessage): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify(msg));
  }

  disconnect(): void {
    if (this.reconnectTimer !== null) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.ws?.close();
    this.ws = null;
    this.reconnectAttempts = 0;
  }
}

export const lessonSocket = new LessonSocket();
```

### useLessonSocket hook skeleton

```typescript
import { useEffect, useRef } from 'react';
import { createClient } from '@/lib/supabase/client';
import { lessonSocket } from '@/lib/ws/lessonSocket';
import { usePlayerStore } from '@/stores/player.machine';
import type { AttentionSignalMessage } from '@hie/shared/types/ws';

export function useLessonSocket(sessionId: string) {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let mounted = true;

    const init = async () => {
      const supabase = createClient();
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token ?? '';
      if (!mounted) return;

      lessonSocket.connect(sessionId, token, {
        onTutorIntervene: (payload) => {
          usePlayerStore.getState().setTutorState('INTERVENING');
          // payload.message available for TutorInterventionCard in Sprint 3
        },
        onCesUpdate: (payload) => {
          usePlayerStore.getState().updateCes(payload.ces);
        },
        onStateChange: (payload) => {
          usePlayerStore.getState().setTutorState(payload.to_state);
        },
      });

      // Sprint 1: send placeholder attention signal every 5s
      // Sprint 3: AttentionMonitor will provide real behavioral/head_pose/blink values
      intervalRef.current = setInterval(() => {
        const signal: AttentionSignalMessage = {
          type: 'attention_signal',
          payload: {
            session_id: sessionId,
            quiz_accuracy: null,
            teachback_score: null,
            behavioral_score: 1.0,
            head_pose_score: 1.0,
            blink_rate: 0.2,
          },
        };
        lessonSocket.send(signal);
      }, 5000);
    };

    init();

    return () => {
      mounted = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
      lessonSocket.disconnect();
    };
  }, [sessionId]);

  return { connectionStatus: lessonSocket.connectionStatus };
}
```

### Token transport: WebSocket subprotocol mechanism

Standard browser WebSocket API does not support custom HTTP headers. The prescribed pattern (from sprint tracker) is:
```typescript
new WebSocket(url, ['Bearer', token])
```
This sends `Sec-WebSocket-Protocol: Bearer, <jwt>` to the server. Dev 4's FastAPI server reads the `Sec-WebSocket-Protocol` header to extract and verify the JWT. **Do not change this pattern** — it is agreed with Dev 4.

Fallback: if `token` is empty string (e.g. unauthenticated), connect proceeds and the server will reject the connection — the `handleClose` backoff fires normally, lesson continues offline.

### Exponential backoff formula

```
attempt 0 → delay 1000ms  (2^0 × 1000)
attempt 1 → delay 2000ms  (2^1 × 1000)
attempt 2 → delay 4000ms  (2^2 × 1000)
attempt 3 → delay 8000ms
attempt 4 → delay 16000ms
attempt 5 → STOP, connectionStatus = 'offline'
```

`reconnectAttempts` is incremented **before** calling `connect()` in the timeout callback (so it's correct on each retry). Reset to 0 on successful `onopen`.

### MockWebSocket for vitest/jsdom

jsdom does not implement `WebSocket`. Stub it in `beforeEach`:

```typescript
class MockWebSocket {
  static OPEN = 1;
  static CLOSED = 3;
  readyState = MockWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  url: string;
  protocols: string[];
  sentMessages: string[] = [];

  constructor(url: string, protocols?: string | string[]) {
    this.url = url;
    this.protocols = Array.isArray(protocols) ? protocols : protocols ? [protocols] : [];
    // Simulate async open
    setTimeout(() => this.onopen?.(), 0);
  }

  send(data: string) { this.sentMessages.push(data); }
  close() { this.readyState = MockWebSocket.CLOSED; this.onclose?.(); }

  // Test helper: simulate incoming server message
  simulateMessage(msg: object) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
}

let lastSocket: MockWebSocket | null = null;

beforeEach(() => {
  vi.useFakeTimers();
  lastSocket = null;
  // @ts-expect-error — mocking global
  global.WebSocket = class extends MockWebSocket {
    constructor(url: string, protocols?: string | string[]) {
      super(url, protocols);
      lastSocket = this;
    }
  };
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
```

Use `vi.advanceTimersByTime(n)` to step through backoff delays in tests.

### PlayerStore extension (Task 1)

Open `stores/player.machine.ts` and add to the interface:
```typescript
// In PlayerStore interface
cesScore: number | null;
updateCes: (ces: number) => void;
```
Add to the `create()` initializer:
```typescript
cesScore: null,
updateCes: (ces) => set({ cesScore: ces }),
```
This is the only change to `player.machine.ts`. All existing actions and state are preserved.

### NEXT_PUBLIC_WS_URL env var

`NEXT_PUBLIC_WS_URL` is not currently in `apps/web/.env.local`. Add:
```
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```
The class falls back to `'ws://localhost:8000'` in code (`?? 'ws://localhost:8000'`) so local dev without `.env.local` still works.

### Graceful degradation (AC7 enforcement)

- WebSocket failure path: `disconnect → handleClose → backoff timers`. No exception is thrown, no store action suspends playback.
- After max attempts: `connectionStatus = 'offline'`. Lesson audio/slides/state machine continue normally.
- `useLessonSocket` hook failure path: if `getSession()` fails, token is empty string. Connection attempt fires, server rejects, backoff runs, lesson continues.
- **NEVER** throw from `handleClose`, `handleMessage`, or anywhere in the socket class.

### What NOT to touch

- `lib/websocket/` directory (mock layer for upload flow) — this is Dev 0/Sprint 0 infrastructure. `LessonSocket` lives in the separate `lib/ws/` path (single `s`).
- `lib/websocket/mockSocket.ts` — still used by `uploadGenerationService`. Do not break it.
- Any file in `packages/shared/` — frozen contracts.
- `apps/api/` — read-only for Dev 2.

### Test file paths (exact)

```
apps/web/src/__tests__/lib/ws/lessonSocket.test.ts
apps/web/src/__tests__/hooks/useLessonSocket.test.ts
```

Note: test for a `.ts` (non-React) class uses `.test.ts` extension, not `.test.tsx`.

### Sprint 1 attention signal values

`AttentionMonitor` is Sprint 3. For Sprint 1, send placeholder values that register as "student present and attentive":
- `behavioral_score: 1.0` — full presence
- `head_pose_score: 1.0` — looking at screen
- `blink_rate: 0.2` — normal blink rate
- `quiz_accuracy: null` — no quiz completed yet (null is valid per type)
- `teachback_score: null` — same

In Sprint 3, `useLessonSocket` will accept a `getSignal` callback from `AttentionMonitor` and replace these defaults. The hook signature at that point will change — for now, hardcode is correct.

### Previous story learnings (from S1-06 + S0-07)

- `@testing-library/jest-dom` is NOT in vitest setup — don't use `toBeDisabled()`. Use `hasAttribute('disabled')` or check Booleans directly.
- `vi.useFakeTimers()` / `vi.advanceTimersByTime()` is the correct way to test `setTimeout`/`setInterval` in vitest.
- `beforeAll(() => { global.ResizeObserver = class { ... } })` not needed here (no Radix components).
- Import paths: `@hie/shared/types/ws` (not `@/lib/websocket/types`). The `@hie/shared` alias is configured in `vitest.config.ts`.
- Run `npx tsc --noEmit` from `apps/web/` (not repo root).

---

## Dev Agent Record

### Implementation Plan
- Task 1 first: extend PlayerStore with `cesScore`/`updateCes` — no tests, just tsc gate
- Task 2 RED: write LessonSocket tests against global WebSocket mock (vi.useFakeTimers for backoff)
- Task 3 GREEN: implement LessonSocket class — disconnect() nulls `ws.onclose` to prevent re-entrant handleClose
- Task 4 RED: write useLessonSocket hook tests with vi.mock for lessonSocket singleton and Supabase client
- Task 5 GREEN: implement useLessonSocket — async init for JWT, 5s interval, store callbacks
- Task 6: NEXT_PUBLIC_WS_URL env var added
- Task 7: full suite — 109/109 pass, zero tsc errors

### Debug Log
- MockWebSocket auto-firing `onopen` at `setTimeout(0)` caused `reconnectAttempts` to reset mid-backoff
  loop in tests 2f/2g. Fix: removed auto-`onopen` from MockWebSocket constructor; tests call `triggerOpen()`
  explicitly only when needed.
- `disconnect()` calling `ws.close()` re-entered `handleClose` via `ws.onclose`. Fix: null out
  `ws.onclose` before calling `ws.close()` in disconnect.

### Completion Notes
✅ 109/109 tests pass (16 new: 11 LessonSocket + 5 useLessonSocket hook; 93 existing)
✅ `npx tsc --noEmit` — zero errors
✅ All 8 ACs verified
✅ `lessonSocket.ts`: LessonSocket class + singleton export, exponential backoff 2^n×1000ms, max 5 attempts
✅ `useLessonSocket.ts`: async JWT fetch, 5s attention signal interval, store callbacks wired
✅ `player.machine.ts`: `cesScore` + `updateCes` added — all 25 existing store tests still pass
✅ `NEXT_PUBLIC_WS_URL=ws://localhost:8000` added to `.env.local`
✅ `lib/websocket/` mock layer untouched — no regressions in existing mock socket code

---

## File List

- `apps/web/src/lib/ws/lessonSocket.ts` — created
- `apps/web/src/hooks/useLessonSocket.ts` — created
- `apps/web/src/__tests__/lib/ws/lessonSocket.test.ts` — created
- `apps/web/src/__tests__/hooks/useLessonSocket.test.ts` — created
- `apps/web/src/stores/player.machine.ts` — modified (added cesScore + updateCes)
- `apps/web/.env.local` — modified (added NEXT_PUBLIC_WS_URL)

---

### Review Findings

> Code review run 2026-06-29. Layers: Blind Hunter · Edge Case Hunter · Acceptance Auditor. Dismissed: 4 (Bearer-subprotocol spec-mandated, `callbacks!` safe, `lib/websocket/` untouched, singleton-pattern spec-mandated).

**Decision-needed (must resolve before patches):**

- [x] [Review][Decision] D1: connect() signature — resolved: kept 3-arg, updated AC1 wording to match. No code change. [lessonSocket.ts:27]

**Patch findings:**

- [x] [Review][Patch] P1: Off-by-one in reconnect — DISMISSED (false positive): 5 retries made correctly per spec; `reconnectAttempts < maxAttempts` guard produces correct "max 5" behavior; test 2g verifies this [lessonSocket.ts:58-67]
- [x] [Review][Patch] P2: `connectionStatus` is stale — FIXED: added `onStatusChange?: (s: ConnectionStatus) => void` to `LessonSocketCallbacks`; `setStatus()` helper calls callback; hook uses `useState` wired to `onStatusChange` [useLessonSocket.ts:10, lessonSocket.ts:45]
- [x] [Review][Patch] P3: Old `WebSocket` not closed before new `connect()` — FIXED: defensive teardown at top of `connect()` nulls all handlers and closes old socket before creating new one [lessonSocket.ts:29-37]
- [x] [Review][Patch] P4: `getSession()` error swallowed silently — FIXED: `init()` wrapped in `try/catch`; empty token still connects (intentional per dev notes — server rejects, backoff runs, lesson continues) [useLessonSocket.ts:13]
- [x] [Review][Patch] P5: `onerror` handler never assigned — FIXED: `this.ws.onerror = () => this.handleClose()`; `handleClose` has `reconnectTimer !== null` guard to prevent double-schedule from onerror+onclose; timer callback resets `reconnectTimer = null` [lessonSocket.ts:50, 62, 67]
- [x] [Review][Patch] P6: `disconnect()` does not reset `connectionStatus` — FIXED: `this.connectionStatus = 'connecting'` added in `disconnect()` [lessonSocket.ts:85]
- [x] [Review][Patch] P7: Test cross-contamination — DISMISSED (false positive): `mockClear()` in `beforeEach` + `clearAllMocks()` in `afterEach` are sufficient; `vi.resetModules()` would break React instance across renderHook calls [useLessonSocket.test.ts]
- [x] [Review][Patch] P8: Interval fires before `onopen` — FIXED: interval callback guards `if (lessonSocket.connectionStatus !== 'connected') return` [useLessonSocket.ts:36]
- [x] [Review][Patch] P9: Trailing slash in `NEXT_PUBLIC_WS_URL` — FIXED: `.replace(/\/$/, '')` on `base` [lessonSocket.ts:41]

**Deferred:**

- [x] [Review][Defer] W1: `reconnectAttempts` reset on `disconnect()` loses backoff state — intentional for explicit disconnect; acceptable MVP behavior — deferred, pre-existing

---

## Change Log

| Date | Change |
|------|--------|
| 2026-06-29 | Story created — S1-07 Real WebSocket Client |
| 2026-06-29 | Implementation complete — 109/109 tests pass, zero tsc errors |
| 2026-06-29 | Code review complete — 7 patches applied, 3 dismissed (2 false positives + 1 spec-mandated), 1 deferred |
