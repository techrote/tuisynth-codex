# TRIO-013 prepass: DRIFT granular engine

## Reconciliation

- Issue #13 is open with no owner comments. Its dependencies, TRIO-003 and TRIO-004, are merged and green.
- `main` is clean at `28630a7afadc01900dcf1eaf16ae099b93a7c4f5`; the latest main CI is green.
- No open pull request duplicates this issue. The work branch will be `trio-013-drift-engine` from the reconciled `main`.
- The required DRIFT, audio-engine, charter, recovery, workflow and provenance documents were read before implementation.

## Design prepass

1. Keep DRIFT self-contained in `trio_drift`: a parameter registry, instrument, six polyphonic stream voices, bounded grain pool, source generator, formant processor, factory preset resources, and device-free tests. Use only `trio_kit` shared APIs; do not import another instrument.
2. Build the seeded two-second source bank at prepare time. On a `src.color` change, regenerate the bank from a dedicated deterministic source RNG in `on_block_boundary`; do not allocate work to another thread or rebuild on every parameter snapshot. Keep source generation/vector operations bounded and sanitize state if parameters are invalid.
3. Use a single global grain pool (capacity `gr.max`, clamped to the contract's 16–96 range). Each active note stream has its own seeded RNG. A stream present at the start of a 256-frame block draws one Poisson schedule for the whole block; event-split render segments partition that schedule, so adding a note event does not change an existing stream's random sequence. A stream created by a sample-offset note-on draws only for its active portion of that block, preventing pre-note grains. Pool overflow is accounted as dropped grains, not unbounded backlog.
4. Voice render advances the shared ADSR and submits its envelope and velocity to the scheduler. A grain captures its onset amplitude, source start, duration, pitch ratio and pan so it can finish after NoteOff. The pool renderer visits only active grains, vectorizes source interpolation/windowing/overlap-add for each grain, and performs no Python per-sample work. Process a grain across arbitrary host chunks by retaining absolute grain age and source phase; this is the basis for block-straddle equivalence tests.
5. Apply field controls at block boundaries: `field.x` blends the vowel target and source position, `field.y` scales density by 0.25–4 and raises source brightness, and a held gust uses a 300ms smoothed multiplier. Factory presets omit both map coordinates so the live cursor remains independent of the chosen sound. Wind has a dedicated seeded smooth-random signal; it modulates density/brightness and optionally adds a Q=25 moving howl band.
6. Implement the five exact vowel rows and linear morph, shift, Q, output mix, and explicit 20ms vowel smoothing. Use five stereo biquads with state preserved across blocks; compare filter response peaks against the contracted vowel table rather than relying on subjective listening.
7. Keep every parameter in the registry and demonstrate it is consumed in DSP or exposed as a shared control. Keep telemetry at or below 16 fields, and each vector bounded to 64 numeric values. Register the eight issue-named factory presets as package data; keep UI/skins for TRIO-014.

## Qualification focus

Implement deterministic unit tests for window shape and exact endpoints; exponential attack/release timing; Poisson counts over ten seconds; active-pool cap/drop accounting; grain timing/position/ratio/pan and cross-block continuity; vowel formant locations and morph/shift; field endpoints/density; gust attack/release; complete registry use; preset render safety and non-silence; and a bounded six-stream/96-grain throughput check. Run the repository's full device-free suite and clean-wheel checks after the focused DRIFT tests.

## Scheduling interpretation

The engine invokes `on_block_boundary` once per internal 256-frame block but may render voices and `process_bus` in smaller event-delimited segments. A voice active at the start of the block draws its schedule once for the full block; later event segments partition those arrivals without another Poisson draw. A voice created by an offset note-on draws once for the remaining active portion of that block, so it cannot spawn grains before it exists. This matches the renderer's event ordering while keeping each stream's schedule stable across unrelated event splits.

## Provenance

Codex desktop (GPT-6; exact configuration unavailable), Git/GitHub CLI, PowerShell and Python are used for reconciliation, prepass, implementation, qualification and review. Public external references are not needed for this contract-driven work.
