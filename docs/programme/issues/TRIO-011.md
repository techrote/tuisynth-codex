# [TRIO-011] LOOM engine: waveguide strings, sympathetic bank and bodies

This issue is the autonomous execution prompt for **TRIO-011**. `AGENTS.md` is incorporated by reference and mandatory, including reconciliation, branching, checkpoints, provenance, PR review, exact-head CI, merge, and post-merge verification.

## Depends on
TRIO-003 and TRIO-004 merged/green.

## Read first
1. `AGENTS.md`
2. `ATTEMPT.md`
3. `docs/programme/IMPLEMENTATION-PROGRAMME.md`
4. `docs/rag/12-AUTONOMOUS-WORKFLOW.md`
5. `docs/rag/13-BENCHMARK-PROVENANCE.md`
6. `docs/programme/issues/TRIO-011.md`
7. `docs/rag/07-LOOM-SPEC.md (Sound identity, DSP, Tests)`
8. `docs/rag/00-CHARTER.md`
9. `docs/rag/02-AUDIO-ENGINE-CONTRACT.md`
10. `docs/rag/11-LESSONS-FROM-RECOVERY.md`

## Objective
Implement LOOM's physically inspired waveguide string engine with pluck/bow excitation, sympathetic bank, bodies, strum model and factory presets.

## Required implementation
- Exact delay-chunked extended Karplus-Strong/waveguide recursion with fractional delay, brightness/loss and T60 behavior; retain history across retargets with click-safe pitch changes.
- Seeded PluckExciter and documented linear BowExciter approximation with specified envelope/flutter.
- 12-string sympathetic bank with scale/drone/chord tunings, quiet-only retune and no return path into main strings.
- Modal body resonator types with documented artistic approximation and size scaling.
- StrumModel default tuning/chord spread/crossing velocity and InstrumentEvent handling for pluck/bow/mute/strum.
- LOOM registry with all params used, dynamic 8-pluck/4-bow voice limit, telemetry and at least eight named presets.

## Required tests and acceptance
- Chunked waveguide equals slow per-sample reference within tolerance.
- Fundamental tuning within ±5 cents across specified MIDI range; T60 within ±25%.
- Pitch retarget click bound, excitation determinism/envelopes/comb behavior.
- Sympathetic in-tune energy advantage, zero-mix no-return behavior, quiet retune.
- Body modal peaks/size scaling; strum chord/default/velocity/spread.
- 20s max-decay/brightness/coupling finite and bounded before master; all presets finite/non-silent/below ceiling; performance gate.
- No spectral/granular implementation in LOOM; CI green.

## Out of scope
LOOM UI/skins (TRIO-012).

## Delivery
Complete end-to-end. Open PR `[TRIO-011] LOOM engine: waveguide strings, sympathetic bank and bodies` with `Closes #<this issue>`; include exact tests, RAG changes, limitations and role-based provenance. Use a provider-internal independent review tier/configuration where available. Merge only when the exact reviewed head is current and all required automated checks are green; verify `main` CI. If interrupted, post the `AGENTS.md` checkpoint.
