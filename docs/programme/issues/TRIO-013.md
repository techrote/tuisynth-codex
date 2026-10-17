# [TRIO-013] DRIFT engine: granular air and formant clouds

This issue is the autonomous execution prompt for **TRIO-013**. `AGENTS.md` is incorporated by reference and mandatory, including reconciliation, branching, checkpoints, provenance, PR review, exact-head CI, merge, and post-merge verification.

## Depends on
TRIO-003 and TRIO-004 merged/green.

## Read first
1. `AGENTS.md`
2. `ATTEMPT.md`
3. `docs/programme/IMPLEMENTATION-PROGRAMME.md`
4. `docs/rag/12-AUTONOMOUS-WORKFLOW.md`
5. `docs/rag/13-BENCHMARK-PROVENANCE.md`
6. `docs/programme/issues/TRIO-013.md`
7. `docs/rag/08-DRIFT-SPEC.md (Sound identity, DSP, Tests)`
8. `docs/rag/00-CHARTER.md`
9. `docs/rag/02-AUDIO-ENGINE-CONTRACT.md`
10. `docs/rag/11-LESSONS-FROM-RECOVERY.md`

## Objective
Implement DRIFT's distinct bounded granular engine over seeded air sources, morphing formant bank, wind/field performance controls and factory presets.

## Required implementation
- Seeded source bank: spectral-tilted noise, additive soft tone and breath source; regenerate only at safe block boundaries when source color changes.
- Grain windows hann/tukey/expodec/rexpodec with exact zero endpoints; bounded GrainPool and Poisson scheduling; at most gr.max active grains and bounded per-grain NumPy overlap-add, no per-sample loop.
- Shared six-stream/paraphonic note model, deterministic per-stream RNG, position/size/pitch/pan scatter.
- Five-band vowel/formant bank using the exact table/interpolation/shift/q/mix contract with smoothing.
- Wind/gust/howl and field.x/y/amount performance mapping including 300ms gust ramps.
- DRIFT parameter registry with every param used, telemetry capped/bounded, eight named presets.

## Required tests and acceptance
- Window shape/endpoints/expodec timing.
- Seeded Poisson spawn statistics over 10s; pool cap/drop accounting.
- Single-grain requested position/length/ratio/pan and block-straddle equivalence.
- Vowel A/I peak locations, morph and shift behavior.
- field.x endpoints A/U; field.y density scale; gust ramp/density behavior.
- Registry/spec usage; all presets finite/non-silent/below ceiling; densest 6-stream/96-grain performance.
- No waveguide/spectral-table implementation in DRIFT; CI green.

## Out of scope
DRIFT terminal UI/skins (TRIO-014).

## Delivery
Complete end-to-end. Open PR `[TRIO-013] DRIFT engine: granular air and formant clouds` with `Closes #<this issue>`; include exact tests, RAG changes, limitations and role-based provenance. Use a provider-internal independent review tier/configuration where available. Merge only when the exact reviewed head is current and all required automated checks are green; verify `main` CI. If interrupted, post the `AGENTS.md` checkpoint.
