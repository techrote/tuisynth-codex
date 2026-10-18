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

- `extras.sequencer` is a validated object with `pattern`, `tempo`, `swing`, `playing` and
  `arpeggiator` members. `pattern` contains `length` and `lanes`; lanes are arrays of steps.
  Arpeggiator fields are `enabled`, `mode`, `octaves`, `rate`, `latch` and `seed`. Omitted
  shared settings receive deterministic defaults. Instrument validators see only their private
  extras; the shared preset validator preserves both areas.
- `Pattern`: 16 steps (lengths 1-32 allowed), up to 4 lanes. Each step: `on`, `note`
  (MIDI 0-127 or `None` = "use held chord"), `velocity` 0-1, `gate` 0.05-1 of a step,
  `probability` 0-1. Stored in presets under `extras.sequencer` (validated).
- `Transport`: tempo 40-240 BPM, swing 0-0.6. Swing delays the even-numbered sixteenth-note
  ticks (one-based counting) by `swing * one unswung sixteenth`; boundaries are computed from
  the transport anchor rather than accumulated rounded durations.
- Scheduling happens **inside the engine** at block level: for each block the sequencer
  computes step boundaries falling in the block and pushes `NoteOn`/`NoteOff` with `frame`
  offsets (sample-accurate, see TRIO-ENGINE). It uses an engine-owned `note_id` range and sends a
  `NoteOff` for every generated `NoteOn`, including progression, stop, tempo change, pattern edit
  and panic.
- `Arpeggiator`: modes `up`, `down`, `updown`, `random` (seeded), `as-played`; octaves 1-4;
  rate 1/4, 1/8, 1/8T, 1/16, 1/16T, 1/32; latch on/off. Input is the currently held notes
  from any keyboard; output replaces direct note triggering while enabled.
- The shared `SequencerProcessor` observes routed note events from MIDI, computer keyboard and
  on-screen piano, plus LOOM's explicit held-pitch event while chord mode filters direct delivery.
  Latched notes remain eligible until panic or an input release after latch is disabled. Arp notes
  trigger immediately on the first held input and then use the selected rate.
- Optional MIDI clock follow (24 ppqn, Start/Stop/Continue) is allowed only if it is fully
  tested with the fake MIDI backend; otherwise leave it out.

### UI

Each instrument places a step-grid widget in its own visual language: AURORA as a row of
spectral "pillars" on the SPACE screen, LOOM as knots on a thread across the panel row, DRIFT
as a ring of 16 pressure cells in a drawer. In every instrument `Shift+F3` opens/focuses the
sequencer area. Mouse: click toggles a step, drag vertically sets velocity, right-click sets
probability; `Space` starts/stops the transport (Space is not a note key). `Escape` returns to the
instrument screen that was open before the sequencer. Keyboard twin: arrows select step, `Enter`
toggles, `PageUp/PageDown` velocity.
- The shared `SequencerWidget` draws the instrument-specific motif, preserves the pattern in
  `extras.sequencer`, and adds up/down arrows for lane selection. `[`/`]` adjusts tempo and
  `,`/`.` adjusts swing. While the grid has focus, `A` enables the arp, `M` cycles mode, `O`
  cycles octave count, `R` cycles rate, and `L` toggles latch. Terminals that encode modified F3
  using the legacy F15 key normalize it to the same sequencer action.

### Tests

Step timing within 1 frame of the ideal at 120 BPM over 64 steps at both sample rates;
swing offsets; every `NoteOn` has a matching `NoteOff`; stop releases all sequencer notes;
arp ordering for each mode with seeded random; pattern round-trip through presets.

## Modulation oscillators, matrix and post-processing (TRIO-016)

### Sources

`LFO1`-`LFO3` (sine, triangle, saw, square, sample&hold, smooth random; free rate 0.01-20 Hz or
tempo-synced divisions that follow tempo up to 32 Hz at 240 BPM and 1/32; phase 0-1; per-voice
or global), `ModEnv` (ADSR), `velocity`,
`modwheel`, `keytrack`, `note-random` (per-note seeded constant), `pitchbend`.

`extras.modulation` stores exactly three LFO objects (`waveform`, free `rate`, `sync`, `division`,
`phase`, `mode`, `seed`), ModEnv ADSR times (`attack`, `decay`, `sustain`, `release`), exactly eight
slots (`source`, `destination`, bipolar `amount`) and a `rack` object (`order`, `units`). Every
source is normalized to -1..1: velocity and modwheel map their 0..1 inputs to -1..1, keytrack is
clipped around MIDI 60, pitchbend is normalized to 12 semitones, note-random is seeded per note,
and LFO/FX sources use their block mean. Voice-mode LFOs and per-note sources are evaluated per
voice; the three shared LFOs, modwheel, pitchbend and effect LFOs are global.

### Matrix

8 slots: `source -> destination` with bipolar amount -1..1. Destinations are any parameter
with `modulatable=True` in the instrument registry plus FX parameters. Modulation is applied at
control rate (once per 256-frame block) to a copy of the `ParamSnapshot`, smoothed with a 20 ms
one-pole transition, and clamped to the parameter range. A route adds
`source * amount * (maximum - minimum) / 2` to the parameter's base value. Destinations must be
known, continuous and marked modulatable; `ParamSpec.modulation_scope` is `global`, `voice` or
`both`. Voice sources apply to voice/both parameters only; global sources may target any
modulatable parameter. Validation rejects voice-source routes to global-only parameters or FX rack
destinations, because they are consumed only by a shared instrument/effect bus. Per-voice routes initialize from the note-start source value so excitation
parameters receive modulation at note-on, then smooth subsequent control changes over 20 ms.
Multiple global and per-voice routes to one destination sum before one final clamp. LOOM keyboard,
MIDI and surface-triggered string voices share the same note-scoped modulation state. DRIFT's
grain controls and ADSR parameters expose per-voice destinations where each note stream consumes
them. FX routes use the same summed, smoothed rule with their rack-owned parameter ranges. The
matrix is empty by default and round-trips in presets under `extras.modulation`. Interactive matrix
and rack edits commit together at an internal block boundary. An edit to rack settings preserves
unrelated matrix LFO phase and route smoothing state. DRIFT's `wind.howl` is a global destination
because its processor adds howl to the shared formant bus.

### Post-processing rack (modulation oscillators inside effects)

Order (each with bypass and mix, user-reorderable): `tremolo/autopan` (own LFO),
`ring-mod` (sine carrier 0.5-2,000 Hz, carrier frequency itself LFO-modulatable),
`phaser` (4/8 all-pass stages, own LFO whose sweep reaches a static 250 Hz at depth 0), `tape` (wow 0.5 Hz + flutter 8 Hz modulated delay,
soft saturation), then the existing shared chorus, delay and reverb. Default order is as written;
the four new units are bypassed by default and existing instrument effects keep their prior
enabled state and order. Each rack LFO is also exposed as a matrix source. All rack units are
block-vectorised and stateful across blocks. Rack mix is a 0..1 wet blend and is editable on the
pedalboard by dragging its mix row or scrolling over the unit; `,`/`.` decrement/increment the
selected unit mix.

### UI

A `MOD` area in each instrument's own style, opened/focused with `Shift+F4`: a matrix grid
(all sources as rows, slots as columns) with ASCII patch cords, and an FX "pedalboard" drawn as
ASCII art boxes whose order can be changed by dragging. Mouse edits routes, amounts, unit mix,
bypass, clear and order; keyboard twins are `R`/arrows for source, `T` for destination,
`+`/`-`/PageUp/PageDown for amount, Delete for clear, `B`/Space for bypass, `[`/`]` for order,
and `,`/`.` for mix. Press `V` to switch keyboard focus between the matrix and rack; rack focus
uses Left/Right to select any of the seven units before changing its mix, bypass or order.

### Tests

LFO shapes/rates exact at known phases; tempo sync at 120 BPM; matrix clamping; per-voice vs
global routing; tremolo/autopan constant-power; ring-mod spectrum shows sum/difference
components; phaser notches move with LFO; tape delay modulation depth; every unit stable and
finite for 20 s at extreme settings; preset round-trip of matrix and rack order.
