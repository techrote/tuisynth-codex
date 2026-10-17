# [TRIO-004] Kit DSP building blocks

This GitHub issue is the autonomous execution prompt for **TRIO-004**. `AGENTS.md` is incorporated by reference and is mandatory, including reconciliation, branching, checkpoints, provenance, PR review, exact-head CI, merge, and post-merge verification.

## Depends on
TRIO-001 merged/green. May proceed independently of TRIO-002/003, but integrate against current main.

## Read first
1. `AGENTS.md`
2. `ATTEMPT.md`
3. `docs/programme/IMPLEMENTATION-PROGRAMME.md`
4. `docs/rag/12-AUTONOMOUS-WORKFLOW.md`
5. `docs/rag/13-BENCHMARK-PROVENANCE.md`
6. `docs/programme/issues/TRIO-004.md`
7. `docs/rag/02-AUDIO-ENGINE-CONTRACT.md (Fixed numbers, DSP building blocks, Performance)`
8. `docs/rag/11-LESSONS-FROM-RECOVERY.md`

## Objective
Implement the block-vectorized stateful DSP units all instruments will share.

## Required implementation
Implement ADSR, RBJ biquad lp/bp/hp/peak, LFO shapes including seeded random/S&H, fractional chronological DelayLine, Chorus, StereoDelay, Reverb and parameter smoothing. State carries across arbitrary chunks <= internal block. Production code avoids unbounded/per-sample Python loops. Delay chronology and reverb stability rules in TRIO-ENGINE are binding.

## Required tests and acceptance
- Every unit: one-shot vs randomized chunk processing continuity.
- ADSR timing/retrigger click bound.
- Biquad cutoff/centre response and high-Q finite stability.
- LFO known phase values/rate/seed repeatability.
- Delay chronological ramp regression, impulse location, fractional interpolation, feedback decay.
- Chorus delay range; ping-pong channel behavior; extreme feedback finite.
- Reverb impulse tail finite/decays; mix=0 identity.
- Generous aggregate DSP performance regression.
- Full matrix CI green.

## Out of scope
Instrument-specific spectral/waveguide/granular DSP.

## Delivery
Complete the issue end-to-end. Open a PR titled `[TRIO-004] Kit DSP building blocks` with `Closes #<this issue>`; include exact test evidence, RAG/contract changes, limitations and role-based provenance. Use a provider-internal independent review tier/configuration where available. Merge only when the exact reviewed head is current and every required automated check is green; verify `main` CI after merge. If interrupted, post the `AGENTS.md` checkpoint before ending.
