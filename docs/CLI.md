# Command-line reference

Examples use installed console commands. A source or candidate-bundle launcher accepts the same options after the instrument name: `launch.cmd aurora --selftest` or `sh ./launch.sh aurora --selftest`. See [installation](INSTALL.md) for the separate launcher options that appear before the instrument name.

<!-- generated:cli:start -->

## Shared command options

These options are read from the actual argparse parser. They apply to `aurora`, `loom` and `drift`, after the instrument name when using a launcher. Option/list/selftest/render/snapshot commands exit without entering the full-screen application. Device-listing commands may enumerate hardware; selftest/render/snapshot never do.

| Option | Default | Purpose |
| --- | --- | --- |
| `-h`, `--help` | — | Show argument help and exit. |
| `--version` | — | Print installed command/version and exit. |
| `--skin` | — | Select a factory/user skin ID; unknown IDs fall back to mono with a warning. |
| `--preset` | — | Load a factory/user preset by ID (not a JSON file path). |
| `--midi` | — | Select MIDI input by zero-based port index or name substring. |
| `--midi-channel` | 0 | Filter incoming MIDI: 0 means omni; 1–16 selects a channel. Choices: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16. |
| `--no-audio` | False | Use the device-free/null audio backend for interactive operation. |
| `--device` | — | Select audio output by device index or name. |
| `--sample-rate` | 48000 | Engine/offline sample rate in Hz. Choices: 44100, 48000. |
| `--ascii` | False | Force monochrome ASCII-safe drawing. |
| `--mono` | False | Force the built-in mono skin. |
| `--data-dir` | — | Use a shared user-data root; instrument name is appended. |
| `--list-skins` | False | List installed factory/user skin IDs and exit. |
| `--list-presets` | False | List factory/user preset IDs and names and exit. |
| `--list-midi` | False | List MIDI ports (or a readable unavailable message) and exit. |
| `--list-devices` | False | List audio devices (or a readable unavailable message) and exit. |
| `--selftest` | False | Validate factory presets/skins and render offline audio; no devices opened. |
| `--render` | — | Write a stereo 16-bit PCM WAV file without opening devices. |
| `--notes` | C4,E4,G4 | Comma-separated render notes, for example C4,E4,G4 or F#3,Bb3. |
| `--seconds` | 4.0 | Offline render duration, finite 0.01–120 seconds. |
| `--seed` | 0 | Deterministic non-negative random seed. |
| `--snapshot` | — | Print a deterministic terminal frame, for example 100x30 (maximum 500x200). |
| `--screen` | main | Choose a snapshot screen; has no effect on normal interactive startup. |

## Snapshot screen names

| Command | Accepted --screen values |
| --- | --- |
| aurora | main, help, palette, skins, midi, presets, sequencer, modulation, play, shape, space, library |
| loom | main, help, palette, skins, midi, presets, sequencer, modulation, strings, panels, sympathy, library |
| drift | main, help, palette, skins, midi, presets, sequencer, modulation, map, grain, air, library |

<!-- generated:cli:end -->

## Offline examples

```powershell
aurora --preset glacier-choir --render "pad chord.wav" --notes C3,G3,D4 --seconds 8 --seed 0
loom --list-presets
loom --snapshot 80x24 --screen strings --skin rosewood
drift --snapshot 100x30 --screen modulation --mono
drift --selftest --sample-rate 44100
```

A render creates the requested output directory if needed and overwrites an existing file at that path. Notes are held for approximately 78% of the requested duration; the remaining duration captures release. This is an offline file export, not a recording of an interactive session. `--snapshot` defaults to mono unless a skin is specified and freezes its test scene. A snapshot validates layout, not live audio or physical terminal gestures.
