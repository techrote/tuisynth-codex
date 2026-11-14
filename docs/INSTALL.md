# Install, launch and recover TRIO

## Requirements and supported qualification

Use a 64-bit Python installation, version 3.11 or newer, with `venv` and `pip`. The qualification matrix is Ubuntu/Windows on Python 3.11/3.14. Other Python/platform combinations are not claimed by that matrix. Use Windows Terminal or a terminal with Unicode, colour and SGR mouse support; 100×30 cells is the full layout, 80×24 the compact layout. Below 80×24 the app asks you to enlarge it. No standalone Python executable is bundled.

The four distributions are `trio-kit`, `trio-aurora`, `trio-loom` and `trio-drift`, all version 0.1.0. Their console commands are `trio-demo`, `aurora`, `loom` and `drift`; instrument imports remain separate. Core dependencies include NumPy, SciPy, prompt-toolkit and wcwidth. Optional `audio` installs sounddevice; optional `midi` installs mido and python-rtmidi. Installing those packages does not establish that an audio device or MIDI port is available.

## First run and reuse

Extract the candidate to a writable directory or clone this repository. Keep the launcher and `tools` directory with the rest of the candidate. Run from that directory:

```powershell
.\launch.cmd aurora --no-audio
```

```sh
sh ./launch.sh aurora --no-audio
```

The launcher finds Python, checks its supported version, prepares `.trio-venv`, and installs all four distributions. A candidate with `wheels/` installs its four TRIO wheels; a source checkout builds from the four local package directories. The environment is shared by the three instruments. Repeat launches check its completed-installation state and reuse it without rerunning pip unnecessarily. Changes to package source/metadata or explicitly requested extras cause the appropriate setup to run again. A failed setup does not write a success marker; the next invocation retries it.

Launcher options come **before** the instrument name; application options come after it:

```text
launch.cmd [--extras audio,midi] [--wheelhouse DIR] [--setup-only] [--reinstall] aurora|loom|drift [application arguments]
```

| Launcher setting | Purpose |
|---|---|
| `--extras audio`, `--extras midi`, `--extras audio,midi` | Explicitly add the chosen optional hardware dependencies. Selection is additive and retained for repeat/retry setup. |
| `--wheelhouse DIR` | Install/build from an already populated local dependency directory without consulting an index. |
| `--setup-only` | Prepare the environment and exit without opening an instrument. |
| `--reinstall` | Force a fresh installation pass in the managed environment. |
| `TRIO_PYTHON` | Choose the Python executable; use a full path if needed. |
| `TRIO_VENV` | Choose an alternate managed environment directory. |
| `TRIO_WHEELHOUSE` | Supply the offline wheelhouse without repeating the option. |

For example, these commands install hardware support once, verify available ports, then open AURORA:

```powershell
.\launch.cmd --extras audio,midi --setup-only aurora
.\launch.cmd aurora --list-devices
.\launch.cmd aurora --list-midi
.\launch.cmd aurora --preset glacier-choir
```

Omitting `--extras` later preserves the existing selection. To remove optional backends, use a new `TRIO_VENV`; the launcher does not silently uninstall them. Paths and forwarded arguments may contain spaces:

```powershell
$env:TRIO_PYTHON = 'C:\Program Files\Python314\python.exe' # Use your actual Python path.
$env:TRIO_VENV = Join-Path $env:LOCALAPPDATA 'TRIO evaluation\venv'
.\launch.cmd drift --data-dir "$env:LOCALAPPDATA\TRIO evaluation\data" --no-audio
```

POSIX equivalents use `TRIO_PYTHON=/actual/path/to/python3` and `TRIO_VENV=/desired/path`; a path stored in the variable is a single executable name, not a shell command with extra arguments. No activation script or PowerShell execution-policy change is needed to run `launch.cmd`.

## Clean wheel installation

A release candidate's four wheels can also be installed directly. A new virtual environment keeps the candidate separate from other Python tools:

```powershell
python -m venv .evaluation-venv
$python = Join-Path $PWD '.evaluation-venv\Scripts\python.exe'
$wheels = @(Get-ChildItem .\wheels\*.whl | ForEach-Object FullName)
if ($wheels.Count -ne 4) { throw 'Expected exactly four TRIO wheels.' }
& $python -m pip install @wheels
if ($LASTEXITCODE -ne 0) { throw 'Wheel installation failed.' }
& $python -m pip check
& .\.evaluation-venv\Scripts\aurora.exe --selftest
& .\.evaluation-venv\Scripts\loom.exe --selftest
& .\.evaluation-venv\Scripts\drift.exe --selftest
```

The bare wheel install is core/device-free. Add explicit kit extras with the local kit wheel, or use the launcher `--extras` flow. Tests and release qualification use a separate environment and working directory to prove commands resolve installed files rather than the checkout. No PyPI publication is part of this candidate.

## Offline setup and pinned qualification dependencies

First obtain dependencies on an internet-connected machine with the same OS, architecture and Python version as the target. For a source checkout, a qualification wheelhouse can be populated with:

```powershell
python -m pip download --only-binary=:all: --dest wheelhouse -r requirements-dev.txt
# Optional; only if actual hardware operation is wanted:
python -m pip download --only-binary=:all: --dest wheelhouse "sounddevice>=0.5,<1" "mido>=1.3,<2" "python-rtmidi>=1.5,<2"
.\launch.cmd --wheelhouse .\wheelhouse --extras audio,midi aurora
```

On POSIX use the same Python commands followed by `sh ./launch.sh`. Build tools for source installation must be present in the wheelhouse as well as runtime dependencies. Native dependency wheels are platform/interpreter specific; a Windows/Python 3.11 wheelhouse is not a universal Linux/Python 3.14 cache. A missing or incompatible wheel fails setup with pip's diagnostic; provide it and retry. A release bundle carries the four TRIO wheels but does not implicitly contain all third-party binaries. See [release reproduction](RELEASE.md) for the recorded dependency/toolchain hashes.

## Audio and MIDI

Without `--no-audio`, interactive startup tries the sounddevice backend. An absent module, PortAudio failure or unavailable output device falls back to the null/device-free backend with a readable status. Headless snapshots, selftests and WAV renders never open audio/MIDI devices.

Use `--list-devices`, then `--device INDEX` or `--device "name"` to select audio output. Engine sample rate is 48 kHz by default; `--sample-rate 44100` is also supported. On Linux, sounddevice may need the distribution's PortAudio runtime and a working host audio service. Install those using your distribution's package manager if the error reports missing PortAudio. Optional backend availability and real-time headroom are machine-specific.

Use `--list-midi`, then `--midi INDEX` or `--midi "name substring"`; `--midi-channel 0` is omni and 1–16 filters one channel. F7 can change input during a session. The input service supports notes, velocity-zero note-off, sustain CC64, mod wheel CC1, pitch bend, panic CC120/123 and CC learn, and polls for reconnect. Unavailable MIDI leaves computer and mouse playing available. Focus a parameter and press Ctrl+L, then move the intended hardware controller to save its CC mapping. These paths are software-tested with fake devices; real USB reconnect and listening remain owner checks.

## User data and configuration

TRIO uses per-instrument user data, separate from the installed files and launcher environment:

| Platform/option | Instrument directory |
|---|---|
| Windows | `%APPDATA%\trio\aurora`, `loom` or `drift` |
| POSIX with absolute `XDG_DATA_HOME` | `$XDG_DATA_HOME/trio/aurora`, `loom` or `drift` |
| POSIX default | `~/.local/share/trio/aurora`, `loom` or `drift` |
| `--data-dir ROOT` | `ROOT/aurora`, `ROOT/loom`, `ROOT/drift` |

User presets are UTF-8 JSON files directly in the instrument directory (there is no extra `presets/` level); a preset's filename must match its `id`. F8 → S saves under a new name; R/D rename/delete a selected user preset. Packaged factory sounds cannot be renamed or deleted through the UI. Presets store instrument parameters plus instrument extras and shared `sequencer`/`modulation` settings. DRIFT factory presets omit live field X/Y and use registry defaults; an explicitly saved user preset includes the current X/Y values. The shell records parameter-level undo/redo, not an undo stack for all preset, gesture and shared-extra operations.

User skins are TOML files in `skins/`; they can replace a matching factory ID except for reserved immutable `mono`. See the [skin format](rag/05-SKINS-CONTRACT.md). The MIDI CC map is `midi-map.json` using schema `trio-midi-map/1`; a corrupt map warns and loads empty. Back up the whole instrument directory before changing custom assets. The preset ID `midi-map` is reserved to protect controller data. If an older version saved a sound with that ID, it remains visible with a warning: rename it through F8/R before saving MIDI mappings. Until it is renamed, learning remains usable in memory but refuses to overwrite the legacy preset.

There is no generic `config.ini`, automatic current-preset save or automatic restoration of the last session. Use CLI options for startup selection and explicitly save presets. Skin changes live in the current session. `--mono`, `--ascii` or `NO_COLOR` forces mono; a snapshot without `--skin` defaults to mono.

## Troubleshooting and rollback

| Symptom | Next step |
|---|---|
| Python is missing, too old, or opens the Windows Store | Install a real supported 64-bit Python and set `TRIO_PYTHON` to its executable. |
| First setup fails | Read the pip/build error, fix package access or wheelhouse contents, then run the same command again. No successful setup is recorded for the failed attempt. |
| Setup is already running | Let the other installer finish; do not launch competing setup processes into the same environment. |
| Environment was moved or its interpreter changed | Use a fresh `TRIO_VENV` path or remove only the disposable `.trio-venv`, then relaunch. Python venvs are not portable installations. |
| Application has no sound | Check status, remove `--no-audio`, install `--extras audio`, inspect `--list-devices`, and choose the intended output. |
| MIDI list is empty or unavailable | Install `--extras midi`, connect the controller, check the OS detects it, then inspect F7/`--list-midi`. |
| Notes do not stop on ordinary computer-key release | Terminal input uses a timed gate (450 ms without repeat), not physical key-up events. Check apostrophe latch; F9 is panic. |
| Computer letter keys change controls instead of notes | A focused sequencer/matrix consumes its command letters. Escape clears focus or returns to the prior area. |
| Mouse or modified function keys fail | Test in Windows Terminal/another SGR terminal; confirm terminal shortcuts are not intercepting the keys. Use Ctrl+P for palette actions and keyboard twins. |
| Layout is clipped | Enlarge to 100×30 or use 80×24 compact mode. Below that, the app intentionally asks for a larger window. |
| Glyphs/colours look wrong | Try `--mono` or `--ascii`, check terminal font, and test each skin. |
| A malformed custom preset blocks listing/startup | Move that user JSON aside, relaunch with a fresh `--data-dir`, then repair it against the schema/validation error. |
| Skin remains mono when selecting a colourway | Remove the `NO_COLOR` environment variable and omit `--mono`/`--ascii`; unknown/malformed skins also fall back to mono. |

To roll back, quit all instruments, keep a backup of user data, and reopen the previous source revision/artifact with its own fresh environment. Removing the candidate directory and its `.trio-venv` removes the disposable installation; do not delete `%APPDATA%\trio` or its POSIX counterpart unless you intend to remove saved work. No global package installation, Git tag or published release is required by this procedure.
