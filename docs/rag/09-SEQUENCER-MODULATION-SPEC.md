---
corpus: tuisynth
programme: trio
document_id: TRIO-SEQMOD
status: authority (mandatory programme scope)
---
# Sequencer/arpeggiator and modulation/post-processing contract

Both are mandatory `trio_kit` modules integrated into all three instruments. Implement them after the three instrument UIs are merged. All earlier behavior and tests must remain green.

## Sequencer and arpeggiator (TRIO-015)

### Model (`trio_kit.seq`)

- `Pattern`: 16 steps (lengths 1-32 allowed), up to 4 lanes. Each step: `on`, `note`
  (MIDI 0-127 or `None` = "use held chord"), `velocity` 0-1, `gate` 0.05-1 of a step,
  `probability` 0-1. Stored in presets under `extras.sequencer` (validated).
- `Transport`: tempo 40-240 BPM, swing 0-0.6 (delays even 16th steps), playing/stopped.
- Scheduling happens **inside the engine** at block level: for each block the sequencer
  computes step boundaries falling in the block and pushes `NoteOn`/`NoteOff` with `frame`
  offsets (sample-accurate, see TRIO-ENGINE). It uses its own `note_id`s and always sends a
  `NoteOff` for every `NoteOn`, including on stop, tempo change and pattern edit.
- `Arpeggiator`: modes `up`, `down`, `updown`, `random` (seeded), `as-played`; octaves 1-4;
  rate 1/4, 1/8, 1/8T, 1/16, 1/16T, 1/32; latch on/off. Input is the currently held notes
  from any keyboard; output replaces direct note triggering while enabled.
- Optional MIDI clock follow (24 ppqn, Start/Stop/Continue) is allowed only if it is fully
  tested with the fake MIDI backend; otherwise leave it out.

### UI

Each instrument places a step-grid widget in its own visual language: AURORA as a row of
spectral "pillars" on the SPACE screen, LOOM as knots on a thread across the panel row, DRIFT
as a ring of 16 pressure cells in a drawer. In every instrument `Shift+F3` opens/focuses the
sequencer area. Mouse: click toggles a step, drag vertically sets velocity, right-click sets
probability; `Space` starts/stops the transport (Space is not a note key). Keyboard twin:
arrows select step, `Enter` toggles, `PageUp/PageDown` velocity.

### Tests

Step timing within 1 frame of the ideal at 120 BPM over 64 steps at both sample rates;
swing offsets; every `NoteOn` has a matching `NoteOff`; stop releases all sequencer notes;
arp ordering for each mode with seeded random; pattern round-trip through presets.

## Modulation oscillators, matrix and post-processing (TRIO-016)

### Sources

`LFO1`-`LFO3` (sine, triangle, saw, square, sample&hold, smooth random; rate 0.01-20 Hz or
tempo-synced divisions; phase 0-1; per-voice or global), `ModEnv` (ADSR), `velocity`,
`modwheel`, `keytrack`, `note-random` (per-note seeded constant), `pitchbend`.

### Matrix

8 slots: `source -> destination` with bipolar amount -1..1. Destinations are any parameter
with `modulatable=True` in the instrument registry plus FX parameters. Modulation is applied at
control rate (once per 256-frame block) to a copy of the `ParamSnapshot`, smoothed over the
block, and clamped to the parameter range. Per-voice sources apply to per-voice params only;
global sources may target anything. Stored in presets under `extras.modulation`.

### Post-processing rack (modulation oscillators inside effects)

Order (each with bypass and mix, user-reorderable): `tremolo/autopan` (own LFO),
`ring-mod` (sine carrier 0.5-2,000 Hz, carrier frequency itself LFO-modulatable),
`phaser` (4/8 all-pass stages, own LFO), `tape` (wow 0.5 Hz + flutter 8 Hz modulated delay,
soft saturation), then the existing shared chorus, delay and reverb. Each rack LFO is also
exposed as a matrix source. All rack units are block-vectorised and stateful across blocks.

### UI

A `MOD` area in each instrument's own style, opened/focused with `Shift+F4`: a matrix grid
(sources as rows, slots as columns) with ASCII patch cords, and an FX "pedalboard" drawn as ASCII art boxes whose
order can be changed by dragging. Keyboard twin for every action.

### Tests

LFO shapes/rates exact at known phases; tempo sync at 120 BPM; matrix clamping; per-voice vs
global routing; tremolo/autopan constant-power; ring-mod spectrum shows sum/difference
components; phaser notches move with LFO; tape delay modulation depth; every unit stable and
finite for 20 s at extreme settings; preset round-trip of matrix and rack order.
