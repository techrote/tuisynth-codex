---
corpus: tuisynth
programme: trio
document_id: TRIO-AURORA
status: authority
---
# AURORA: spectral PADsynth pad engine

## Sound identity

Wide, smooth, slowly breathing pads and choirs built from a **painted harmonic profile**.
Each harmonic is smeared into a Gaussian band whose width grows with harmonic number, giving
the shimmering ensemble quality of Nasca's PADsynth algorithm. No oscillator detune-chorus is
needed for width: left and right channels use independently randomised phases.

## DSP (TRIO-009)

### Table generation (Nasca PADsynth)

For each **zone** (one table per octave, base notes C1, C2 ... C7 => 7 zones) build a
spectrum of `N = 2**18` samples at the engine sample rate:

```text
for k in 1..H:                                  H = spec.count (16, 32 or 64)
    f_k   = f0 * k ** spec.stretch              exponent; 1.0 = exactly harmonic
    bw_hz = (2 ** (spec.bw / 1200) - 1) * f0 * k ** spec.bwscale
    A_k   = harmonics[k-1] * 10 ** (spec.tilt * log2(k) / 20)
    add A_k * gaussian(freq_bins, centre=f_k, sigma=bw_hz/2) to magnitude[]
magnitude += spec.noise * 1e-3 * mean(magnitude)          optional noise floor
phase_L, phase_R = uniform(0, 2pi) from Generator(seed=spec.seed*2), Generator(spec.seed*2+1)
table_L = irfft(magnitude * exp(i*phase_L)), table_R likewise
normalise both by the same factor so max(abs) == 0.9
```

- Use vectorised NumPy only (`numpy.fft.irfft`, broadcasting the Gaussian over a window of
  +-4 sigma around each harmonic, not over all bins).
- Bins above Nyquist are discarded; harmonics whose `f_k` exceeds 0.45 * sample rate are skipped.
- Tables are cached by a hash of `(sample rate, zone, spectral params, harmonics)`.
- Regeneration runs on a **worker thread**, debounced 150 ms after the last spectral change.
  The audio thread swaps to the new table set at a block boundary and crossfades old->new over
  50 ms. Voices never stop sounding during regeneration. Memory bound: two table sets.

### Voice

- Playback: phase accumulator over the zone table whose base note is nearest below the
  played note, advancing `freq / zone_f0` table samples per output sample (the table was
  generated so that playback at ratio 1.0 sounds `zone_f0`), linear interpolation with
  wrap-around, vectorised per block, separate L/R tables. `osc.detune` adds a second, slightly detuned read head per channel (0-50 cents)
  mixed at -6 dB; `osc.width` crossfades between mono (L table both sides) and full L/R.
- State-variable filter (2-pole, `lp`/`bp`/`hp`) from `trio_kit.dsp`, coefficients updated per
  block with 5 ms smoothing; cutoff = `flt.cut * 2**(flt.env*fenv*5 + flt.key*(pitch-60)/12)`.
- Amp ADSR and filter ADSR (`trio_kit.dsp.Adsr`, exponential segments, per-block vectorised).
- One LFO per voice (`sine`, `triangle`, smooth random) with random start phase; target pitch
  (+-50 cents), cutoff (+-2 octaves), amplitude (tremolo) or pan.
- Bus: `trio_kit` chorus, stereo delay and reverb (shared DSP), then master.

### Parameters

| Key | Range | Default | Notes |
|---|---|---|---|
| `spec.count` | choice 16/32/64 | 32 | harmonics used |
| `spec.bw` | 1-400 cents (log) | 60 | base bandwidth |
| `spec.bwscale` | 0-2 | 1.0 | bandwidth growth per harmonic |
| `spec.stretch` | 0.95-1.05 | 1.0 | partial stretch (1.0 = harmonic) |
| `spec.tilt` | -12..+6 dB/oct | -3 | brightness tilt |
| `spec.noise` | 0-1 | 0 | spectral noise floor |
| `spec.seed` | discrete 0-9999 | 1 | phase seed |
| `osc.octave` | discrete -2..+2 | 0 | |
| `osc.detune` | 0-50 cents | 6 | second read head |
| `osc.width` | 0-1 | 0.85 | stereo decorrelation |
| `amp.a/d/s/r` | 0.001-20 s / 0.01-20 s / 0-1 / 0.01-30 s | 1.8/1.5/0.8/4.0 | |
| `amp.vel` | 0-1 | 0.4 | velocity sensitivity |
| `flt.mode` | choice lp/bp/hp | lp | |
| `flt.cut` | 20-20,000 Hz (log) | 5,000 | |
| `flt.res` | 0-0.95 | 0.1 | |
| `flt.env`, `flt.key` | -1..1, 0..1 | 0.2, 0.3 | |
| `fenv.a/d/s/r` | as amp | 2.5/2.0/0.5/5.0 | |
| `lfo.rate`, `lfo.depth`, `lfo.wave`, `lfo.tgt` | 0.01-10 Hz (log), 0-1, choice, choice | 0.15, 0.2, smooth, cutoff | |
| `fx.chorus.mix`, `fx.delay.time/fb/mix`, `fx.reverb.size/damp/mix` | see TRIO-ENGINE shared FX | 0.2; 0.42/0.35/0.15; 0.85/0.4/0.35 | |
| `master.level`, `master.drive` | 0-1 | 0.75, 0.1 | |

`extras.harmonics`: list of 64 floats in 0..1 (validated; shorter lists padded with 0).
Polyphony 8. `legato_glide = False`.

### Factory presets (>= 8)

`glacier-choir`, `northern-veil`, `cathedral-air` (narrow bandwidth organ-like),
`solar-bloom`, `ice-strings` (bright, fast attack), `deep-ocean` (sub-heavy, dark),
`hollow-partials` (odd harmonics only), `stretch-bells` (inharmonic stretch 1.03).

## UI (TRIO-010)

Full layout, 100x30 (compact layout drops the waterfall to 3 rows and harmonics to 32 bars):

```text
╭─ ✶ A U R O R A ✶ ── glacier-choir* ─────────────── skin borealis · midi: none · 3/8 v · cpu 9% ─╮
│ ░░▒▒▓▓  aurora waterfall: columns = harmonics/log-frequency, rows = time (newest at bottom)  ▓▒░ │
│  . :·:.  ::;;!!||  ;:.     . :;!|||!;:.        .:;!;:.          ..:::..                        │
│ .:;!|┃┃|!;:.  .:;!|┃┃|!:.    .:;!|┃|!;:.   .:;!|!;:.     .:;!;:.     .:;:.                    │
├─ HARMONICS · drag paint · right-drag erase · wheel fine ─────────────────── count 32 · tilt -3dB ─┤
│ █                                                                                               │
│ █  ▆                                                                                            │
│ █  █  ▅     ▃                                                                                   │
│ █  █  █  ▄  █  ▂  ▁  ▂  ▁                                                                       │
│ 1  2  3  4  5  6  7  8  9 ...                                                                   │
├─ SHAPE ─────────────── AMP ──────────────── FILTER ───────────── MOTION ─────── SPACE ───────────┤
│ bandwidth ━━━━●━━ 60c   A ━━●━━━ 1.8s      cutoff ━━━━━●━ 5.0k  rate ●━━━━ .15  reverb ━━━━●━ .35 │
│ bw scale  ━━━●━━━ 1.0   R ━━━━●━ 4.0s      reso   ●━━━━━━ .10   depth ━●━━━ .20 delay  ━●━━━━ .15 │
├─ KEYS · click=play · depth=velocity · drag=gliss · wheel=octave ────────────────── oct 0 vel .70 ─┤
│ ┃ ▐█▌ ▐█▌ ┃ ▐█▌ ▐█▌ ▐█▌ ┃ ▐█▌ ▐█▌ ┃ ▐█▌ ▐█▌ ▐█▌ ┃ ▐█▌ ▐█▌ ┃ ▐█▌ ▐█▌ ▐█▌ ┃ ▐█▌ ▐█▌ ┃ ▐█▌ ▐█▌ ▐█▌ ┃     │
│ ┃  C3 ┃  D  ┃  E  ┃  F  ┃  G  ┃  A  ┃  B  ┃  C4 ┃  D  ┃  E  ┃  F  ┃  G  ┃  A  ┃  B  ┃  C5 ┃       │
╰─ F1 help · F2 PLAY · F3 SHAPE · F4 SPACE · F5 LIBRARY · F6 skin · F7 midi · F9 panic · ^Q quit ──╯
```

(The keyboard art above is illustrative; the widget geometry contract is in TRIO-INPUT.)

- **Waterfall**: 4-8 rows scrolling upward at ~12 rows/s; each column is a log-frequency band;
  glyph from the skin `density` ramp and colour from the skin `aurora` ramp, driven by the
  current table magnitude multiplied by the summed envelope level of active voices and the LFO.
  Silent when no voice sounds (a faint idle shimmer is allowed only from skin `idle` glyphs).
- **Harmonic painter**: one bar per harmonic (64 when width allows, else 32). Left-drag sets
  bar heights along the drag path (interpolate between sampled points so fast drags leave no
  gaps). Right-drag erases to 0. Wheel adjusts one bar. Keyboard twin: focus the painter,
  `Left/Right` select bar, `Up/Down` +-0.05, `PageUp/PageDown` +-0.25, `Delete` zero,
  `Ctrl+R` randomise smoothly, `Ctrl+E` even-only, `Ctrl+O` odd-only.
- Screens: **PLAY** (as above), **SHAPE** (all spectral + envelope params, large painter),
  **SPACE** (motion + FX), **LIBRARY** (presets and skins with live preview).
- `--render` and `--selftest` must not start the regeneration worker thread in a way that
  leaves threads running at exit.

## Tests

- Spectrum: rendered table FFT has peaks within 1 % of `k * f0` for the first 8 harmonics;
  increasing `spec.bw` increases measured -6 dB bandwidth of harmonic 4.
- Determinism with equal seeds; different `spec.seed` gives different waveforms with equal
  magnitude spectrum (within tolerance).
- L/R decorrelation: Pearson correlation of 1 s of L vs R output < 0.5 at `osc.width = 1`,
  > 0.99 at `osc.width = 0`.
- Regeneration: changing harmonics while notes sound never produces a block with a step
  discontinuity > 0.2 and keeps output finite; worker thread joins on engine close.
- Table generation for all 7 zones at 64 harmonics finishes in < 10 s on CI (generous gate).
- Every factory preset renders 2 s of a C major chord finite, non-silent, below the ceiling.
- UI (headless): painter drag sets expected bar heights; keyboard twin equivalence;
  golden snapshot of PLAY at 100x30 and compact at 80x24 for every factory skin.
