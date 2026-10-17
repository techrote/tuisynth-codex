---
corpus: tuisynth
programme: trio
document_id: TRIO-ENGINE
status: authority
---
# Audio engine, voices, parameters and presets contract (`trio_kit`)

## Fixed numbers

| Item | Value |
|---|---|
| Default sample rate | 48,000 Hz (`--sample-rate` accepts 44,100 and 48,000) |
| Internal block | 256 frames (`BLOCK`) |
| Sample format | float32, stereo, shape `(frames, 2)` |
| Output ceiling | `|sample| <= 0.966` (-0.3 dBFS) after the master limiter |
| Event queue | thread-safe, bounded 4,096 events; overflow drops oldest `param` events first, never note-offs |

## Parameters (TRIO-002)

`ParamSpec(key, label, unit, minimum, maximum, default, kind, choices=None, curve="linear",
modulatable=False, group="")` where `kind` is `continuous`, `discrete` (integer steps) or
`choice` (index into `choices`). `curve` is `linear`, `log` (minimum > 0) or `exp`.

- `ParamRegistry` holds specs in declaration order; keys are unique dotted names
  (`amp.a`, `fx.reverb.mix`). It provides `to_unit(key, value) -> 0..1`, `from_unit(key, u)`,
  `format(key, value) -> str` (Hz/kHz, ms/s, %, dB, cents, semitones, choice label) and
  `clamp(key, value)`.
- **Validation** (`validate_value`): booleans, strings, `None`, NaN and +-Inf are rejected with a
  `ParamError` naming the key. Out-of-range finite numbers are clamped **and** reported as a
  warning. Discrete/choice values are rounded to the nearest valid integer and reported if
  they changed. Nothing is coerced silently.
- **Morph** (optional per instrument): `morph(a, b, t)` interpolates continuous params
  (respecting `curve`); discrete and choice params take `a` when `t < 0.5` and `b` when
  `t >= 0.5`. Tests must cover `t` in {0, 0.25, 0.49, 0.5, 0.75, 1}.

## Presets (TRIO-002)

JSON document, UTF-8, schema `trio-preset/1`:

```json
{"schema": "trio-preset/1", "synth": "aurora", "id": "glacier-choir", "name": "Glacier Choir",
 "params": {"amp.a": 2.5}, "extras": {"harmonics": [1.0, 0.5]}, "tags": ["pad"]}
```

- `synth` must equal the loading instrument's id; `id` matches `^[a-z0-9][a-z0-9-]{0,47}$`.
- Missing params take defaults; unknown keys produce warnings; invalid values follow the
  validation rules above. `extras` is validated by an instrument-supplied validator.
- Structural errors (not an object, wrong types, oversize > 256 KiB, nesting > 16) return a
  `PresetError` with a message; they never raise `TypeError`/`AttributeError` to the UI.
- `save_preset()` writes atomically (temp file in the same directory, flush, `os.replace`).
- Factory presets load from package data; user presets from the user data directory and
  shadow factory presets with the same id only when the user explicitly saves over one.

## Events (TRIO-003)

Immutable dataclasses: `NoteOn(note_id, pitch, velocity, source, frame=0)`,
`NoteOff(note_id, frame=0)`, `Sustain(on)`, `PitchBend(semitones)`, `ModWheel(value)`,
`ControlChange(cc, value)`, `ParamSet(key, value)`, `InstrumentEvent(name, payload)`,
`Panic()`, `Transport(...)` (stretch).

- `pitch` is a float MIDI note number (0-127 after transposition); `velocity` is 0..1.
- `note_id` is an `int` allocated by `NoteIds.next()` (monotonic, thread-safe). Producers keep
  their own mapping from physical key / MIDI note / mouse press to `note_id`. Transpose or
  octave changes affect only **new** notes; a `NoteOff` always releases exactly the voice its
  `note_id` started.
- `frame` is an optional offset (0..BLOCK-1) inside the next block for sample-accurate timing
  (used by the sequencer). The engine splits a block at event frames.
- Events with out-of-range values are rejected at construction with `ValueError`.
- `InstrumentEvent(name: str, payload: tuple)` carries instrument-specific, non-scalar
  commands (AURORA harmonic arrays, LOOM string plucks/mutes). The engine delivers it to
  `Instrument.on_event(name, payload)` at the start of the next block (or at its `frame`).
  `payload` must be a tuple of floats/ints/strings (validated by the instrument).

## Voices (TRIO-003)

`VoiceManager(max_voices)` maps `note_id -> Voice`.

- Allocation order: a free voice; else steal the quietest **released** voice; else the oldest
  held voice. A stolen voice gets a 5 ms fade, never an instant cut.
- Two `NoteOn`s with the same pitch create two voices. Each `NoteOff` releases its own voice.
- Sustain: while on, `NoteOff` marks the voice `sustained`; turning sustain off releases every
  sustained voice. `Panic` releases all voices with a 10 ms fade and clears sustain.
- An instrument implements `Instrument` (create voices, `prepare(sample_rate, block)`,
  optional `process_bus(buffer, params)`, `telemetry()`, `on_event(name, payload)`,
  `get_extras() -> dict` and `set_extras(extras)` for non-scalar preset state, `close()`);
  a voice implements
  `start(pitch, velocity, params)`, `release()`, `render(frames, params) -> ndarray`,
  `finished` and `retarget(pitch)` (for glissando/legato).

## Engine (TRIO-003)

`Engine(instrument, sample_rate=48000, block=256, max_voices, seed=0)`:

- `push(event)` is thread-safe and non-blocking.
- `render(frames) -> ndarray(frames, 2)` accepts **any** positive `frames`. Internally it
  renders whole 256-frame blocks and keeps the unused remainder for the next call, so
  `render(257); render(255)` is sample-identical to `render(512)` (property-tested for many
  random chunkings). It never returns uninitialised memory.
- Per block: drain events (applying `ParamSet`s into a new `ParamSnapshot`), split at event
  frames, render voices, run the instrument bus, then the `MasterBus`.
- `OfflineEngine` is the same engine with no device; used by tests and `--render`.
- Randomness only through `numpy.random.Generator` instances seeded from `(seed, voice
  counter)`, so equal seeds and equal event streams give bit-identical float32 output on the
  same platform.

## DSP building blocks (TRIO-004)

`trio_kit.dsp` provides stateful, block-vectorised units used by all instruments. Every unit
has `reset()`, carries state across blocks, accepts any block length up to `BLOCK`, and is
tested for continuity: processing one signal in random chunk sizes equals processing it whole.

| Unit | Contract |
|---|---|
| `Adsr` | Attack is a linear ramp; decay and release are exponential approaches whose stated time is the time to cover 99 % of the distance. Closed-form per stage, split at stage boundaries inside a block. `gate_on(velocity)`, `gate_off()`, `finished`. |
| `Biquad` | RBJ-cookbook low-pass / band-pass / high-pass / peaking coefficients; processing with `scipy.signal.lfilter(b, a, x, zi=state)`; coefficient changes at block boundaries with parameter smoothing over 5 ms. Stable for cutoff 20 Hz-0.45 x sample rate and resonance up to Q 20. |
| `Lfo` | sine, triangle, saw, square, sample-and-hold, smooth random (seeded); vectorised phase; rate 0.01-20 Hz; outputs -1..1. |
| `DelayLine` | Circular buffer, fractional (linear-interpolated) read. **Chronological**: after writing 0..7, a read of delay 4 returns 4,5,6,7 (MOD-004 regression test). Feedback delays require delay >= one block so a block is computed from past samples only. |
| `Chorus` | Two modulated `DelayLine` taps (7-20 ms, LFO 0.1-6 Hz, opposite phases L/R), mix. |
| `StereoDelay` | Ping-pong feedback delay 60 ms-2 s, feedback 0-0.9 with a low-pass in the loop, mix. |
| `Reverb` | 8-line feedback delay network with a Householder matrix, all line lengths > `BLOCK` (so each block is computed from past samples), per-line one-pole damping via `lfilter`, size 0.2-1.6 scales lengths/decay, mix. Must decay to below -90 dBFS after input stops for size <= 1.6. |

## Master bus (TRIO-003)

DC blocker (one-pole high-pass, 10 Hz, `lfilter` with carried state) -> optional `tanh`
drive -> peak limiter (instant attack, 120 ms release, ceiling 0.966) -> final hard clip at
0.966 -> non-finite guard. The limiter lives in `trio_kit/engine/master.py` and is
vectorised: the decayed-peak envelope `env[n] = max(|x[n]|, env[n-1] * r)` (with
`r = exp(-1 / (0.12 * sample_rate))`) is computed per block as
`max(env_prev * r**(k+1), maximum.accumulate(|x[k]| * r**-k) * r**k)` for `k = 0..n-1`,
and the gain is `min(1, ceiling / env)`, applied to both channels using the louder channel's
envelope. If any non-finite sample appears, the block is replaced with silence, all voice and
filter states are reset, and a `nonfinite_resets` telemetry counter increments.

## Backends (TRIO-003)

`NullBackend` (no device, used by `--no-audio`) and `SoundDeviceBackend` (lazy `import
sounddevice`; `OutputStream(callback=..., blocksize=0)`). The callback fills `outdata[:]`
from `engine.render(frames)` for whatever `frames` it receives, catches every exception,
writes silence on error and records it in telemetry. Stream start failure closes the stream,
reports a readable message and falls back to `NullBackend` instead of crashing.

## Performance

Engines are block-vectorised NumPy/SciPy code. No per-sample Python loops in voice
rendering except where an issue explicitly allows a bounded loop. CPU is reported as
`callback_seconds / block_seconds` (exponential moving average) in telemetry. CI gates only on
a generous bound (see [10-TESTING-CI-RELEASE.md](10-TESTING-CI-RELEASE.md)); precise
real-time performance is a manual acceptance item.
