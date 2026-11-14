# TRIO 0.1.0 candidate release notes

**Draft/HOLD for explicit owner approval.** This campaign produces reviewable artifacts and software qualification evidence. It does not merge the PR, tag a revision, publish a GitHub/PyPI release or close TRIO-017. Package versions are 0.1.0; candidate status is carried in the release/provenance records and PR rather than by pretending that publication has happened.

## Included

The four distributions install together: `trio-kit`, `trio-aurora`, `trio-loom` and `trio-drift`. AURORA remains a spectral pad/choir painter, LOOM a plucked/bowed string surface and DRIFT a granular weather/voice field. Shared infrastructure includes the audio engine, safe master output, computer and on-screen pianos, optional MIDI/CC learn, presets, skins, sequencer/arpeggiator, modulation matrix and ordered effects rack. Each instrument includes eight factory presets, three colourways and the shared mono fallback.

TRIO-017 adds a reusable first-run launcher for POSIX and Windows, explicit hardware extras, real installed-command qualification outside the checkout, full package-data verification, reproducible source/wheel artifacts, checksum manifests and source/toolchain provenance. Release qualification also repairs shared-overlay mouse/scroll interaction and MIDI-learn cancellation, and separates MIDI-map files from preset discovery without moving existing user data. A historical preset named `midi-map` remains discoverable and renamable; controller writes preserve it until migration. User guides include dispatch-checked control tables, parser-derived CLI options, factory inventories and existing frozen layout fixtures. [CHANGELOG.md](../CHANGELOG.md) maps the whole release to TRIO-001–017.

## Qualification and interpretation

The required matrix is Ubuntu/Python 3.11, Ubuntu/Python 3.14, Windows/Python 3.11 and Windows/Python 3.14. A candidate is software-qualified only when its exact-source CI and independent review evidence are green. Use the PR's final handoff and artifact `SOURCE.json`/qualification records for the actual revision and outcomes; a successful run for a different revision does not qualify this one.

The release tool checks clean builds, package contents, installed versions/imports/commands, every installed selftest and checksums. Reproducibility means repeated builds from the same Git source with the recorded pinned toolchain and source epoch produce the same TRIO wheel/source bytes. Third-party native dependencies and installer qualification evidence depend on the recorded platform/interpreter; cross-platform equality of those binaries is not claimed.

## Known scope and limits

- Python is required; there is no bundled standalone executable, plugin/VST/CLAP, audio input, sample import or network synthesis feature.
- Core install is device-free. Audio/MIDI packages are explicit extras; host drivers and devices are separately required. Device fallback preserves UI/offline operation.
- Computer keys use timed gates because ordinary terminal input lacks key-up events. Use an actual MIDI controller for held-key performance; physical behavior must be checked.
- The TUI sequence editor exposes enable/velocity/probability, tempo/swing and arp controls. Advanced pattern note/gate/length/lane settings are validated preset data. LFO/ModEnv source configuration is likewise preset data; the matrix edits routes/amounts and the rack edits order/mix/bypass.
- Parameter undo/redo is not a full-history editor. Save presets explicitly; last-session restore and recording of interactive sessions are not features of 0.1.0.
- Frozen text snapshots prove software layout with deterministic telemetry. They do not prove real terminal glyphs, mouse gestures, colour or timing.
- No real audio, USB MIDI, physical Windows Terminal, listening or ten-minute hardware/CPU result is fabricated. All physical status is solely in [ACCEPTANCE.md](ACCEPTANCE.md).
- A licence has not been selected by the owner. No new licence is introduced by the candidate.

## Evaluate or roll back

Use [installation](INSTALL.md), the [three instrument guides](../README.md) and the Windows procedure in [acceptance](ACCEPTANCE.md). Start at a low listening volume and confirm the chosen audio output. Save any useful user presets outside the disposable candidate directory. Rollback means quitting the candidate and using the previous artifact/revision with a fresh separate environment; per-instrument user data remains available for backup. See [release reproduction](RELEASE.md) for checksums and source identity.
