# [TRIO-008] Kit on-screen keyboard, app shell and shared CLI

This GitHub issue is the autonomous execution prompt for **TRIO-008**. `AGENTS.md` is incorporated by reference and is mandatory, including reconciliation, branching, checkpoints, provenance, PR review, exact-head CI, merge, and post-merge verification.

## Depends on
TRIO-003, TRIO-005 and TRIO-007 merged/green.

## Read first
1. `AGENTS.md`
2. `ATTEMPT.md`
3. `docs/programme/IMPLEMENTATION-PROGRAMME.md`
4. `docs/rag/12-AUTONOMOUS-WORKFLOW.md`
5. `docs/rag/13-BENCHMARK-PROVENANCE.md`
6. `docs/programme/issues/TRIO-008.md`
7. `docs/rag/03-INPUT-CONTRACT.md (On-screen keyboard)`
8. `docs/rag/04-TUI-UX-CONTRACT.md (App shell, CLI, Headless driver)`
9. `docs/rag/02-AUDIO-ENGINE-CONTRACT.md (Engine/Backends/Presets)`
10. `docs/rag/01-ARCHITECTURE.md`
11. `docs/rag/11-LESSONS-FROM-RECOVERY.md`

## Objective
Provide everything around an instrument-specific layout: exact clickable piano, shell/overlays, shared CLI, offline render/selftest/snapshot and end-to-end demo.

## Required implementation
- PianoWidget exact visible-cell hit geometry; mouse-down NoteOn with depth velocity, mouse-up anywhere exact NoteOff, drag gliss/optional legato, right latch, wheel octave, keyboard cursor twin and sounding highlights.
- InstrumentSpec + Shell coordinating engine/backend/MIDI/skins/presets; shared F1/F6/F7/F8/F9/Ctrl+L/P/Z/Y/Q commands, note-key routing, undo/redo, telemetry and strict shutdown order.
- Help, command palette, live skin preview, MIDI/CC-learn picker, preset library/save/rename/delete overlays.
- Engine preset apply hook at block boundary.
- Shared CLI flags from TRIO-UX: listing, --no-audio, --selftest, --render, --snapshot, --version etc.
- Selftest loads factory assets, offline-renders finite/non-silent/bounded audio and headlessly renders screens without opening devices/terminal.
- Demo SineInstrument app proves stack.

## Required tests and acceptance
- Real-SGR every key cell including black keys/depth velocity, release, gliss, latch, wheel, keyboard twin.
- Shell F-keys/palette/undo/redo/note routing and Ctrl+Q release->backend stop->MIDI close order.
- CLI list/version/render valid WAV/snapshot/selftest success and intentional fixture failure.
- Backend failure fallback visible but usable.
- Deterministic demo snapshots at required sizes.
- CI green.

## Out of scope
AURORA/LOOM/DRIFT-specific DSP/layouts.

## Delivery
Complete the issue end-to-end. Open a PR titled `[TRIO-008] Kit on-screen keyboard, app shell and shared CLI` with `Closes #<this issue>`; include exact test evidence, RAG/contract changes, limitations and role-based provenance. Use a provider-internal independent review tier/configuration where available. Merge only when the exact reviewed head is current and every required automated check is green; verify `main` CI after merge. If interrupted, post the `AGENTS.md` checkpoint before ending.
