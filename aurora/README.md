# AURORA — spectral pads and choirs

AURORA builds pitch-zone PADsynth tables from a 64-partial harmonic profile, then plays polyphonic pads through its envelope, filtering and shared effects. Painting changes the sound's spectral construction; a background regeneration worker publishes the completed table at an engine block boundary. The PLAY view combines a waterfall, macro controls and full-width piano. SHAPE exposes the harmonic profile and synthesis controls; SPACE exposes spatial/effect controls; LIBRARY selects sounds and skins.

From the repository/candidate root:

```powershell
.\launch.cmd aurora --no-audio
.\launch.cmd --extras audio,midi aurora --preset glacier-choir --skin borealis
.\launch.cmd aurora --selftest
.\launch.cmd aurora --preset northern-veil --render "aurora pad.wav" --notes C3,G3,D4 --seconds 8
```

POSIX uses `sh ./launch.sh` with the same arguments. See [installation](../docs/INSTALL.md) and the [CLI reference](../docs/CLI.md). Quit with Ctrl+Q; F9 releases held notes. A failed audio backend reports a device-free fallback so the controls and offline operations remain usable.

## First performance

Load a preset with F5/LIBRARY or F8, play a chord on the computer or on-screen keyboard, then paint a few harmonics while the chord sustains. F3/SHAPE exposes the larger painter: 64 visible bars at widths of 90 columns or more and 32 below that; the complete 64-partial profile remains stored. Use the SHAPE controls for bandwidth, stretch and other spectral parameters. Save the resulting sound under a new name using F8 then S.

AURORA faders use the [standard parameter keys](../docs/CONTROLS.md#standard-parameter-controls). Tab/Shift+Tab changes focus. F5 sound and skin lists preview the selected entry; arrows select and Enter applies. Press Shift+F3 for spectral-pillar sequencing or Shift+F4 for the matrix and FX rack. AURORA's worker readiness checks and finite offline renders do not establish real-time headroom on your audio hardware.

<!-- generated:instrument:start -->

## Areas and controls

| Key | Area |
| --- | --- |
| `F2` | PLAY |
| `F3` | SHAPE |
| `F4` | SPACE |
| `F5` | LIBRARY |

The following keyboard controls act on the focused main gesture area. Shared piano, presets, skins, sequencing and MOD controls are in [the control reference](../docs/CONTROLS.md).

| Key or keys | Action |
| --- | --- |
| `Left / Right` | Select a harmonic bar. |
| `Up / Down` | Raise / lower the selected amplitude by 0.05. |
| `PageUp / PageDown` | Raise / lower amplitude by 0.25. |
| `Delete` | Erase the selected harmonic. |
| `Ctrl+E` | Erase even-numbered harmonics (2, 4, …). |
| `Ctrl+O` | Erase odd-numbered harmonics (1, 3, …). |
| `Ctrl+R` | Generate the next deterministic smooth random harmonic profile. |

| Mouse gesture | Action |
| --- | --- |
| Left press/drag | Paint harmonic amplitudes; skipped bars are interpolated. |
| Right press/drag | Erase the traversed harmonics. |
| Wheel over a bar | Adjust that harmonic by 0.05 per reported wheel step. |

## Factory presets

| Preset ID for --preset | Name | Description |
| --- | --- | --- |
| `cathedral-air` | Cathedral Air | A narrow-bandwidth, organ-like tone with a spacious sustain. |
| `deep-ocean` | Deep Ocean | A subdued, low-centered pad with a dark, slowly moving edge. |
| `glacier-choir` | Glacier Choir | A slow, wide choir with a cool upper shimmer. |
| `hollow-partials` | Hollow Partials | An odd-harmonic hollow tone with a restrained stereo halo. |
| `ice-strings` | Ice Strings | A brighter string-like pad with a quick bow-on attack. |
| `northern-veil` | Northern Veil | A soft auroral sheet of sound with a long, distant tail. |
| `solar-bloom` | Solar Bloom | A bright, gently detuned bloom that opens as the note settles. |
| `stretch-bells` | Stretch Bells | Inharmonic stretched partials bloom into a slow metallic bell cloud. |

## Factory skins

| Skin ID for --skin | Name |
| --- | --- |
| `mono` | MONO |
| `borealis` | BOREALIS |
| `polar-night` | POLAR NIGHT |
| `solar-wind` | SOLAR WIND |

## Frozen terminal view

This is the existing deterministic 100×30 text fixture [aurora-play-borealis-100x30.txt](tests/snapshots/aurora-play-borealis-100x30.txt); it is a software layout snapshot, not a photograph of a physical terminal. Colour/style is not represented in this text. Full and compact fixtures remain in [tests/snapshots](tests/snapshots).

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ✶ A U R O R A ✶ | Init | borealis | MIDI: stopped                                                │
│ voices 0/8  CPU 0.0%  limiter 1.00  octave +0  velocity 0.70  latch off                          │
│ [PLAY]                  SHAPE                   SPACE                   LIBRARY                  │
│ AURORA WATERFALL · 0 voices · tables frozen · log partials                                       │
│ ----:::::::::::::::::::::::..................................................................... │
│ -------::::::::::::::::::::::................................................................... │
│ ----------:::::::::::::::::::::................................................................. │
│ ------------:::::::::::::::::::::............................................................... │
│ HARMONICS · 64 bars · drag paint / right-drag erase                                              │
│ @                                                                                                │
│ @ *+ == =- -- -- -: ::                                                                           │
│ | *+ == =- -- -- -: :: :: :: :: :: :: :: :: :: :: :: :. .. .. .. .. .. .. .. .. .. .. .. .. .. . │
│ 1   8   16   24   32   40   48   56   64                                                         │
│                                                                                                  │
│ Partials: < 32 >                Bandwidth                 60.00 Cutoff                  5000.00  │
│                                 ---------------------|--------- ------------------------|------  │
│ Amp release                4.00 LFO rate                   0.15 Reverb                     0.35  │
│ ----------------------|-------- ------------|------------------ ----------|--------------------  │
│ Master                     0.75 Octave                     0.00 Width                      0.85  │
│ ----------------------|-------- ---------------|--------------- --------------------------|----  │
│                                                                                                  │
│ ┌─██─██─┐┌─██─██─██─┐┌─██─██─┐┌─██─██─██─┐┌─██─██─┐┌─██─██─██─┐┌─██─██─┐┌─██─██─██─┐             │
│ │ ██ ██ ││ ██ ██ ██ ││ ██ ██ ││ ██ ██ ██ ││ ██ ██ ││ ██ ██ ██ ││ ██ ██ ││ ██ ██ ██ │             │
│ │ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ ││ │             │
│ C3│D3│E3│F3│G3│A3│B3│C4│D4│E4│F4│G4│A4│B4│C5│D5│E5│F5│G5│A5│B5│C6│D6│E6│F6│G6│A6│B6│             │
│ └─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘             │
│                                                                                                  │
│ PLAY · paint/R erase · wheel · Tab · F2-F5 · F6 skin · F8 presets · F9 · ^Q                      │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

<!-- generated:instrument:end -->

## Presets and configuration

F8 → S creates a user preset containing parameters, the harmonic profile and shared sequencer/modulation/effect extras. Factory presets stay protected. User presets/skins and MIDI mappings use the per-instrument directories described in [installation](../docs/INSTALL.md#user-data-and-configuration). CLI `--preset` accepts one of the IDs above or a saved user ID, not a path. There is no separate general settings file or automatic last-session restore.

## Evaluation focus

Listen for clean pad attacks/releases, worker updates during a held chord, stable tails after preset changes, and successful F9/exit cleanup. Compare each colourway and mono at 100×30 and 80×24; paint and erase while dragging outside the original region, then release. Record actual results in [acceptance](../docs/ACCEPTANCE.md).
