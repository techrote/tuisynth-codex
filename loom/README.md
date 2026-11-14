# LOOM — plucked and bowed strings

LOOM combines waveguide strings, pluck/bow excitation, a resonant body and a sympathetic bank. Its single playing surface keeps string gesture, parameter groups and sympathetic tuning together, with a short piano for notes or chord selection. It has eight direct pluck voices; bow use is limited to four voices by the instrument. A mouse drag crosses string rows in order, and a captured bow ends on release.

From the repository/candidate root:

```powershell
.\launch.cmd loom --no-audio
.\launch.cmd --extras audio,midi loom --preset rosewood-harp --skin rosewood
.\launch.cmd loom --selftest
.\launch.cmd loom --preset sitar-dawn --render "loom strings.wav" --notes C3,G3,C4 --seconds 8
```

POSIX uses `sh ./launch.sh` with the same arguments. See [installation](../docs/INSTALL.md) and the [CLI reference](../docs/CLI.md). Ctrl+Q quits; F9 releases sounding notes.

## First performance

Start with Rosewood Harp and drag across the strings. Right-click one row to mute it. Focus the strings with F2 and use comma/period to strum, or Enter to trigger the selected row. Slash switches DIRECT and CHORD mode. DIRECT plays notes from the piano normally; CHORD uses held piano/computer/MIDI pitches to tune the string surface, so use a strum gesture to sound that chord. The shared arpeggiator can consume held chords in either mode.

F3 focuses parameter panels. In compact panels, Left/Right chooses a parameter, Up/Down adjusts it, PageUp/PageDown changes it by ten steps, Home/End sets a limit, and Delete/right-click restores its default. Full panels use the [standard parameter controls](../docs/CONTROLS.md#standard-parameter-controls). F4 focuses the sympathetic column: arrows choose a note and Enter sets the root. F5 opens the shared preset actions. Space always controls sequencer transport outside MOD; use Enter to play a focused string.

For bowing, choose bow excitation in the Exciter controls or load a bow preset, then hold/drag on the string surface. Keyboard Enter makes a brief bow trigger rather than a sustained key-release-controlled bow. Shift+F3 opens the thread-knot sequencer; Shift+F4 opens the matrix and FX rack.

<!-- generated:instrument:start -->

## Areas and controls

| Key | Area |
| --- | --- |
| `F2` | STRINGS |
| `F3` | PANELS |
| `F4` | SYMPATHY |
| `F5` | LIBRARY |

The following keyboard controls act on the focused main gesture area. Shared piano, presets, skins, sequencing and MOD controls are in [the control reference](../docs/CONTROLS.md).

| Key or keys | Action |
| --- | --- |
| `Up/Right / Down/Left` | Select a higher / lower string index. |
| `Enter` | Play the selected string; a keyboard bow trigger releases immediately. |
| `, / .` | Strum in opposite directions across the current held chord. |
| `/` | Toggle DIRECT / CHORD piano mode; CHORD tunes the surface instead of playing direct notes. |

| Mouse gesture | Action |
| --- | --- |
| Left press/drag across rows | Pluck strings in crossing order; in bow excitation, sustain crossed strings until release. |
| Release, including outside the surface | End the captured bow/strum gesture. |
| Right-click a string | Mute that string. |

## Factory presets

| Preset ID for --preset | Name | Description |
| --- | --- | --- |
| `autoharp-dorian` | Autoharp Dorian | Chord-spread strings over a Dorian sympathetic bed. |
| `cello-drone` | Cello Drone | A soft bowed line supported by low sympathetic root and fifth strings. |
| `glass-koto` | Glass Koto | A bright, short koto-like pluck with a light glassy sustain. |
| `hardingfele` | Hardingfele | A sustained bowed tone with strong scale-matched sympathetic strings. |
| `muted-guitar` | Muted Guitar | A dark, short guitar pluck with a quick palm-muted release. |
| `rosewood-harp` | Rosewood Harp | A warm, open pluck with a gentle pentatonic sympathy bed. |
| `sitar-dawn` | Sitar Dawn | A bright pluck with Bhairav drones and a resonant sitar-like body. |
| `steel-shimmer` | Steel Shimmer | A hard bright pluck with a restrained, high sympathetic shimmer. |

## Factory skins

| Skin ID for --skin | Name |
| --- | --- |
| `mono` | MONO |
| `brass` | BRASS |
| `indigo-loom` | INDIGO LOOM |
| `rosewood` | ROSEWOOD |

## Frozen terminal view

This is the existing deterministic 100×30 text fixture [loom-rosewood-100x30.txt](tests/snapshots/loom-rosewood-100x30.txt); it is a software layout snapshot, not a photograph of a physical terminal. Colour/style is not represented in this text. Full and compact fixtures remain in [tests/snapshots](tests/snapshots).

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ≋ L O O M ≋  ♬ R O S E W O O D ♬ · Init · rosewood · MIDI: stopped · 0/8                         │
│ voices 0/8  CPU 0.0%  limiter 1.00  octave +0  velocity 0.70  latch off                          │
│ ╭STRINGS · DIRECT/PLUCK · drag to play · right mute─────────────╮  ╭SYMPATHETIC · 12 resonators╮ │
│ │D5  ────────────────────────────────────────────────────────── │  │C3   ─────── C4   ───────  │ │
│ │A4  ────────────────────────────────────────────────────────── │  │D3   ─────── D4   ───────  │ │
│ │E4  ────────────────────────────────────────────────────────── │  │E3   ─────── E4   ───────  │ │
│ │B3  ────────────────────────────────────────────────────────── │  │F#3  ─────── F#4  ───────  │ │
│ │G3  ────────────────────────────────────────────────────────── │  │G#3  ─────── G#4  ───────  │ │
│ │D3  ────────────────────────────────────────────────────────── │  │A#3  ─────── A#4  ───────  │ │
│ │A2  ────────────────────────────────────────────────────────── │  │                           │ │
│ │E2  ──────────────────────────────────────────────────────────>│  │                           │ │
│ ╰8 tuned strings · arrows select · Enter pluck/bow · , . strum ·╯  ╰F4 focus · Enter sets root─╯ │
│ ╭EXCITE───────────╮╭STRING───────────╮╭BODY─────────────╮╭SYMPATHY─────────╮╭PLAY──────────────╮ │
│ │mode <pluck>     ││decay ---#-- 6.0s││type <guitar>    ││mix --#----- 0.30││mode <direct>     │ │
│ │hard ---#--- 0.55││relea --#--- 0.4s││mix ----#--- 0.50││coupl --#--- 0.40││strings <8>       │ │
│ │press --#--- 0.50││brigh ---#-- 0.60││size --#---- 1.00││decay ---#- 12.0s││spread -#---- 18ms│ │
│ │speed ----#- 0.70││pick -#----- 0.13││                 ││tuning <scale>   ││                  │ │
│ │rosin --#--- 0.30││                 ││                 ││scale <dorian>   ││                  │ │
│ │                 ││                 ││                 ││root <D>         ││                  │ │
│ │                 ││                 ││                 ││                 ││                  │ │
│ ╰─────────────────╯╰─────────────────╯╰─────────────────╯╰─────────────────╯╰──────────────────╯ │
│ PIANO · DIRECT · default E2 A2 D3 G3 B3 E4 A4 D5 · piano plays notes                             │
│ ┌─██─██─┐┌─██─██─██─┐┌─██─██─┐┌─██─██─██─┐                                                       │
│ │ ██ ██ ││ ██ ██ ██ ││ ██ ██ ││ ██ ██ ██ │                                                       │
│ C3│D3│E3│F3│G3│A3│B3│C4│D4│E4│F4│G4│A4│B4│                                                       │
│ └─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘└─┘                                                       │
│                                                                                                  │
│ F2 strings · F3 panels · Shift+F3 sequencer · F4 sympathy · F5 presets · F6 skin · F9 · ^Q       │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

<!-- generated:instrument:end -->

## Presets and configuration

F8 → S saves the current parameters and shared sequence/modulation/effects as a user preset. Use F8 then R/D to rename/delete a selected user preset. Factory presets stay protected. The [installation guide](../docs/INSTALL.md#user-data-and-configuration) gives the user-data location. Playback mode, tuning and excitation belong to the preset; there is no automatic last-session restore.

## Evaluation focus

Listen to pluck decay and pitch, body/sympathetic response and bow continuity. Cross several strings quickly and slowly; check the release still ends bowing when the pointer is outside the surface. Compare DIRECT and CHORD input behavior, mute one string, panic, then reopen. Record physical results in [acceptance](../docs/ACCEPTANCE.md).
