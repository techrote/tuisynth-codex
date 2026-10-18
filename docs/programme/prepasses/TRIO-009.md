# TRIO-009 prepass

## Reconciliation

- Issue #9 is open without owner comments. Its dependencies TRIO-003 and TRIO-004 are merged as PRs #20 and #21; post-TRIO-008 `main` is green at `99490af9d3eba7f569f81b6b7ca7ffa319066376` (CI run `39088531335`).
- No open duplicate PR exists. Branch `trio-009-aurora-padsynth` starts from the green `main` revision.
- AURORA currently contains only its versioned CLI stub and no instrument, registry, data assets or tests beyond version output. `trio_kit` supplies the block engine, bounded event queue, stable note-id voices, seeded RNG, master safety bus, envelopes, RBJ filters, LFOs and stereo effects.
- AURORA's complete synthesis and acceptance contract is in `docs/rag/06-AURORA-SPEC.md`; its eight factory sounds, spectral controls and seven octave zones belong only to AURORA. Shared mechanics remain in `trio_kit`.

## Integration decisions

- The engine currently invokes `process_bus` once per event-delimited segment, so a table swap there could occur mid-block. Add an optional instrument `on_block_boundary(params)` hook after queued params/extras apply and before any voices or sample-offset events render. This is the point where AURORA may commit a pending table set.
- Generate seven C1..C7 stereo tables with the specified 2^18 FFT size, bounded Gaussian windows around each partial, fixed seed-derived phases, skipped partials above 0.45 of sample rate, deterministic Parseval RMS normalization and float32 output. Hash sample rate, all seven zones, spectral parameters and padded harmonic profile for a bounded two-set cache. RMS normalization is phase independent so changing `spec.seed` changes phase without changing the magnitude spectrum.
- One worker owns regeneration. Requests replace pending and not-yet-committed state and restart the 150 ms debounce. The worker does not begin another table set during a live 50 ms swap; active + pending (or old + new during the swap) are the only retained sets. `close()` signals and joins the worker and clears the cache.
- Voices read the nearest lower octave table with linear wrap interpolation and a frequency/base-frequency phase step. Every voice keeps its own phase and envelopes; the instrument owns shared effects, spectral state and telemetry. Tables remain live during regeneration, with per-sample crossfade weights over 50 ms.
- Keep `--render` and `--selftest` device-free. They may start the shared instrument worker, but must wait for the requested tables before rendering and close/join the worker before returning.

## Qualification plan

- Test registry keys, kinds, ranges/defaults, extras padding/validation, and usage coverage for every registered control.
- Test spectral peaks and bandwidth, equal-magnitude/different-phase seed behavior, Nyquist skips, determinism, and the seven-zone/64-harmonic generation budget.
- Test held-note pitch across zone boundaries and low/mid/high notes; width/correlation at 0 and 1; all filter modes, modulation targets, ADSR stages, and release.
- Regenerate while voices sound: finite output, bounded block step, eventual new table, and worker joined on close. Exercise preset-driven table requests at the block hook.
- Render every factory preset for two seconds; test the densest eight-voice path with a generous regression bound.

## Contract changes

- The block-boundary callback is a new optional engine integration point needed to meet AURORA's swap guarantee. Document its call order in `docs/rag/02-AUDIO-ENGINE-CONTRACT.md`; preserve all existing instruments by making the callback optional.
- Shared presets gain an optional bounded description for the named AURORA factory sounds. `InstrumentSpec` now carries instrument polyphony, CLI seed and extras validation so the common shell can serve AURORA without importing its implementation.
- Shared `Reverb` gains normalized damping from 0..1 mapped to a 18 kHz..45 Hz cutoff; this is needed by the exact AURORA registry and is documented in the audio contract.

## Qualification findings

- On Python 3.12.10 / NumPy 2.4.3 / SciPy 1.17.1, all seven 2^18 tables at 64 partials stayed below the 10 s acceptance guard; the dense eight-voice 48 kHz offline regression stayed below its 15 s guard.
- An offline preset change can supersede a worker-produced table before the next audio boundary. Invalidating that invisible pending set when the newer request arrives avoids blocking `--render` while preserving block-only commits.
- Voice review caught a scalar phase-step path when pitch LFO was not selected; frequency samples are now broadcast across the block. Detuned right-channel playback uses its own phase accumulator, and reused voices reset filter/LFO state.
- FFT review also fixed the real-only DC/Nyquist phase bins; leaving random complex phases there changed endpoint magnitudes between seeds because `irfft` discards their imaginary components.
