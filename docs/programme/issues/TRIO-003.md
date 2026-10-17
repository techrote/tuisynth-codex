# [TRIO-003] Kit events, voices, engine, master bus and audio backends

This GitHub issue is the autonomous execution prompt for **TRIO-003**. `AGENTS.md` is incorporated by reference and is mandatory, including reconciliation, branching, checkpoints, provenance, PR review, exact-head CI, merge, and post-merge verification.

## Depends on
TRIO-002 merged/green.

## Read first
1. `AGENTS.md`
2. `ATTEMPT.md`
3. `docs/programme/IMPLEMENTATION-PROGRAMME.md`
4. `docs/rag/12-AUTONOMOUS-WORKFLOW.md`
5. `docs/rag/13-BENCHMARK-PROVENANCE.md`
6. `docs/programme/issues/TRIO-003.md`
7. `docs/rag/02-AUDIO-ENGINE-CONTRACT.md (Fixed numbers through Backends, Performance)`
8. `docs/rag/01-ARCHITECTURE.md (runtime flow)`
9. `docs/rag/11-LESSONS-FROM-RECOVERY.md`

## Objective
Build the real-time shared core: validated events, note-id-owned voices, coherent parameter snapshots, exact arbitrary-size rendering, safe master output and device-free/sounddevice backends.

## Required implementation
- Implement immutable NoteOn/NoteOff/Sustain/PitchBend/ModWheel/ControlChange/ParamSet/InstrumentEvent/Panic events, monotonic thread-safe NoteIds and bounded nonblocking EventQueue with a documented policy that never strands required release/panic semantics.
- Implement immutable ParamSnapshot/ParamState; queued parameter changes apply coherently at block boundaries.
- Define Voice/Instrument contracts and VoiceManager allocation, released-first stealing, fade-on-steal, sustain and panic; note identity is note_id, never pitch.
- Engine renders any positive frame count exactly and is chunking-equivalent; supports event frame offsets; publishes bounded immutable telemetry; closes instruments.
- Master: DC removal, optional drive, vectorized limiter to <=0.966, hard clip, nonfinite guard/reset counters.
- Null and lazy sounddevice backends; callback always fills output; callback/start failures become silence/readable null fallback rather than crashes.

## Required tests and acceptance
- Event validation, concurrent NoteIds, overflow/release safety, InstrumentEvent frame delivery.
- Random chunkings equal whole render; callback sizes including 1,255,256,257,1024+ fully written/finite.
- Transpose does not strand note; same-pitch overlap releases correct voice; stealing/sustain/panic fade semantics.
- Param changes appear only at block boundaries.
- Master hot-noise/square ceiling, nonfinite reset, DC removal, limiter vs slow reference.
- Missing sounddevice/start/callback failure paths.
- Equal seed/event stream deterministic; different seed changes stochastic instrument fixture.
- Full matrix CI green.

## Out of scope
Shared ADSR/filter/effects, MIDI/keyboard, terminal UI.

## Delivery
Complete the issue end-to-end. Open a PR titled `[TRIO-003] Kit events, voices, engine, master bus and audio backends` with `Closes #<this issue>`; include exact test evidence, RAG/contract changes, limitations and role-based provenance. Use a provider-internal independent review tier/configuration where available. Merge only when the exact reviewed head is current and every required automated check is green; verify `main` CI after merge. If interrupted, post the `AGENTS.md` checkpoint before ending.
