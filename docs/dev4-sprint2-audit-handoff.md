# Dev 4 Handoff: Sprint 2 Audit Findings — Tutor FSM / WebSocket (from the 360° Audit)

**From:** Dev 1 (developer1-cybersmith)
**To:** Dev 4 (WebSocket handlers / JWT / tutor FSM / interventions owner)
**Date:** 2026-07-27
**Source:** `docs/reports/sprint2-360-audit-2026-07-27.md` + `docs/reports/sprint2-360-reaudit-2026-07-27.md`
**Severity:** CRITICAL — this blocks Sprint 3 kickoff. The tutor state machine and CES pipeline have never received live traffic and cannot be validated for the India-region migration/load-test until they do.

---

## TL;DR

The 7-state FSM, CES computation, and Redis-backed guard rules are all implemented and unit-tested — but the WebSocket layer has two real defects that mean none of it has ever run against a live client:

1. **`state_change` is never broadcast on a real transition** — only on reconnect, and always as a no-op snapshot (`from == to`).
2. **CES/attention processing isn't gated to the TEACHING state**, so a stray signal during CHECKING_IN/QUIZZING silently forces the FSM back to TEACHING.

Plus three smaller items: a stale `ws.ts` contract field, two unimplemented REST stubs, and an unrelated auth cleanup decision that landed in your module by association.

Separately (Dev2's side, FYI, not your action item): the frontend never opens the socket at all today. Once Dev2 mounts `useLessonSocket`, both of your fixes below become immediately observable in the live player — worth sequencing your fixes to land before or alongside their wiring work, not after.

---

## 1. `state_change` Never Broadcasts a Real Transition (CRITICAL)

**Evidence:** The only `state_change` send site in the entire backend is `ConnectionManager.connect()`'s reconnect branch (`apps/api/app/core/websocket.py`) — it reads a single `restored` state from Redis and sends it with `from_state == to_state`, i.e. always a snapshot, never a genuine transition. `dispatch_event()` and all 7 node functions in `graph.py`/the tutor state machine persist the new state to Redis correctly but never call `manager.send(...)` afterward. `tutor/service.py` only ever broadcasts `tutor_intervene`, never `state_change`.

The frontend side is not the problem here — `useLessonSocket.ts` has a correct, already-tested handler waiting to consume real `state_change` frames. It's simply never fed one.

**Fix:** add a `manager.send(session_id, {type: 'state_change', payload: {from_state, to_state, ...}})` broadcast inside `dispatch_event()` (or in each node, whichever fits your architecture better) whenever `current_state` actually changes. Guard it so the existing reconnect-sync path doesn't double-fire a broadcast on top of its own snapshot send.

---

## 2. CES/Attention Not Gated to TEACHING State (HIGH)

**Evidence:** `process_attention_signal()` computes CES and unconditionally dispatches `distraction_detected`, with no check of the session's current `tutor_state`. `route_from_checking_in` and `route_from_quizzing` both fall through to `return "teaching"` for any event they don't explicitly recognize — meaning a stray attention signal arriving while a student is legitimately in CHECKING_IN or QUIZZING silently teleports the FSM back to TEACHING mid-quiz. Only `route_from_teach_back` is correctly guarded against this today (per PRD §10: "CES monitoring ONLY active in TEACHING state").

Notably, `lessonSocket.ts` on the frontend already has a code comment documenting awareness of this exact hazard for `session_start` resends — the frontend team already suspected the backend might have this gap.

**Fix:**
1. Add an explicit guard in `process_attention_signal` — only dispatch `distraction_detected` when `tutor_state == TEACHING`.
2. Change `route_from_checking_in`/`route_from_quizzing`'s unguarded fallthrough to return the *current* state (a no-op) instead of `"teaching"`, matching the pattern `route_from_teach_back` already uses correctly.

---

## 3. Frozen `ws.ts` Contract Drift — Stale `ces` Field (HIGH, needs a 4-dev PR)

**Evidence:** `packages/shared/types/ws.ts`'s `AttentionAckMessage` still types the payload as `{session_id: string; ces: number}`. The backend's actual frame (post the PR#91 CES-leak fix, `apps/api/app/core/websocket.py`) is `{session_id, status: 'ok'}` — with an explicit "PRD §18: never expose raw clinical/CES scores to the client" comment. `ces` is never sent. No runtime break today (the frontend handler is a no-op either way), but the frozen contract is currently lying about what's on the wire.

**Fix:** update the frozen contract to `{session_id: string; status: 'ok'}`. This needs the standard 4-dev-reviewed contract PR per CLAUDE.md §16 — small change, but frozen is frozen.

---

## 4. Tutor REST Stubs Still 501 (HIGH, no urgency — no caller exists)

`GET /session/{id}/state` and `POST /intervene` both unconditionally `raise HTTPException(501)` with TODO comments pointing at the service layer / state machine, neither implemented. No frontend caller exists for either yet, so nothing is actively broken — but nothing can be built against them either.

**Also worth deciding before you implement `get_session_state`'s body:** its response model (`TutorSessionState`) currently declares a raw `ces_score: float` with no role/ownership gating beyond `CurrentUser` (any authenticated user). Per PRD §18, that would leak a raw clinical score to any authenticated caller the moment the 501 is filled in. Either drop `ces_score` from the response (admin-only variant instead) or add an explicit role/ownership check before implementing the body — whichever fits, just don't ship the 501→200 flip without deciding this first.

---

## 5. Auth Stubs — Decommission or Finish (HIGH, own-goal cleanup, not core FSM work)

Unrelated to the FSM/WS work above, but flagged in your module's general area since JWT middleware is yours: `apps/api/app/modules/auth/router.py`'s `/signup`, `/signin`, `/onboarding/complete` are all 501 stubs. Only `GET /me` (echoing the JWT payload) is real. The frontend already bypasses all three by calling the Supabase Auth SDK directly (`SignInForm.tsx`/`SignUpForm.tsx`), and the real onboarding-completion path is a completely different, fully-working endpoint (`assessment/router.py`'s `/onboarding/submit`, with Redis idempotency) — so `/onboarding/complete` here is genuinely orphaned dead code, not just unfinished.

**Decision needed:** either decommission all three (Supabase SDK + `/onboarding/submit` already cover the real flows) and remove the dead 501s/TODOs, or — if server-side profile-row provisioning on signup was actually intended and just never got built — implement it and update `SignUpForm.tsx` to call it. Whichever way, document the decision so this doesn't get re-flagged in the next audit as an unfinished stub when it might be intentionally orphaned.

---

## 6. Session-Identity Coordination (MEDIUM — with Dev2)

`usePlayerStore.loadLesson()` (Dev2's file) generates `sessionId` client-side via `crypto.randomUUID()`, with no round-trip to any backend session-creation call — your `/ws/{session_id}` endpoint accepts whatever it's handed with no server-side validation or registration. Currently moot since the socket is never opened at all (see Dev2's handoff), but worth agreeing on a contract before they mount it: either your side mints `session_id` via a REST "start session" call the client hits before connecting, or the client-generated UUID gets registered/validated over REST first. Either works — just needs to be one decision between you and Dev2, not two independently-built assumptions.

---

## Files Involved

| File | Action Needed |
|------|----------------|
| `apps/api/app/core/websocket.py` or `apps/api/app/modules/tutor/service.py` (wherever `dispatch_event` lives) | Broadcast real `state_change` on every transition |
| `apps/api/app/modules/tutor/service.py::process_attention_signal` | Gate CES dispatch to `TEACHING` state only |
| `apps/api/app/modules/tutor/state_machine/*` (`route_from_checking_in`, `route_from_quizzing`) | Fix unguarded `"teaching"` fallthrough |
| `packages/shared/types/ws.ts` | Update `AttentionAckMessage` — needs 4-dev PR |
| `apps/api/app/modules/tutor/router.py` | Implement or formally remove `get_session_state`/`trigger_intervention` |
| `apps/api/app/modules/auth/router.py` | Decommission or implement `/signup`/`/signin`/`/onboarding/complete` |
| (coordination only) `apps/web/src/store/usePlayerStore.ts` | Session-identity contract with Dev2 |

---

## Reference

- `docs/reports/sprint2-360-audit-2026-07-27.md` — original full audit
- `docs/reports/sprint2-360-reaudit-2026-07-27.md` — re-verification, confirms all of the above unchanged
- `docs/ws-message-contract.md` — the existing WS contract doc, needs updating alongside the `ws.ts` fix
- `docs/dev2-sprint2-wiring-handoff.md` — Dev2's corresponding action item (mounting `useLessonSocket`)
