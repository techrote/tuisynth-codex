# [TRIO-015] Mandatory step sequencer and arpeggiator

This issue is the autonomous execution prompt for **TRIO-015**. `AGENTS.md` is incorporated by reference and mandatory, including reconciliation, branching, checkpoints, provenance, PR review, exact-head CI, merge, and post-merge verification.

## Depends on
TRIO-010, TRIO-012 and TRIO-014 merged/green.

## Read first
1. `AGENTS.md`
2. `ATTEMPT.md`
3. `docs/programme/IMPLEMENTATION-PROGRAMME.md`
4. `docs/rag/12-AUTONOMOUS-WORKFLOW.md`
5. `docs/rag/13-BENCHMARK-PROVENANCE.md`
6. `docs/programme/issues/TRIO-015.md`
7. `docs/rag/09-SEQUENCER-MODULATION-SPEC.md (Sequencer/arpeggiator)`
8. `docs/rag/02-AUDIO-ENGINE-CONTRACT.md (Events/frame offsets, Engine)`
9. `docs/rag/00-CHARTER.md`
10. `docs/rag/04-TUI-UX-CONTRACT.md`

## Objective
Add sample-accurate sequencing and arpeggiation to the shared kit and integrate it into all three instruments without homogenizing their UIs.

## Required implementation
- Pattern length 1..32, up to 4 lanes; per-step on/note-or-held-chord/velocity/gate/probability, validated and preset round-tripped.
- Transport 40..240 BPM, swing, start/stop. Scheduling inside engine/block hook using frame offsets and owned note_ids; guaranteed matching NoteOff on normal progression, stop, edit and tempo changes.
- Arpeggiator modes up/down/updown/random/as-played, 1..4 octaves, documented rates and latch; seeded random; held notes from any input source.
- Optional MIDI clock only if fully fake-backend tested; otherwise omit.
- Instrument-specific UIs: AURORA spectral pillars, LOOM thread knots, DRIFT pressure-cell ring; Shift+F3 focus/open; click/drag/right-click/keyboard twins; Space transport.

## Required tests and acceptance
- Step frame timing within 1 frame at 44.1/48k over >=64 steps; swing and tempo-change behavior.
- Every sequencer NoteOn paired with correct NoteOff across stop/edit/tempo/panic.
- Arp ordering/modes/octaves/rates/latch and seeded random.
- Pattern validation/preset round-trip.
- Per-instrument real-SGR step toggle + velocity drag + Space; distinct snapshots.
- All earlier tests green and default nonsequenced behavior unchanged; CI green.

## Out of scope
Modulation/post-processing (TRIO-016).

## Delivery
Complete end-to-end. Open PR `[TRIO-015] Mandatory step sequencer and arpeggiator` with `Closes #<this issue>`; include exact tests, RAG changes, limitations and role-based provenance. Use a provider-internal independent review tier/configuration where available. Merge only when the exact reviewed head is current and all required automated checks are green; verify `main` CI. If interrupted, post the `AGENTS.md` checkpoint.
