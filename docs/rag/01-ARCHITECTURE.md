---
corpus: trio-autonomous
document_id: TRIO-ARCH
status: authority
---
# Architecture contract
Required package identities: `kit/` => distribution `trio-kit`/import `trio_kit`; `aurora/` => `trio-aurora`/`trio_aurora`/CLI `aurora`; likewise `loom`, `drift`. All four co-install. Instruments never import one another.

Runtime invariants: UI/MIDI/sequencer enqueue events, never mutate DSP directly; one clear audio/DSP owner; coherent per-block parameter snapshots; stable `note_id` voice ownership; small read-only telemetry; arbitrary callback frame counts are fully written; backend failures degrade to device-free operation; seeded offline paths deterministic where specified.

Reference flow: terminal/MIDI/sequencer -> event queue -> block engine -> voices -> instrument bus -> master -> backend, with telemetry back to UI.

Factory assets ship as package data. User data is per-instrument and atomic, overridable by `--data-dir`.

Behavior/public package/CLI contracts and issue acceptance are binding. Internal file/class decomposition may improve if documented in the PR and future issue contracts remain coherent.
