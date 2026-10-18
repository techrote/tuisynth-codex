# TRIO-010 prepass: AURORA app

## Reconciliation

- Issue #10 is open, has no owner comments, and depends on TRIO-008 and TRIO-009.
- TRIO-008 is merged with green main verification; TRIO-009 merged as `8fc7470` and its post-merge matrix run `39090699216` is green.
- No duplicate open PR exists. Work starts from the verified `main` commit in branch `trio-010-aurora-app`.
- The full issue `Read first` set was read, including the AURORA UI specification, charter/difference contract, UX contract, and skin contract.

## Codebase findings

- `trio_kit.shell.InstrumentSpec` already provides instrument drawing, widgets, screen callbacks, packaged skin/preset roots, and global F2-F5 dispatch. The common shell owns MIDI, global overlays, preset handling, piano, lifecycle, and shared CLI.
- AURORA currently supplies only its engine and preset assets. Its UI can be added in an instrument-owned module without importing LOOM or DRIFT.
- `CanvasApp` and `HeadlessApp` route real SGR input through capture-aware hit regions; a painter widget should be one captured widget whose handler interpolates across all bars crossed during drag.
- AURORA harmonics extras are changed through a lock-protected `set_extras` path which debounces table creation on the instrument worker. This is safe for UI callbacks, but shared shell dirty-state should account for extras so the painter's changes are visible and saved correctly.
- The shared piano currently uses a fixed two-octave/42-cell rectangle. AURORA needs configurable octave count and height to span most of the terminal while preserving existing instrument defaults.
- `SkinLibrary` includes the immutable `mono` fallback automatically. AURORA should package only its three colorways, each with every required semantic role, a single-cell density ramp, aurora colour ramp and AURORA-specific logo/art.
- Shared snapshots currently accept only common overlay names. AURORA's PLAY/SHAPE golden screens need named F2-F5 snapshot selection without changing other instruments' defaults.
- `Engine.telemetry().instrument` carries AURORA voice RMS, harmonic peak/centroid and table readiness. Live waterfall intensity can therefore remain silent without active voices and derive its frozen, deterministic snapshot from preset harmonics rather than wall-clock time.

## Implementation and qualification plan

1. Add an AURORA-specific controller/drawing module, tab selection, harmonic painter widget, and telemetry waterfall with an explicit deterministic freeze mode for snapshots.
2. Expose all required registered controls on PLAY, SHAPE and SPACE; LIBRARY will direct into the shared preset/skin libraries while showing AURORA's own assets.
3. Add three packaged AURORA TOML skins, with `mono` retained as the built-in fourth option.
4. Add small shared-shell extension points only where required for safe extras dirty tracking, AURORA's wide piano, named screen snapshots, and screen-specific header/footer tips.
5. Add headless input tests, golden snapshots for both required sizes/screens/skins, zero-warning skin loading, CLI/package smoke tests, and worker cleanup checks. Keep all tests device-free.

## Implementation findings

- `EngineTelemetry` previously retained only scalar values; AURORA's live waterfall therefore
  had no path for its generated 64-band table magnitude. The shared telemetry snapshot now
  accepts immutable, finite numeric vectors of at most 64 entries while retaining its 16-field
  cap and rejecting mutable or oversized vectors.
- The existing demo's 80x24 piano golden is the compatibility check for shared piano geometry.
  AURORA sets its wider, shorter dimensions explicitly; other instruments retain the existing
  seven-row default.
- The compact 80x24 PLAY layout reserves exactly three rows for waterfall history, while the
  100x30 layout reserves four. Frozen snapshot labels no longer depend on the asynchronous
  table worker's readiness timing.
- Library list movement applies a preset preview and skin preview immediately. Headless tests
  exercise both selection callbacks; user interaction remains device-free.
