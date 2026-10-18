# TRIO-016 prepass: modulation matrix and post-processing rack

## Reconciliation

- TRIO-016 is open with no owner comments. TRIO-015 dependency PR #32 merged as
  `f0ed9ff1cb802d253abb3f2a697a558dd23f92d3`; its post-merge CI run `39108290087` passed all
  four Ubuntu/Windows and Python 3.11/3.14 lanes, including the required clean-wheel job.
- No open PR or local/remote branch duplicates TRIO-016. Work starts from verified current `main`
  on `trio-016-modulation-fx`.
- Read `AGENTS.md`, `ATTEMPT.md`, the programme, RAG 12/13, issue #16, RAG 09, RAG 02 and RAG 00.
  The active issue and RAG 09 are the scope authority; default modulation/rack behavior must keep
  the pre-change factory sound unchanged.

## Findings

- Shared `Lfo` already implements sine, triangle, saw, square, sample-hold and smooth-random
  vector output with phase, rate and seed controls. Shared `Adsr` provides a continuous
  block-vector envelope. Tempo-sync division selection, matrix slots and note-scoped modulation
  state are new work.
- `Engine` publishes a single immutable `ParamSnapshot` per internal block and currently passes
  that same snapshot to every active voice. `VoiceManager` owns note identity and can carry
  per-voice modulation state without changing instrument-specific synthesis APIs, provided base
  and effective snapshots remain separate.
- MIDI modwheel and pitch-bend events already pass through the engine's sample-offset dispatch
  path. Modulation must capture their live values in shared engine state while preserving the
  existing instrument callbacks.
- `ParamSpec.modulatable` exists, but only DRIFT's `field.x` and `field.y` are currently marked.
  Each instrument needs a reviewed set of continuous synthesis destinations; discrete and choice
  parameters must remain excluded. FX destinations are validated as rack-owned parameters.
- The instrument buses currently combine instrument tone shaping and existing effects: AURORA
  chorus/delay/reverb, LOOM body/sympathetic/reverb, and DRIFT granular/formant shaping followed
  by delay/reverb. Insert the new shared rack after instrument tone shaping and before existing
  effects/master gain, preserving the present order of all existing processing when the new rack
  is bypassed.
- The engine master bus remains last and enforces the output ceiling. Empty matrix slots and
  bypassed new rack units must avoid touching the audio buffer so the default output is bit
  identical.

## Implementation and qualification plan

1. **Complete before changing audio code:** captured whole-WAV SHA-256 checksums for all 24
   factory presets from merged main `f0ed9ff1cb802d253abb3f2a697a558dd23f92d3` using the offline
   CLI at 48 kHz, seed 0, notes C4/E4/G4 and the selftest's two-second render window. The fixture
   is `docs/programme/fixtures/TRIO-016-factory-render-baseline.json`; no generated audio was kept.
2. Add strict `extras.modulation` validation for three LFO configs, eight source/destination/amount
   slots and defaults; preserve all instrument-private extras through the shared validator.
3. Add seeded global and per-note source state, tempo divisions, ModEnv, velocity, modwheel,
   keytrack, note-random and pitchbend. Apply only to `modulatable=True` continuous parameters,
   clamp through each registry, and keep empty slots an identity operation.
4. Add vectorized tremolo/autopan, ring-mod, phaser and tape processors plus an ordered rack with
   bypass, mix and preset state. Split instrument pre-effect/effect processing so the new rack is
   in the documented position and the existing instrument defaults remain unchanged.
5. Integrate a shared source/slot editor and pedalboard control in visually distinct AURORA,
   LOOM and DRIFT MOD areas; implement Shift+F4, captured mouse actions and keyboard twins.
6. Test LFO shapes/rates/phase/tempo-sync, seeded note state, global/per-voice routing, clamping,
   effect response, long-run finite stability, random chunk continuity, presets, SGR flows, exact
   default checksum preservation and all previous behavior. Run all four package suites and
   clean-wheel qualification before PR.

## Implementation and review results

- Implemented `trio_kit.modulation` with strict three-LFO/eight-slot/rack schema, seeded global
  and per-note sources, registry-checked continuous destinations, 20 ms smoothing, summed routes,
  parameter clamping and ModEnv release continuity. Shared preset plumbing preserves instrument
  extras and rejects unknown or non-modulatable destinations.
- Implemented the stateful vectorized `FxRack` and split all three instrument buses around its
  ordered callback chain. The four new inserts bypass by default; existing chorus/delay/reverb
  keep their prior active state and order. All 24 factory WAVs were rendered after integration
  and match the pre-change SHA-256 fixture exactly.
- Added distinct AURORA/LOOM/DRIFT MOD areas, all 13 source rows at 80x24, matrix route/target/
  amount/clear controls, seven-unit order/bypass/mix controls and captured SGR input. MOD mode
  restores its prior instrument screen and focus after Escape.
- Fresh highest-effort self-review against issue #16, RAG 02/09, preset validation,
  default-render fixture and all instrument buses fixed the ModEnv release-level calculation,
  additive/smoothed FX routing, unknown destination validation, compact source-row mouse limit,
  rack-mix editing and segment-length-aware voice smoothing. The independent `gpt-6-astra`
  `xhigh` review confirmed eight additional defects: no DRIFT per-voice destinations; LOOM surface
  voices bypassing modulation; note-start smoothing erasing excitation routes; global/per-voice
  deltas clamping separately; DRIFT's formant callback seeing only base parameters; no keyboard
  selection for rack units; phaser sweep remaining at zero depth; and 1/16T/1/32 sync clipping at
  20 Hz. Fixes add DRIFT voice-scoped grain/ADSR targets, route note identity and age through
  LOOM's auxiliary voice path, initialize per-note smoothing from actual note-start pitch/velocity
  without advancing LFOs, sum both route scopes before clamping, deliver effective parameters to
  block-boundary callbacks, add `V` rack focus with arrow unit selection, scale phaser excursion
  to depth, and support synchronized rates through 32 Hz. The review's follow-up also found that
  LOOM initially queried a surface voice before its pitch/velocity had been initialized; the start
  snapshot now receives the event values explicitly, with a regression asserting its velocity
  delta. Dedicated tests cover the review findings and the initial fresh self-review corrections.
- The review follow-up identified and fixed immediate off-thread modulation resets, phase/smoothing
  resets on rack-only changes, the ineffective per-voice DRIFT `wind.howl` destination, and missing
  instrument-level SGR routing/reorder coverage. Configurations now commit together at a block
  boundary, unchanged matrix state survives unrelated rack edits, howl is global-only, and shared
  validation rejects voice sources that target global-only parameters or shared FX destinations.
  Automated `HeadlessApp` SGR tests exercise route, target, amount and pedal reorder through each
  actual instrument screen.
- The final independent review found that voice-steal, polyphony-contraction and panic fade tails
  received the global snapshot after their note modulation state had been retired. Active voices
  now retain their last effective snapshot, transfer it to the tail, and render the fade with that
  snapshot; a parameterized regression covers all three tail causes. The same review confirmed the
  earlier smoothing-history and rack-LFO continuity fixes. It reported no remaining actionable
  findings.
- Final `tools/check.py --package all --packaging` passed 549 tests (kit 405, AURORA 41, LOOM 48,
  DRIFT 55), built and clean-installed all four wheels on Windows, and passed installed
  metadata/import/CLI, preset/skin, DRIFT offline selftest and render checks. The standalone
  `tools/check_factory_render_baselines.py` verified all 24 factory WAV checksums against the
  pre-change fixture; `git diff --check` passed. Exact-head hosted CI, PR review/merge and
  post-merge main checks remain. Physical audio, MIDI and terminal acceptance remain unperformed.

## Provenance

Codex desktop (GPT-6, configuration unknown) performed this prepass, implementation and fresh
highest-effort self-review against the local repository, Git/GitHub CLI, PowerShell and Python
3.12.10. A provider-native independent reviewer (GPT-6 Astra, xhigh) reviewed the implementation
and follow-up fixes, including the final fade-tail snapshot repair. The implementer generated the
24 reference WAV files in temporary storage through the offline CLI, hashed them and discarded
them after recording the fixture. No sibling implementation, external technical source or physical
hardware was used.
