# [TRIO-009] AURORA engine: spectral PADsynth

This GitHub issue is the autonomous execution prompt for **TRIO-009**. `AGENTS.md` is incorporated by reference and is mandatory, including reconciliation, branching, checkpoints, provenance, PR review, exact-head CI, merge, and post-merge verification.

## Depends on
TRIO-003 and TRIO-004 merged/green.

## Read first
1. `AGENTS.md`
2. `ATTEMPT.md`
3. `docs/programme/IMPLEMENTATION-PROGRAMME.md`
4. `docs/rag/12-AUTONOMOUS-WORKFLOW.md`
5. `docs/rag/13-BENCHMARK-PROVENANCE.md`
6. `docs/programme/issues/TRIO-009.md`
7. `docs/rag/06-AURORA-SPEC.md (Sound identity, DSP, Tests)`
8. `docs/rag/00-CHARTER.md (difference contract)`
9. `docs/rag/02-AUDIO-ENGINE-CONTRACT.md`
10. `docs/rag/11-LESSONS-FROM-RECOVERY.md`

## Objective
Implement AURORA's distinct spectral PADsynth engine, background table regeneration and factory presets with full offline qualification; no terminal UI yet.

## Required implementation
- AURORA parameter registry exactly matches the spec; all registered params have a real DSP path.
- Deterministic vectorized PADsynth table generation for seven zones, harmonic painting extras, Nyquist policy, cache and bounded memory.
- Debounced worker regeneration; block-boundary swap with click-safe crossfade; clean close/join.
- Voices: table playback/interpolation, stereo width/detune, amp/filter envelopes, filter modes, per-voice LFO modulation, shared chorus/delay/reverb bus and telemetry spectrum/levels.
- At least the eight named factory presets with distinct harmonic profiles and descriptions.

## Required tests and acceptance
- Registry/spec/parameter-usage coverage.
- Harmonic peak positions/bandwidth/seed magnitude-vs-phase behavior/Nyquist skips/table generation budget.
- Held-note pitch across low/mid/high notes, stereo correlation width bounds, filter/envelope/release.
- Live table regeneration step bound, finite output, worker joined.
- Every preset parses and renders finite/non-silent/below ceiling.
- Densest 8-voice performance regression.
- No waveguide/granular implementation in AURORA; CI green.

## Out of scope
AURORA terminal UI/skins (TRIO-010).

## Delivery
Complete the issue end-to-end. Open a PR titled `[TRIO-009] AURORA engine: spectral PADsynth` with `Closes #<this issue>`; include exact test evidence, RAG/contract changes, limitations and role-based provenance. Use a provider-internal independent review tier/configuration where available. Merge only when the exact reviewed head is current and every required automated check is green; verify `main` CI after merge. If interrupted, post the `AGENTS.md` checkpoint before ending.
