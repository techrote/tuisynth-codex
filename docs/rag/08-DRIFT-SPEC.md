---
corpus: tuisynth
programme: trio
document_id: TRIO-DRIFT
status: authority
---
# DRIFT: granular air and vowel-cloud instrument

## Sound identity

Air you can play: breath tones, wind, whistling howls and choir-like vowel clouds made of
thousands of tiny grains of coloured noise and soft tones, shaped by a morphing formant
filter. DRIFT is played by **steering weather**: the XY map changes vowel and storm density
while notes come from the keyboards or MIDI.

## DSP (TRIO-013)

### Sources (per engine, regenerated when source colour changes)

Two-second looped buffers at the engine sample rate, generated with seeded NumPy:

- **noise**: white noise shaped in the frequency domain by a spectral tilt of
  `src.color * 6 dB/octave` (-1 = brown-ish, 0 = white, +1 = blue-ish), normalised to RMS 0.25;
- **tone**: band-limited additive tone at 220 Hz, harmonics 1-8 with `1/k` amplitudes and
  random phases (a soft flute/ocarina-like air tone), normalised to RMS 0.25;
- **breath**: noise passed through a gentle 1.2 kHz band-pass, used to add breathiness.

A grain reads `mix = (1 - src.tone) * noise + src.tone * tone + src.breath * breath`.
When `src.color` changes, the complete seeded bank is regenerated at the next block boundary;
the previous bank and replacement crossfade over 50 ms.

### Grain scheduler and renderer

- Each sounding note is a **stream** (voice) with pitch, velocity and an amp ADSR. Up to six
  streams share a pool of at most `gr.max` (16-96) active grains. When the pool is full, new
  grains are dropped (counted in telemetry), never voices.
- Per block and per stream, the number of new grains is `Poisson(density * block_seconds)`
  from the stream's seeded Generator, where `density = gr.density * field_density * gust`.
  Each grain draws: start frame uniform in the block; duration `gr.size * (1 + gr.size_jit *
  U(-0.5, 0.5))`, clamped to 5-500 ms; source start `gr.pos + gr.pos_scatter * U(-0.5, 0.5)` (wrapping);
  playback ratio `freq / 220 * 2**(gr.pitch_scatter * U(-1, 1) / 1200)` for the tone path
  (the noise path uses the same ratio, which only changes its colour); pan
  `0.5 + gr.spread * U(-0.5, 0.5)` (constant-power); amplitude = velocity x stream envelope.
- The implemented field density is `0.25 + 3.75 * field.y`; a held gust ramps from 0 to 1
  over 300 ms and multiplies density by `1 + held_gust`. Effective wind is
  `min(1, wind.gust + 0.5 * held_gust)`; the seeded smooth-random value contributes the
  additional density factor `1 + effective_wind * 0.8 * g(t)`. Per-stream arrivals are drawn
  for the stream's active portion of the current 256-frame block, including notes started at a
  sample-offset event.
- `field.x` source movement is `(field.x - 0.5) * field.amount` added to `gr.pos`, with wrapping.
- Windows (`gr.window`): `hann`, `tukey` (25 %), `expodec` (exponential decay with a 2 ms
  linear fade-in), `rexpodec` (mirror). Every window starts and ends at exactly zero.
- Rendering: for each active grain compute its overlap with the current block, read the
  source with linear interpolation at the grain's ratio, multiply by the window segment and
  pan gains, and add into the block. A bounded Python loop over active grains is allowed
  (at most `gr.max` iterations per block); each iteration must be a handful of NumPy
  operations, not a per-sample loop.

### Formant bank (on the summed grain bus)

Five parallel band-pass biquads per channel. Vowel table (approximate soprano formants after
the Csound manual's formant table; frequency Hz / bandwidth Hz / gain dB):

| Vowel | F1 | F2 | F3 | F4 | F5 |
|---|---|---|---|---|---|
| A | 800/80/0 | 1150/90/-6 | 2900/120/-32 | 3900/130/-20 | 4950/140/-50 |
| E | 350/60/0 | 2000/100/-20 | 2800/120/-15 | 3600/150/-40 | 4950/200/-56 |
| I | 270/60/0 | 2140/90/-12 | 2950/100/-26 | 3900/120/-26 | 4950/120/-44 |
| O | 450/70/0 | 800/80/-11 | 2830/100/-22 | 3800/130/-22 | 4950/135/-50 |
| U | 325/50/0 | 700/60/-16 | 2700/170/-35 | 3800/180/-40 | 4950/200/-60 |

`fmt.vowel` in 0..4 interpolates between adjacent rows (A=0, E=1, I=2, O=3, U=4);
frequencies are multiplied by `fmt.shift` (0.6-1.5), bandwidths by `1 / fmt.q`; output mixed by
`fmt.mix`. Coefficients are recomputed per block with 20 ms smoothing of `fmt.vowel`.

### Wind

`wind.rate` (0.01-2 Hz) drives a seeded smooth-random gust signal that scales density by
`1 + wind.gust * 0.8 * g(t)` and tilts brightness. `wind.howl` is a global-only modulatable
control that mixes a narrow (Q 25)
band-pass noise whose centre sweeps 600-2,500 Hz with the gust signal.

### Field (performance) parameters

`field.x` and `field.y` (0..1, modulatable) are offsets driven by the XY map, not stored as
preset values unless the user saves: `x` adds to the vowel (`x * 4` blended with
`fmt.vowel` by `field.amount`) and moves `gr.pos`; `y` scales density from 0.25x (bottom,
"calm") to 4x (top, "storm") and raises brightness. Holding the mouse button in the map
applies a **gust** (density x2, `wind.gust` +0.5) with 300 ms attack/release.
The registry exposes `field.x` (default 0) and `field.y` (default 0.5) as modulatable controls;
factory presets omit them so the live map position stays independent of factory sound settings.

### Parameters

| Key | Range | Default |
|---|---|---|
| `src.color` | -1..1 | -0.2 |
| `src.tone`, `src.breath` | 0-1 | 0.35, 0.2 |
| `gr.density` | 1-200 grains/s (log) | 35 |
| `gr.size` | 5-500 ms (log) | 90 |
| `gr.size_jit`, `gr.pos`, `gr.pos_scatter`, `gr.spread` | 0-1 | 0.3, 0.5, 0.4, 0.7 |
| `gr.pitch_scatter` | 0-1,200 cents | 12 |
| `gr.window` | choice | hann |
| `gr.max` | discrete 16-96 | 64 |
| `fmt.vowel` | 0-4 | 0 |
| `fmt.shift` | 0.6-1.5 | 1.0 |
| `fmt.q`, `fmt.mix`, `field.amount` | 0.3-3, 0-1, 0-1 | 1.0, 0.7, 0.8 |
| `wind.gust`, `wind.howl` | 0-1 | 0.3, 0.1 |
| `wind.rate` | 0.01-2 Hz (log) | 0.12 |
| `amp.a/d/s/r` | as AURORA | 0.6/0.8/0.8/2.5 |
| `fx.reverb.*`, `fx.delay.*`, `master.*` | shared | 0.9/0.3/0.4; 0.5/0.3/0.2; 0.75/0.0 |

Polyphony: 6 streams. `legato_glide = True` (glissando retargets the stream pitch).

### Factory presets (>= 8)

`squall-choir`, `desert-flute`, `monsoon-breath`, `howling-pass`, `whisper-field`,
`vowel-sweep`, `glass-wind`, `deep-exhale`.

## UI (TRIO-014)

Full-screen weather map with pop-over HUD drawers, 100x30:

```text
╭─ ≈ D R I F T ≈ ── squall-choir ──────────── skin squall · midi: none · 2/6 · 41 grains · cpu 21% ─╮
│ A           E            I              O               U                              ▲ storm    │
│   ·   ( ( ( ( · ·     ∙        ·  ∙   ·   ) ) ) )    ·      ∙    ·          ·                     │
│  ~ ~ ( ( ·  ∙  •  ·  ~ ~ ~ ~    ∙  •  ∙  ) )  ~ ~ ~    ·   ∙      ·    ·      ~ ~ ~               │
│    ( (  ·  •  ∙  ·    ·   ∙   ·  •   ·   ) )     ·        ∙  ·        ·                           │
│  ~ ( ·  ∙   •   @  ·   ∙  ·   •  ·  ∙  ·  ) ~ ~ ~      ·     ∙   ·                                │
│    ( (  ·  ∙  ·   ∙  ·   ·   ∙  ·   ·   ) )      ·   ∙     ·                                      │
│   ~ ~ ( ( ·   ∙   ·      ·    ∙    ) ) ~ ~ ~ ~    ·        ·                                       │
│                                                                                       ▼ calm      │
│ ┌ GRAIN (F3) ───────────────────────┐                     ┌ KEYS ──────── oct 0 · vel .70 ───────┐ │
│ │ density ━━━━●━━ 35/s  size ━━●━ 90ms                    │ (compact 2-octave on-screen piano)   │ │
│ │ scatter ━●━━━━ 12c    window ◄ hann ►                   │                                      │ │
│ └───────────────────────────────────┘                     └──────────────────────────────────────┘ │
╰─ F1 help · F2 map · F3 grain · F4 air · F5 library · F6 skin · F7 midi · F9 panic · ^Q quit ───────╯
```

- **Map**: background isobars from a slowly drifting seeded 2-D value-noise field drawn with
  the skin `isobar` glyph ramp; foreground particles are the **real active grains** from
  telemetry: x from grain pan, y from log pitch ratio, glyph from the skin `grain` ramp by
  amplitude, colour by normalized age. The active-grain count and its synchronized pan, ratio,
  amplitude and age vectors come from one snapshot and are bounded at the `gr.max` ceiling of
  96. The storm cursor `@` (skin glyph) sits at `field.x/field.y`.
- **Gestures**: left-drag moves the cursor (sends `field.x`, `field.y`); holding without
  moving keeps a gust active; right-click recentres the cursor; wheel changes `gr.density`.
  Keyboard twin: focus the map, arrows move the cursor 2 % per press, `PageUp`/`PageDown`
  move it 10 % vertically, `Enter` toggles a held gust, `Delete` recentres.
- **Drawers**: `F3` grain, `F4` air (source, formant, wind), `F5` library. Grain and Air drawers
  overlay the lower map and close with `Esc`; only one is open at a time. The F5 library picks a
  factory sound or colourway. Shared F8 preset save/rename/delete actions remain available.
- The keyboard strip and status meters always remain visible.
- The built-in `mono` skin remains immutable. DRIFT supplies its own `DRIFT WEATHER` header and
  ASCII-safe isobar, grain and cursor glyphs, and maps age/isobar levels onto the shared grayscale
  semantic styles.

## Tests

- Spawn statistics: 10 s at 50 grains/s (seeded) spawns 500 +- 10 % grains.
- Pool bound: active grains never exceed `gr.max`; drops are counted.
- Windows start and end at exactly 0; `expodec` reaches peak after ~2 ms.
- Formant: white noise through vowel A shows the strongest spectral peaks within +-15 % of
  800 Hz and 1,150 Hz; vowel I within +-15 % of 270 Hz and 2,140 Hz.
- `field.x = 0` selects A and `1` selects U when `field.amount = 1`.
- Determinism with equal seeds; finite output below the ceiling for every factory preset.
- UI (headless): drag in the map emits `field.x/field.y` changes along the path; holding
  emits a gust; particles drawn equal the telemetry grain count when cells allow;
  golden snapshots at 100x30 and 80x24 for every factory skin.
