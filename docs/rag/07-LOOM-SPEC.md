---
corpus: tuisynth
programme: trio
document_id: TRIO-LOOM
status: authority
---
# LOOM: waveguide string ensemble with sympathetic resonance

## Sound identity

Physically-inspired strings: harp and guitar plucks, hammered/strummed autoharp chords,
and soft bowed drones, all ringing into a bank of **sympathetic strings** (sitar / viola
d'amore / hardingfele character) and a selectable **instrument body**. LOOM is an instrument
you *play with gestures*: strumming across animated strings is its signature.

## DSP (TRIO-011)

### String model: extended Karplus-Strong as a delay-chunked vectorised recursion

Per string, loop length `L = sample_rate / f0` samples (playable range MIDI 24-100, so
`L >= 18` at 48 kHz). With brightness `b = str.bright` set `g = 0.5 * (1 - b)`:

```text
loss taps   = [1-g, g]                   (delay g)
interp taps = [1-d, d]                   (fractional delay d)
h = convolve(loss, interp) = [h0, h1, h2]
M = floor(L - g),  d = (L - g) - M       so M + g + d == L
rho = 10 ** (-3 * L / (sample_rate * T60))     T60 = str.decay (held) or str.release (released)

y[n] = x[n] + rho * (h0*y[n-M] + h1*y[n-M-1] + h2*y[n-M-2])
```

Because the smallest feedback distance is `M`, any run of at most `M` consecutive outputs
depends only on earlier outputs. Render each 256-frame block in **chunks of length
min(M, remaining)** with NumPy slice arithmetic over a per-voice history buffer. This is exact
(not an approximation) and keeps Python overhead to a few array operations per chunk.
`retarget(pitch)` (pitch bend, glissando) recomputes `M, d` at block boundaries; changes in
`M` keep the history buffer and are click-free for small steps.

### Excitation

- **Pluck** (`exc.mode = pluck`): at note start inject a burst of `round(L)` samples: seeded
  white noise -> one-pole low-pass (cutoff from `exc.hardness`, 400 Hz-16 kHz) -> pick
  position comb `x[n] - x[n - round(str.pickpos * L)]` -> scaled by velocity. The burst may
  span several blocks.
- **Bow** (`exc.mode = bow`): continuous excitation while held: seeded noise -> band-pass
  centred near `f0 * (2 + 6 * exc.pressure)` -> amplitude `exc.speed * velocity` with an 80 ms
  attack, a 25-40 Hz random "rosin" flutter of depth `exc.noise * 0.3`, and a 150 ms fade on
  release. This is a deliberate *linear excitation approximation* of bowing; a nonlinear
  friction model is out of scope for v0.1 and must not be claimed.
- On release in pluck mode the loop decay switches to `str.release` with a 20 ms
  crossfade (palm-mute style). A voice is finished when its output stays below -90 dBFS for
  100 ms.

### Sympathetic bank

12 resonators using the same string code without their own excitation. Input is the mono
sum of the main strings x `sym.couple`, low-passed at 5 kHz. Output is mixed by `sym.mix`.
**No signal returns from the sympathetic bank into the main strings** (guaranteed stability).
Tunings (`sym.tuning`): `scale` (12 notes of `sym.scale` from `sym.root` upward over two
octaves starting at MIDI 48), `drone` (root and fifth in octaves 2-5), `chord` (follow the
held strum chord; only resonators quieter than -60 dBFS are retuned, so retuning never clicks).
Scales: `major`, `minor`, `dorian`, `pentatonic`, `bhairav`, `hijaz`.

### Body

Parallel bank of 6-10 band-pass biquad resonators (`scipy.signal.lfilter` with carried
state) per `body.type`: `none`, `guitar`, `violin`, `cello`, `harp`, `sitar`. Mode
frequencies are scaled by `1 / body.size`. Mode tables live in `trio_loom/body.py` with a
docstring citing their (approximate, artistic) origin. `body.mix` is wet/dry.

### Strum surface model

`strum.strings` (4-12, default 8) visible strings. In `play.mode = chord` the notes held on
any keyboard (on-screen, computer, MIDI) set the strum tuning: held pitch classes are spread
upward from the lowest held note across the strings; with nothing held the default tuning is
E2 A2 D3 G3 B3 E4 A4 D5 (truncated/extended to the string count). In `play.mode = direct`
keys sound strings directly and the strum surface uses the default tuning.
A strum crossing string `i` triggers a pluck (or a bow stroke in bow mode) of string `i`
with velocity from crossing speed: `clamp(0.25 + rows_per_second / 40, 0.25, 1.0)`.
`strum.spread` (0-80 ms) applies only to keyboard-triggered strums (`,` = down, `.` = up).

### Parameters

| Key | Range | Default |
|---|---|---|
| `play.mode` | choice direct/chord | direct |
| `exc.mode` | choice pluck/bow | pluck |
| `exc.hardness` | 0-1 | 0.55 |
| `exc.pressure`, `exc.speed`, `exc.noise` | 0-1 | 0.5, 0.7, 0.3 |
| `str.decay` | 0.2-30 s (log) | 6.0 |
| `str.release` | 0.05-5 s (log) | 0.4 |
| `str.bright` | 0-1 | 0.6 |
| `str.pickpos` | 0.02-0.5 | 0.13 |
| `sym.mix`, `sym.couple` | 0-1 | 0.3, 0.4 |
| `sym.decay` | 0.5-40 s (log) | 12 |
| `sym.tuning`, `sym.scale` | choice | scale, dorian |
| `sym.root` | discrete 0-11 | 2 (D) |
| `body.type` | choice | guitar |
| `body.mix`, `body.size` | 0-1, 0.5-2 | 0.5, 1.0 |
| `strum.strings` | discrete 4-12 | 8 |
| `strum.spread` | 0-80 ms | 18 |
| `fx.reverb.size/damp/mix`, `master.level/drive` | shared | 0.7/0.5/0.25, 0.8/0.05 |

Polyphony: 8 in pluck mode, 4 in bow mode (the voice manager limit follows `exc.mode`).
`legato_glide = True` in bow mode (glissando retargets the bowed string).

### Factory presets (>= 8)

`rosewood-harp`, `autoharp-dorian`, `sitar-dawn` (bhairav drone, sitar body),
`cello-drone` (bow), `glass-koto`, `hardingfele` (bow + strong sympathetics),
`steel-shimmer`, `muted-guitar`.

## UI (TRIO-012)

Single instrument surface, 100x30:

```text
╭─ ≋ L O O M ≋ ── rosewood-harp ────────────────────── skin rosewood · midi: none · 2/8 · cpu 14% ─╮
│ ┌ STRINGS · drag across to strum · hold+drag to bow · , . strum ──────────┐ ┌ SYMPATHETIC ─────┐ │
│ │ D5 ───────────────────────────────────────────────────────────────────── │ │ D  ───────────   │ │
│ │ A4 ───────────────────────────────────────────────────────────────────── │ │ E  ──~~~──────   │ │
│ │ E4 ──────────~~~~≈≈≈≈∿∿∿∿≈≈≈≈~~~~──────────────────────────────────────── │ │ F  ───────────   │ │
│ │ B3 ────────~~~≈≈≈∿∿∿∿∿∿∿∿≈≈≈~~~────────────────────────────────────────── │ │ G  ───────────   │ │
│ │ G3 ───────────────────────────────────────────────────────────────────── │ │ A  ─~~≈≈~~────   │ │
│ │ D3 ───────────────────────────────────────────────────────────────────── │ │ B  ───────────   │ │
│ │ A2 ───────────────────────────────────────────────────────────────────── │ │ C  ───────────   │ │
│ │ E2 ───────────────────────────────────────────────────────────────────── │ │  dorian · D      │ │
│ └──────────────────────────────────────────────────────────────────────────┘ └──────────────────┘ │
│ ┌ EXCITE ─────────┐┌ STRING ──────────┐┌ BODY ───────────┐┌ SYMPATHY ───────┐┌ PLAY ────────────┐ │
│ │ (●) pluck ( ) bow││ decay  ━━━●━━ 6s ││ ◄ guitar ►      ││ mix    ━━●━━━ .3 ││ [direct] chord   │ │
│ │ hard ━━━●━━  .55 ││ bright ━━━●━ .60 ││ mix  ━━●━━━ .50 ││ couple ━━━●━━ .4 ││ strings ◄ 8 ►    │ │
│ │ press ━━●━━━ .50 ││ pick   ━●━━━ .13 ││ size ━━━●━━ 1.0 ││ decay  ━━━━●━ 12 ││ spread ━━●━ 18ms │ │
│ └─────────────────┘└──────────────────┘└─────────────────┘└─────────────────┘└──────────────────┘ │
│ ┌ KEYS ───────────────────────────────────────────────── chord: D minor (D F A) · oct 0 · vel .70 ┐│
│ │ (two-octave on-screen piano, TRIO-INPUT geometry)                                             ││
╰─ F1 help · F2 strings · F3 panels · F4 sympathetic · F5 library · F6 skin · F7 midi · F9 · ^Q ───╯
```

- **String animation**: the engine publishes per-string RMS level and a slowly advancing
  phase in telemetry; each string line is drawn as a standing-wave envelope
  `level * sin(pi * x / width)` mapped to the skin `string` glyph ramp
  (e.g. `─ ~ ≈ ∿`). Large displacement may draw onto the adjacent blank row. Bowed strings
  show a bow marker `╫` at the bow point. Sympathetic resonators animate in their column.
- **Strum**: left mouse down on the string area captures the mouse; crossing string rows
  while moving plucks/bows them (see strum model). Right-click a string mutes it (choke).
  Keyboard twin: focus the string area, `Up/Down` select string, `Enter` pluck selected,
  `,`/`.` strum down/up.
- `/` toggles `play.mode`; `F2`..`F4` move focus to strings / panel row / sympathetic column;
  `F5` opens the library overlay.

## Tests

- Tuning: for MIDI 28, 40, 52, 64, 76, 88 the estimated fundamental (FFT peak with parabolic
  interpolation over 1 s of a pluck) is within **+-5 cents**.
- Decay: measured T60 of a pluck at MIDI 52 is within +-25 % of `str.decay` for 1, 4 and 10 s.
- Chunked recursion equals a straightforward per-sample reference implementation (test-only,
  short signal) to within 1e-6.
- Stability: 20 s of maximum decay, maximum brightness and maximum sympathetic coupling stays
  finite and bounded below the ceiling before the limiter engages more than 1 dB.
- Sympathetic: exciting a main string at a pitch present in the bank yields at least 6 dB more
  sympathetic energy than exciting a pitch absent from it.
- Strum: a headless drag across rows 3..9 of the string area produces one pluck per crossed
  string in order, with velocities increasing for a faster drag.
- Every factory preset renders finite, non-silent output below the ceiling.
- Golden snapshots at 100x30 and 80x24 for every factory skin.
