# [TRIO-005] Kit computer-keyboard piano and USB MIDI input

This GitHub issue is the autonomous execution prompt for **TRIO-005**. `AGENTS.md` is incorporated by reference and is mandatory, including reconciliation, branching, checkpoints, provenance, PR review, exact-head CI, merge, and post-merge verification.

## Depends on
TRIO-003 merged/green.

## Read first
1. `AGENTS.md`
2. `ATTEMPT.md`
3. `docs/programme/IMPLEMENTATION-PROGRAMME.md`
4. `docs/rag/12-AUTONOMOUS-WORKFLOW.md`
5. `docs/rag/13-BENCHMARK-PROVENANCE.md`
6. `docs/programme/issues/TRIO-005.md`
7. `docs/rag/03-INPUT-CONTRACT.md`
8. `docs/rag/02-AUDIO-ENGINE-CONTRACT.md (Events)`
9. `docs/rag/11-LESSONS-FROM-RECOVERY.md`

## Objective
Provide pure/testable computer-keyboard note gating and optional USB MIDI parsing/input/CC learn without real devices in CI.

## Required implementation
- Implement the exact two-row tracker key layout, octave/velocity controls, timed gates with repeat extension, latch and release_all; held note-offs preserve original note_id across octave changes.
- Pure MIDI parser for note on/off (velocity 0 off), sustain, modwheel, 14-bit bend, panic CCs, channel filter; ignore clock/active sensing/SysEx; malformed input counted not crashed.
- MidiNoteMap owns note_ids; repeated same MIDI note releases previous instance first.
- Lazy RtMidi backend, fake backend, port selection/reconnect and readable unavailable state.
- Persistent atomic CC-learn map with arm/feed/lookup/clear; corrupt map loads empty with warning.

## Required tests and acceptance
- Exact key->pitch contract, gate expiry/repeat/latch/octave/velocity/out-of-range/original-note release.
- Byte-sequence parser cases incl. bend extremes/centre, channels, realtime/SysEx ignore, malformed count.
- Repeated note-on ownership, sustain/panic mapping.
- Fake delivery, missing rtmidi, disappearance/reconnect.
- CC learn persistence and corrupt-file recovery.
- No test opens hardware; CI green.

## Out of scope
On-screen keyboard widget and shell MIDI picker UI.

## Delivery
Complete the issue end-to-end. Open a PR titled `[TRIO-005] Kit computer-keyboard piano and USB MIDI input` with `Closes #<this issue>`; include exact test evidence, RAG/contract changes, limitations and role-based provenance. Use a provider-internal independent review tier/configuration where available. Merge only when the exact reviewed head is current and every required automated check is green; verify `main` CI after merge. If interrupted, post the `AGENTS.md` checkpoint before ending.
