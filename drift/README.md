# DRIFT — breath, wind and vowel clouds

DRIFT schedules bounded grains from seeded source material and shapes their output through morphing vowel/formant filters. Up to six note streams share a bounded grain pool. Its weather map steers field X/Y: X traverses vowel colour and Y controls the field's density influence. Grain particles and isobars provide an instrument-specific view; Grain and Air drawers expose parameters without replacing the map.

From the repository/candidate root:

```powershell
.\launch.cmd drift --no-audio
.\launch.cmd --extras audio,midi drift --preset squall-choir --skin squall
.\launch.cmd drift --selftest
.\launch.cmd drift --preset desert-flute --render "drift breath.wav" --notes C4,E4,G4 --seconds 8
```

POSIX uses `sh ./launch.sh` with the same arguments. See [installation](../docs/INSTALL.md) and the [CLI reference](../docs/CLI.md). Ctrl+Q quits; F9 releases sounding notes.

## First performance

Play a note or chord, then drag on the weather field: the cursor moves and the held mouse gesture adds a gust until release. Right-click recenters. With the map focused, Enter latches a keyboard gust; press Enter again to release it. A mouse release ends only its own gust source. Wheel over the map to change grain density.

F3 opens Grain and F4 opens Air. In either drawer, Up/Down selects a parameter, Left/Right adjusts it, PageUp/PageDown uses five steps, Home/End selects its range limit, and Delete resets the default. Click selects/changes a control, wheel adjusts it and right-click resets it. Escape returns to the field. F5 opens separate preset/skin columns: Left/Right switches columns, Up/Down selects, Enter applies; mouse selection is also supported.

Shift+F3 opens the pressure-cell sequencer; Shift+F4 opens modulation and the rack. These areas use the [shared controls](../docs/CONTROLS.md). At compact sizes the drawings and drawers adapt; below 80×24 enlarge the terminal.

<!-- generated:instrument:start -->

## Areas and controls

| Key | Area |
| --- | --- |
| `F2` | MAP |
| `F3` | GRAIN |
| `F4` | AIR |
| `F5` | LIBRARY |

The following keyboard controls act on the focused main gesture area. Shared piano, presets, skins, sequencing and MOD controls are in [the control reference](../docs/CONTROLS.md).

| Key or keys | Action |
| --- | --- |
| `Arrow keys` | Move the field cursor 2% per press. |
| `PageUp / PageDown` | Move the cursor vertically by 10%. |
| `Enter` | Toggle the keyboard gust; press again to release it. |
| `Delete` | Recenter the field cursor. |

| Mouse gesture | Action |
| --- | --- |
| Left press/drag | Steer field X/Y and hold a mouse gust until release. |
| Release, including outside the map | Release the mouse gust; a separately latched keyboard gust remains active. |
| Right-click | Recenter field X/Y. |
| Wheel | Raise/lower grain density in its normalized parameter range. |

## Factory presets

| Preset ID for --preset | Name | Description |
| --- | --- | --- |
| `deep-exhale` | Deep Exhale | A deep U-shaped breath that unfolds in slow, soft-edged grains. |
| `desert-flute` | Desert Flute | Sparse, tonal grains with a low vowel and a long, sunlit tail. |
| `glass-wind` | Glass Wind | Bright pitched fragments and fine air scatter across a cold glass surface. |
| `howling-pass` | Howling Pass | A narrow whistling howl wrapped in high moving air and long grains. |
| `monsoon-breath` | Monsoon Breath | A wide rain of breath grains with gusting movement and a soft vowel body. |
| `squall-choir` | Squall Choir | A dense chorus of breath and soft tones swept through a rising squall. |
| `vowel-sweep` | Vowel Sweep | A clear vowel cloud ready to move from A through E, I, O and U. |
| `whisper-field` | Whisper Field | Slow, widely spaced whispers floating in a calm and open landscape. |

## Factory skins

| Skin ID for --skin | Name |
| --- | --- |
| `mono` | MONO |
| `desert-haze` | DESERT HAZE |
| `monsoon` | MONSOON |
| `squall` | SQUALL |

## Frozen terminal view

This is the existing deterministic 100×30 text fixture [map_squall_100x30.txt](tests/snapshots/map_squall_100x30.txt); it is a software layout snapshot, not a photograph of a physical terminal. Colour/style is not represented in this text. Full and compact fixtures remain in [tests/snapshots](tests/snapshots).

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ DRIFT / ~ S Q U A L L ~ / Init / squall / grains 0                                               │
│ voices 0/6  CPU 0.0%  limiter 1.00  octave +0  velocity 0.70  latch off                          │
│ FIELD x 0.00 | y 0.50   WIND +0.00   GUST 0.00                                                   │
│  STORM ^   A  E  I  O  U                                                                         │
│      ≈  ~ ~  ~                       ~      ~~     ~~    ~             ~~        ~    ~   .      │
│      ≈  ~ ~  ~                       ~      ~       ~~     ~~        ~~~~~~     ~~     ~         │
│      ≈  ~ ~     ................ ..        ~            ~~             ~~~                       │
│         ~ ~     .                     ~ ~    ≈      ≈≈≈            ~    ~           ~     ~~~    │
│         ~ ~ ~  .                    . ~ ~ ~                      ≈   ~  ~   ~~~~~      ~  ≈≈     │
│         ~ ~ ~  .                    . ~ ~ ~ ≈                     ≈  ~  ~   ~   ~         ≈      │
│       ≈    ~  ~                        ~ ~  ≈                     ≈  ~  ~  ~    ~   ~  ~   ≈     │
│   @       ~   ~                     ~  ~   ≈                      ≈  ~     ~     ~   ~  ~        │
│         ≈     ~        ~~~~~~~          ≈                            ~    ~       ~   ~   ~~     │
│           ≈                ≈≈≈≈≈≈≈≈                                    ~  ~        ~   ~    ~~   │
│        ≈≈≈                 ≈≈≈≈                                 ≈≈     ~  ~        ~   ~    ~~   │
│       ~~~~~          ~~     ≈≈       ≈≈≈                          ~   ~   ~       ~    ~    ~~   │
│                     ~    ~   ≈      ≈    ~    ~~~~~~~              ~     ~        ~         ~~   │
│                 ~~~~   ~     ≈         ~     ~       ~~~              ~~          ~   ~    ~~~   │
│        ...          ~     ~  ≈             ~               ~~~~~~~~~~             ~   ~    ~~~   │
│  CALM v  00 grains  CALM                                                                         │
│                                                                                                  │
│                                                                                                  │
│ ┌─██─██─┐┌─██─██─██─┐┌─██─██─┐┌─██─██─██─┐                                                       │
│ │ ██ ██ ││ ██ ██ ██ ││ ██ ██ ││ ██ ██ ██ │                                                       │
│ C3│D3│E3│F3│G3│A3│B3│C4│D4│E4│F4│G4│A4│B4│                                                       │
│ └─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘                                                       │
│                                                                                                  │
│ MAP drag/gust; right=centre; wheel=density; F2 map F3 grain Shift+F3 seq F4 air F5 lib           │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

<!-- generated:instrument:end -->

## Presets and configuration

F8 → S saves a user preset with synth parameters and shared sequencing/modulation/effects. Factory presets omit live field X/Y coordinates and load the registry defaults. An explicitly saved user preset includes the current X/Y parameter values, so reloading that user sound restores them. Factory presets remain protected. Use [user-data locations](../docs/INSTALL.md#user-data-and-configuration) for backup or alternate `--data-dir` roots. There is no automatic last-session restore.

## Evaluation focus

Listen for a consistent vowel journey across X, grain/density response across Y and audible gust response without stuck input. Move the pointer outside the map before release; compare an independently toggled keyboard gust. Test Grain/Air drawers, library selection and repeated preset changes with six held notes. Record actual listening, USB MIDI and stability in [acceptance](../docs/ACCEPTANCE.md).
