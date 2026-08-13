# Story 3-41 — Fix invalid `sarvam_voice_id` default (D67)

**Branch:** `sprint3/s3-41-fix-sarvam-voice-default` (from `main`).
**Owner:** Dev 1.
**Trigger:** L1 pre-flight check (`docs/LESSON-DELIVERY-TRACKER.md`) — flagged in an earlier
session, fixed now as a required pre-flight item before the L1 acceptance run spends real money.

## Context

`docs/handoffs/lesson-delivery-dev1.md` explicitly lists L1 pre-flight steps: check stale
processes, confirm the beta-access allowlist, land the L2 narration cap first. It does not
mention this defect because it wasn't found until a live Sarvam API call was made in an earlier
session of this sprint — but it belongs in the same pre-flight category: a config default that
silently breaks every real TTS call before L1 can run cleanly.

## The defect (D67)

`apps/api/app/config.py`'s `sarvam_voice_id` defaults to `"meera"` (set in Story 2-8, unchanged
since). A real, live call to `https://api.sarvam.ai/text-to-speech` with `speaker: "meera"`
returns:

```
400 invalid_request_error
"Speaker 'meera' is not recognized. Available speakers are: anushka, abhilash, manisha, vidya,
arya, karun, hitesh, aditya, ritu, priya, neha, rahul, pooja, rohan, simran, kavya, amit, dev,
ishita, shreya, ratan, varun, manan, sumit, roopa, kabir, aayan, shubh, ashutosh, advait, anand,
tanya, tarun, sunny, mani, gokul, vijay, shruti, suhani, mohit, kavitha, rehan, soham, rupali"
```

Because Sarvam's own error is `invalid_request_error` (not a 429/5xx), `with_retry`'s
classification correctly does **not** retry it — but that means every real lesson's TTS calls
would 400 immediately on the primary provider, then degrade through the fallback chain to Azure,
on 100% of segments, for 100% of lessons, silently. No error would ever surface to a caller
(the fallback chain is designed precisely to never hard-fail — PRD §14), which is exactly why
this is dangerous rather than merely broken: the pipeline would keep reporting success while
quietly paying Azure's rate instead of Sarvam's and never actually exercising the primary
provider this project chose (CLAUDE.md's locked TTS fallback chain: Sarvam Bulbul v2 → Azure TTS
→ Browser Speech).

If L1's acceptance run had been executed against the unfixed default, the first symptom would
have been a confusing "why is `tts_node`'s admin-visible provider field always `azure`, never
`sarvam`" during real-money spend — exactly the kind of silently-wrong-not-loudly-broken failure
`docs/SCALE-CONTRACT.md`'s one-line test exists to catch, even though this isn't a scale defect
in the Q1–Q6 sense — it's a plain config correctness bug, caught the same way: by actually
running the real call instead of trusting the stored default.

## The fix

Changed the default to `"anushka"` — verified via a second live call, not assumed:
`POST /text-to-speech` with `speaker: "anushka"` returned `200 OK` and a real, non-empty audio
payload (122,940 base64 characters).

`anushka` was chosen (over any of the other ~40 valid speakers) for consistency with this
project's existing Azure fallback default, `azure_tts_voice = "en-IN-NeerjaNeural"` — an Indian
English voice, matching TransformED's target market (CLAUDE.md's India-region migration
requirement, OpenStax-style Indian curricula target books). Sarvam's speaker list does not
document accent/locale per-name, so this is a reasonable-default choice, not a verified-identical
voice match — a future story can listen-test multiple candidates if voice quality becomes a
product concern; that is out of scope here, which is a config-correctness fix, not a voice
product decision.

## What this does NOT do

- Does not change `azure_tts_voice` (`"en-IN-NeerjaNeural"`) — already valid, unaffected.
- Does not change the fallback chain order or logic — Sarvam → Azure → Browser Speech is
  unchanged; this fix restores Sarvam's actual ability to serve as the *primary* provider it was
  always meant to be, rather than silently never being reachable.
- Does not touch `sarvam.py`'s tracing, retry, or circuit-breaker logic (Story 3-40's scope,
  separate branch).

## Scale & Load

1. **Unit of work & range.** One config field, one process-wide default. No per-request
   variance — this is a startup-time constant, not a runtime-scaled value.
2. **Fixed budgets vs variable input.** N/A with reason — a speaker name is not a budget that
   meets variable input; it either matches Sarvam's live speaker list or it doesn't, and the
   guard test below pins it to a value that's currently confirmed valid.
3. **Scope of the limit.** Per-deployment (one `SARVAM_VOICE_ID` env var / config default per
   Railway service). Overridable per-environment via env var if a future deployment needs a
   different speaker — no code change required to change it.
4. **Unbounded reads/writes.** None — a single string constant.
5. **Inherited caps re-derived.** This IS the re-derivation: `"meera"` was set once in Story 2-8
   and never re-verified against Sarvam's actual live API as their available-speaker list
   evolved. The new guard test (below) is what prevents this specific silent drift from
   recurring undetected.
6. **Concurrency.** N/A — a read-only config default, no check-then-act sequence.

## Verification

- Live call #1 (pre-fix): `speaker: "meera"` → `400 invalid_request_error`, full valid-speaker
  list captured verbatim in the D67 register entry.
- Live call #2 (post-fix): `speaker: "anushka"` → `200 OK`, real 122,940-char base64 audio
  payload confirmed non-empty.
- New test: `tests/unit/test_config_settings.py::test_sarvam_voice_id_default_is_a_documented_valid_speaker`
  — pins the default against the literal speaker list captured from Sarvam's own `400` response
  body (a copy-pasted real API response, not a hand-typed guess), so a future Sarvam API change
  that drops `"anushka"` from their roster fails this test instead of silently reintroducing
  D67's failure mode.
- Full relevant suite (`test_config_settings.py`) run clean, 0 regressions (see commit for exact
  count).
