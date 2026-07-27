# Sprint 2 (Dev 4) — Validation & Unit-Testing Audit Report

**Prepared for:** Engineering Manager / HR
**Prepared by:** Dev 4 (WebSocket · JWT · 7-State Tutor · Redis Buffer · Interventions)
**Date:** 2026-07-24
**Branch under audit:** `dev4/s2` ("master sprint 2") · HEAD `696690f` (post-remediation)
**Scope:** Sprint 2 Dev-4 deliverables only (tracker tasks `full_state_machine`, `all_transitions`, `quizzing_teachback_flow`, `session_restore`, `intervention_selection`, `ws_message_types_final`) + Story 4-18 (`state_change` broadcast).
**Method:** Evidence-based (BMad Correct Course → story-first → dev-story → 3-layer adversarial code review). Every status is backed by an executed command and its captured output. No task marked green on claim alone.

---

## 1. Executive Summary

| Metric | At audit start (`b390788`) | After remediation (`696690f`) |
|--------|:--:|:--:|
| Dev-4 test files green | 5 / 7 | **7 / 7** |
| Failing Dev-4 tests | **19** | **0** |
| Passing Dev-4 tests | 110 | **129** |
| Tasks with 100% passing evidence | 5 / 6 core | **6 / 6 core (+ bonus 4-18)** |
| **Overall Sprint 2 implementation** | ~95% | **100% (core)** |

**Headline:** The Sprint 2 tutor state-machine work was feature-complete but the "master sprint 2" branch shipped with **19 failing Dev-4 tests** — contradicting the tracker's earlier "298 passed / all green" claim. The audit root-caused all 19 to **two test-fixture defects** (not product bugs), which were fixed under **Story 4-22** and merged into `dev4/s2`. The branch is now **129 passed, 0 failed**, verified per file.

---

## 2. Environment & Reproducibility

| Item | Value |
|------|-------|
| OS / Python | Windows 11 · CPython 3.13.14 · pytest 9.1.1 |
| Interpreter | `apps/api/.venv` |
| Deps repaired for a faithful run | `.venv` was missing `langfuse`, `sentry-sdk`, `openai` → installed `langfuse==4.12.0`, `sentry-sdk[fastapi]==2.63.0`, `openai==2.44.0` (per `apps/api/uv.lock`) |
| Env vars | Set at shell to match CI before pytest (required — `test_tutor_service.py` calls `compute_ces()` at import/collection time) |

```bash
cd apps/api
python -m pip install "langfuse==4.12.0" "sentry-sdk[fastapi]==2.63.0" "openai==2.44.0"
export SUPABASE_URL=http://localhost:54321 SUPABASE_ANON_KEY=test SUPABASE_SERVICE_ROLE_KEY=test \
       SUPABASE_JWT_SECRET=test-secret-at-least-32-chars-long!! REDIS_URL=redis://localhost:6379 \
       OPENAI_API_KEY=test SARVAM_API_KEY=test HEYGEN_API_KEY=test \
       LANGFUSE_PUBLIC_KEY=test LANGFUSE_SECRET_KEY=test
```
> **Evidence placeholder [E-ENV]:** `[screenshot: pip install + pytest --version]`

---

## 3. Per-File Test Results — before → after

**Command:**
```bash
for f in test_tutor_graph test_tutor_service test_websocket_session test_lesson_ready_pubsub \
         test_lesson_ready_integration test_ws_load_test test_auth; do
  python -m pytest tests/$f.py -p no:cacheprovider --tb=no -q | tail -1
done
```

| Test file | Before (`b390788`) | After (`696690f`) |
|-----------|:--:|:--:|
| `test_tutor_graph.py` | 44 passed ✅ | **44 passed ✅** |
| `test_tutor_service.py` | 13 failed / 14 passed ❌ | **27 passed ✅** |
| `test_websocket_session.py` | 29 passed ✅ | **29 passed ✅** |
| `test_lesson_ready_pubsub.py` | 7 passed ✅ | **7 passed ✅** |
| `test_lesson_ready_integration.py` | 5 passed ✅ | **5 passed ✅** |
| `test_ws_load_test.py` | 7 passed ✅ | **7 passed ✅** |
| `test_auth.py` | 6 failed / 4 passed ❌ | **10 passed ✅** |
| **Total** | **19 failed / 110 passed** | **0 failed / 129 passed** |

> **Evidence placeholders:** `[E-BEFORE]` red per-file loop · `[E-AFTER]` green per-file loop (129 passed).

---

## 4. Task-by-Task Validation (final)

| Task | AC (summary) | Key tests | Status | Impl % |
|------|--------------|-----------|:------:|:--:|
| **4-7 full_state_machine** | IDLE→TEACHING→INTERVENING→TEACHING no errors | `test_full_intervention_cycle_step_through`, `test_fatigue_fires_once_then_blocked`, +10 | ✅ PASS | 100% |
| **4-5 all_transitions** | one test per transition + guard-blocked cases | 14 transition tests + 4 guard-blocked | ✅ PASS | 100% |
| **4-6 quizzing_teachback_flow** | step-through + never-interrupt-TEACH_BACK | `test_quiz_teachback_step_through`, `test_*_blocked_during_teach_back`, WS E1–E4 | ✅ PASS | 100% |
| **4-9 session_restore** | reconnect receives current state (Redis-read only) | WS F1–F3, F5–F7 (incl. 7-state parametrized) | ✅ PASS | 100% |
| **4-8 intervention_selection** | Redis-reads-only delivery; message reaches client | `test_intervention_delivers_tutor_intervene_message`, `test_intervention_no_delivery_on_cache_miss` (**now green**) | ✅ PASS | 100% |
| **4-10 ws_message_types_final** | Dev 2 signs off on WS contract | `docs/ws-message-contract.md` (doc + sign-off) | ⚠️ Doc complete; **Dev 2 sign-off pending** | 90% |
| **4-18 state_change (bonus)** | broadcast on real transitions, silent on no-op | `test_state_change_broadcast_*` (×3) | ✅ PASS | 100% |

**Note on 4-8:** the two delivery tests that proved "message reaches the client" were the ones failing at audit start (fixture defect); they are now green, so the AC is genuinely verified. **4-10** is the only non-100% core task, gated solely on an external Dev 2 sign-off (no code/test gap).

---

## 5. Remediation — Story 4-22 (what was fixed and how)

All 19 failures were **test-fixture defects**; production code (`compute_ces`, JWT verify) was correct throughout. Source under `apps/api/app/` was **not touched** (verified).

| Issue | Root cause | Fix | Result |
|-------|-----------|-----|--------|
| **ISSUE-1** (13 tests) | `_setup` mock `Settings` set only `ces_threshold`; real §11 `compute_ces()` read `ces_weight_*` off a MagicMock → `TypeError` at `service.py:127`. Also: unstubbed `redis.get` fed an AsyncMock into `json.loads` on the 4-8 path; a stale `assert result.ces == 0.5` (old stub). | Added `_settings_mock()` helper with config-default weights (0.35/0.25/0.20/0.12/0.08); stubbed `redis.get→None`; dispatch mock returns a no-message INTERVENING dict; replaced the stale assertion with `_EXPECTED_CES` **plus a hard-coded `pytest.approx(75.733)` anchor** (code-review-driven). | 13 → **0 failing** (27 passed) |
| **ISSUE-2** (6 tests) | `test_auth` minted tokens with <32-byte secrets → PyJWT ≥2.10 `InsecureKeyLengthWarning`, promoted to error by `filterwarnings=error`. | Padded `_SECRET` (36 B) and the wrong-secret literal (32 B); both still distinct so the signature-mismatch 401 is still genuinely proven. | 6 → **0 failing** (10 passed) |

**Process:** BMad **Correct Course** (branch strategy locked: fix on `dev4/s2`, defer `main` integration) → **story-first** commit (Story 4-22) → **dev-story** implementation → **3-layer adversarial code review** (Blind Hunter, Edge Case Hunter, Acceptance Auditor). Review verdict: **APPROVED** — no security regression, no weakened/vacuous tests, all 5 ACs met; one finding (self-referential CES assertion) patched with a concrete literal anchor.

---

## 6. Issues Register (final)

| ID | Severity | Status | Note |
|----|----------|:------:|------|
| ISSUE-1 | High | ✅ **RESOLVED** | Story 4-22 (mock weights, redis.get, dispatch dict, anchor) |
| ISSUE-2 | Med | ✅ **RESOLVED** | Story 4-22 (≥32-byte secrets) |
| ISSUE-3 | Med | ✅ **RECONCILED** | Tracker's "298 passed" was overstated; branch is now genuinely 129/0 |
| ISSUE-ENV | Med | ⚠️ Open (CI hygiene) | `.venv`/CI missing pinned deps; module-level `compute_ces()` at collection; CI exports stale `ELEVENLABS_API_KEY` not `SARVAM_API_KEY` |
| ISSUE-4 | High | ⚠️ Open (integration) | `main` CI red at the **Ruff lint** gate — a `main`-side blocker, out of scope for `dev4/s2` test results |
| ISSUE-SEC | Info | ⚠️ Open (MVP) | `/ws/{session_id}` unauthenticated; documented MVP limitation, hardening tracked for Sprint 3 |

---

## 7. Production-Readiness Assessment

**Branch `dev4/s2` test-health: GREEN and reportable.** All Sprint 2 Dev-4 ACs are met and test-verified (6/6 core + bonus), with the sole exception of the external Dev 2 sign-off on 4-10.

**Full production-readiness: still gated on integration concerns (outside this report's test scope):**
1. `main` CI is red at the Ruff lint gate (ISSUE-4) — must be greened before any Sprint-2 merge.
2. `dev4/s2` is **135 commits behind `main`** (4 ahead) — not fast-forward mergeable; integration strategy (rebase vs cherry-pick of Story 4-18) is deferred per `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-24.md`.
3. Unauthenticated WebSocket endpoint (ISSUE-SEC) — acceptable for MVP demo, not for real students.
4. Live load/reconnect ACs are proven locally/in-harness only; a live (India-region) deploy is the Sprint-3 prerequisite for real-server validation.

**Recommendation:** the Sprint-2 branch is now honest-green and ready to report. Integration to `main` is a separate, sequenced follow-up (green `main` lint → cherry-pick Story 4-18 → re-validate).

---

## 8. Commands Reference

```bash
# Green verification (§3 after-column)
cd apps/api && <env exports from §2>
python -m pytest tests/test_tutor_graph.py tests/test_tutor_service.py tests/test_websocket_session.py \
  tests/test_lesson_ready_pubsub.py tests/test_lesson_ready_integration.py tests/test_ws_load_test.py \
  tests/test_auth.py -p no:cacheprovider -q          # -> 129 passed

# Branch facts
git rev-list --left-right --count main...dev4/s2      # -> 135  5  (after the 4-22 merge)
gh run list --branch main --limit 6                   # -> main CI failure (Ruff lint gate)
```
> **Evidence placeholders:** `[E-AFTER]` 129-passed console · `[E-REVIEW]` code-review APPROVED summary · `[E-CI]` red `main` run.

## 9. Honest Caveats

- No live server / Redis / OpenAI was run; results are unit/integration tests with mocked I/O. Load-test (50 concurrent) and reconnect-under-fault ACs are proven by the local harness/`--self-test`, not a deployed API.
- No `curl` against live endpoints — the WebSocket endpoint is not HTTP-GET testable; the tutor REST endpoints are 501 stubs pending a running server.
- Results reflect `dev4/s2` @ `696690f`. The `main`-side lint failure and integration strategy are explicitly out of this report's scope.
