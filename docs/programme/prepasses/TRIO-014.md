# TRIO-014 prepass: DRIFT weather field

## Reconciliation

- Issue #14 is open, has no owner comments, and depends on TRIO-008 and TRIO-013.
- Both dependencies are merged; `main` is `366a506b54f9f61173229a2a85e47c56f8f3b0d9` and its post-merge CI is green.
- No open PR or duplicate branch for TRIO-014 exists in this attempt.
- The local checkout was clean before branching. Work is on `trio-014-drift-app`, created from current `main`.

## Findings

- DRIFT currently has only its engine, parameters, presets and a version/preset-list CLI. The shared `trio_kit.cli.run_cli` and `InstrumentSpec` already provide the shell, offline render, self-test, skin selection, snapshots and F-key screens required by the issue.
- The shell draws instrument widgets after the common frame, supports zero-based SGR pointer capture, and keeps the shared piano/footer layout independent of instrument widgets. A full-width weather-map widget can therefore draw behind focused grain/air/library HUD widgets while keeping the keyboard strip visible.
- DRIFT already reports grain pan but its pool snapshot and telemetry omit per-grain pitch, amplitude and age and cap the rendered snapshot at 64. The supported pool capacity is 16..96. Exact particle representation at the supported maximum requires synchronised per-grain telemetry vectors and snapshots up to 96.
- `EngineTelemetry.instrument` currently accepts vectors up to 64. TRIO-014 will extend this documented, immutable numeric-vector limit to 96 so the map can represent all telemetry grains without weakening the 16-field top-level bound or accepting arbitrary arrays.
- The shared `mono` skin is immutable and reserved. DRIFT will package three instrument-owned TOML factory skins (`squall`, `desert-haze`, `monsoon`) and use mono as the fourth option, with instrument-specific field glyphs and semantic age/isobar ramps.

## Implementation and qualification plan

1. Add a DRIFT-only UI adapter with a seeded, slowly drifting value-noise isobar layer, x/y storm cursor, vowel/weather labels, captured drag/gust, recenter, density wheel and keyboard twins.
2. Add Grain and Air pop-over widgets and a compact two-column preset/skin library; wire F2 map, F3 grain, F4 air and F5 library while leaving F8's shared preset actions available.
3. Extend DRIFT's immutable telemetry snapshot through the 96-grain pool maximum and update the telemetry contract/test accordingly.
4. Add package skins, CLI integration and headless tests for SGR interaction, actual grain vectors, deterministic snapshots, all four skins, HUD controls, full/compact layout and shared CLI flows.
5. Run the complete device-free package checks, inspect the full diff against issue/RAG/lesson contracts, request PR checks on the exact head, monitor CI, squash-merge, and verify post-merge `main` CI.

## Provenance

Codex desktop (GPT-6; configuration unknown) performed this prepass using the local repository, Git, PowerShell and GitHub CLI. No external sources, sibling attempt artifacts, or physical audio/MIDI devices were used.

## Implementation outcome

- DRIFT now runs through the shared `trio_kit` shell with a per-instrument weather map, complete Grain/Air HUD controls, a preset/colourway library, three packaged TOML skins and the guaranteed built-in mono option.
- The map samples the engine seed for its noise lattice and freezes phase during snapshots. SGR tests verify y orientation, queued field changes, gust down/up events, recenter, wheel density and keyboard equivalents.
- `GrainPool.grain_snapshot` returns all currently active grains. DRIFT publishes synchronized pan/ratio/amplitude/age vectors and count from that snapshot; the shared telemetry vector cap is 96, matching `gr.max`.
- Fresh review found an edge-coordinate off-by-one at the top/bottom map boundary and missing Grain/Air controls; both were corrected and covered. The library now initially highlights the current colourway.
- `tools/check.py --package all --packaging` passed 470 tests (kit 339, AURORA 38, LOOM 44, DRIFT 49), built all four wheels, installed them into a clean environment, and passed import/resource/CLI smoke checks. Installed DRIFT skin and preset listings, compact snapshot, self-test (8 presets, 4 skins, 16 offline render-seconds), and offline WAV render (2,400 stereo frames at 48 kHz) all passed. Physical audio, MIDI and terminal hardware acceptance was not run.
- A fresh highest-effort self-review was performed because an independent provider-native tier was unavailable. No sibling attempt artifacts or external references were used.
