# [TRIO-016] Mandatory modulation matrix and post-processing rack

This issue is the autonomous execution prompt for **TRIO-016**. `AGENTS.md` is incorporated by reference and mandatory, including reconciliation, branching, checkpoints, provenance, PR review, exact-head CI, merge, and post-merge verification.

## Depends on
TRIO-015 merged/green.

## Read first
1. `AGENTS.md`
2. `ATTEMPT.md`
3. `docs/programme/IMPLEMENTATION-PROGRAMME.md`
4. `docs/rag/12-AUTONOMOUS-WORKFLOW.md`
5. `docs/rag/13-BENCHMARK-PROVENANCE.md`
6. `docs/programme/issues/TRIO-016.md`
7. `docs/rag/09-SEQUENCER-MODULATION-SPEC.md (Modulation + post-processing)`
8. `docs/rag/02-AUDIO-ENGINE-CONTRACT.md (Parameters/Engine/DSP)`
9. `docs/rag/00-CHARTER.md`

## Objective
Add global/per-voice modulation sources, an eight-slot modulation matrix and reorderable post-processing rack to every instrument while preserving default sound.

## Required implementation
- Sources: LFO1-3 with free/tempo-sync shapes, ModEnv, velocity, modwheel, keytrack, seeded note-random, pitchbend; explicit global/per-voice semantics.
- Eight matrix slots source->modulatable destination with bipolar amount, block-rate evaluation/smoothing/clamping and preset extras round-trip.
- Reorderable rack: tremolo/autopan, ring mod, phaser, tape wow/flutter/saturation plus existing chorus/delay/reverb; bypass/mix/order and effect-owned LFOs exposed as modulation sources.
- Backwards-compatible engine hook for global/per-voice modulated snapshots as needed.
- Shared matrix/pedalboard widgets, but each instrument renders a distinct MOD area opened/focused by Shift+F4; mouse route/amount/clear/reorder/bypass + keyboard twins.
- Matrix empty and rack bypassed by default; pre-change factory preset render checksum fixtures prove default sound unchanged.

## Required tests and acceptance
- LFO shapes/rates/phases/tempo sync and seeded note-random stability.
- Matrix bipolar routing, clamping, global vs per-voice, empty identity.
- Rack: tremolo/autopan constant-power behavior, ring-mod sum/difference, moving phaser notch, tape modulation depth, extreme 20s finite stability, random-chunk continuity, default bypass bit identity.
- Matrix/rack preset round-trip.
- Per-instrument SGR routing/reorder and distinct MOD snapshots.
- Default factory preset sound checksums unchanged; all earlier tests green; CI green.

## Out of scope
New synthesis engines, audio input, plugin formats.

## Delivery
Complete end-to-end. Open PR `[TRIO-016] Mandatory modulation matrix and post-processing rack` with `Closes #<this issue>`; include exact tests, RAG changes, limitations and role-based provenance. Use a provider-internal independent review tier/configuration where available. Merge only when the exact reviewed head is current and all required automated checks are green; verify `main` CI. If interrupted, post the `AGENTS.md` checkpoint.
