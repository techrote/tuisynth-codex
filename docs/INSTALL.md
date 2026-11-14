# Install, launch and recover TRIO

## Requirements and supported qualification

Use a 64-bit Python installation, version 3.11 or newer, with `venv` and `pip`. **Python 3.11 is recommended for Windows owner evaluation with online audio/MIDI installation.** The qualification matrix is Ubuntu/Windows on Python 3.11/3.14; the Python 3.14 MIDI lane prepares a native dependency wheel before offline installation. Other Python/platform combinations are not claimed by that matrix. Use Windows Terminal or a terminal with Unicode, colour and SGR mouse support; 100×30 cells is the full layout, 80×24 the compact layout. Below 80×24 the app asks you to enlarge it. No standalone Python executable is bundled.

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

For online Windows hardware-support installation, first select 64-bit Python 3.11. These commands prepare the environment, list available ports and open AURORA:

```powershell
$selected = & py -3.11 -I -c "import struct, sys; assert struct.calcsize('P') == 8; print(sys.executable)"
if ($LASTEXITCODE -ne 0 -or -not $selected) { throw 'Install 64-bit Python 3.11 with the Python Launcher.' }
$env:TRIO_PYTHON = $selected.Trim()
.\launch.cmd --extras audio,midi --setup-only aurora
.\launch.cmd aurora --list-devices
.\launch.cmd aurora --list-midi
.\launch.cmd aurora --preset glacier-choir
```

Omitting `--extras` later preserves the existing selection. To remove optional backends, use a new `TRIO_VENV`; the launcher does not silently uninstall them. Paths and forwarded arguments may contain spaces:

```powershell
$env:TRIO_PYTHON = 'C:\Program Files\Python311\python.exe' # Use your actual 64-bit Python path.
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

Prepare dependencies on an internet-connected machine using the **same interpreter, OS and architecture** as the target. Run the release helper from the repository/candidate root; it downloads the pinned core/build dependencies and explicitly requested extras. For Windows with the interpreter selected above:

```powershell
& $env:TRIO_PYTHON tools/release.py --prepare-wheelhouse wheelhouse --extras audio,midi
if ($LASTEXITCODE -ne 0) { throw 'Wheelhouse preparation failed; read the native prerequisite diagnostic.' }
.\launch.cmd --wheelhouse .\wheelhouse --extras audio,midi aurora
if ($LASTEXITCODE -ne 0) { throw 'TRIO setup or launch failed.' }
```

On POSIX, use the intended Python executable for the same helper invocation, then `sh ./launch.sh --wheelhouse ./wheelhouse --extras audio,midi aurora`. Omit `--extras` for a core-only wheelhouse, or select just `audio`/`midi`. The helper handles the native MIDI build where upstream wheels are absent; a blanket `pip download --only-binary` command cannot prepare Python 3.14 MIDI dependencies.

The completed wheelhouse is the offline installer input; later build/install qualification uses no package index. Native dependency wheels are platform/interpreter specific: a Windows/Python 3.11 wheelhouse is not a Linux/Python 3.14 cache. A release candidate includes the four TRIO wheels, but not a universal third-party dependency bundle. See [release reproduction](RELEASE.md) for source/build/dependency provenance.

## Python 3.14 MIDI wheelhouse

The final Python 3.14 CI jobs provide separate `trio-wheelhouse-<OS>-py3.14-<SHA>`
artifacts. For owner evaluation, download the Windows artifact from the same
qualified run as the candidate, extract it, and set `TRIO_WHEELHOUSE` to that
directory's absolute path. This uses the compiled backend already exercised by
CI and requires no local C++ compiler. Keep its `WHEELHOUSE.json`, native build
provenance and compiler log together with the wheels. The local build instructions
below are for preparing a new wheelhouse yourself.

[python-rtmidi 1.5.8's upstream files](https://pypi.org/project/python-rtmidi/1.5.8/#files) provide CPython binary wheels through 3.12. For Python 3.13+ with `midi` selected, a first launcher setup without a wheelhouse stops with instructions; it does not claim that a plain online source install is compatible. Core and audio-only online setup remain available. Once a matching wheelhouse installation completes successfully, ordinary repeat launches reuse it without repeating the wheelhouse option.

The release helper builds the native MIDI wheel during **dependency acquisition**, using a checksum-verified upstream source distribution, pinned Cython regeneration from the unchanged `.pyx`, and a pinned Meson toolchain. It preserves the upstream `.pyx`/MIDI source and the chosen interpreter; only the generated C++ is refreshed for current Python compatibility. Build versions are pinned in `requirements-midi-build.txt`. The source build uses ALSA on Linux with JACK disabled, and WinMM on Windows; the upstream prebuilt Linux wheel can expose a different backend set. Install the host build prerequisites before running the helper:

| Host | Native prerequisites for controlled MIDI-wheel preparation |
|---|---|
| Ubuntu | `build-essential`, `pkg-config`, `libasound2-dev`, and development headers for the selected Python. Use the headers matching the actual interpreter. |
| Windows | Installed MSVC C++ build tools and a Windows SDK. The helper selects the Visual Studio build environment through Meson `--vsenv`; Developer PowerShell is also suitable. |

For Ubuntu, install the listed packages through your system package manager before acquisition. On Windows, install the C++/SDK components in Visual Studio Build Tools before acquisition; they are unnecessary for the Python 3.11 prebuilt-wheel evaluation path. Upstream explains the [native compiler, Python-header and MIDI-library requirements](https://spotlightkid.github.io/python-rtmidi/installation.html).

To deliberately evaluate Python 3.14 on Windows, set `TRIO_PYTHON` to its actual 64-bit executable, run that executable's `tools/release.py --prepare-wheelhouse wheelhouse --extras audio,midi`, then set `TRIO_WHEELHOUSE` to the completed wheelhouse's absolute path before running the [owner evaluation block](ACCEPTANCE.md). Retain `RTMIDI-PROVENANCE.json` and, for a source build, `RTMIDI-BUILD.log` alongside the dependency wheels. They identify the source hash, generated C++ transformation, build versions/settings, output wheel hash and device-free API check; the release embeds the provenance in `SOURCE.json`. A missing compiler, header or wheel is a setup failure to repair, not an inferred hardware pass.

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
| Python 3.13+ MIDI setup requests a wheelhouse | Prepare it using that same Python and the native prerequisites above; alternatively select 64-bit Python 3.11 for upstream prebuilt wheels. Do not change interpreters silently. |
| MIDI list is empty or unavailable | Ensure optional MIDI setup completed, connect the controller, check the OS detects it, then inspect F7/`--list-midi`. |
| Notes do not stop on ordinary computer-key release | Terminal input uses a timed gate (450 ms without repeat), not physical key-up events. Check apostrophe latch; F9 is panic. |
| Computer letter keys change controls instead of notes | A focused sequencer/matrix consumes its command letters. Escape clears focus or returns to the prior area. |
| Mouse or modified function keys fail | Test in Windows Terminal/another SGR terminal; confirm terminal shortcuts are not intercepting the keys. Use Ctrl+P for palette actions and keyboard twins. |
| Layout is clipped | Enlarge to 100×30 or use 80×24 compact mode. Below that, the app intentionally asks for a larger window. |
| Glyphs/colours look wrong | Try `--mono` or `--ascii`, check terminal font, and test each skin. |
| A malformed custom preset blocks listing/startup | Move that user JSON aside, relaunch with a fresh `--data-dir`, then repair it against the schema/validation error. |
| Skin remains mono when selecting a colourway | Remove the `NO_COLOR` environment variable and omit `--mono`/`--ascii`; unknown/malformed skins also fall back to mono. |

To roll back, quit all instruments, keep a backup of user data, and reopen the previous source revision/artifact with its own fresh environment. Removing the candidate directory and its `.trio-venv` removes the disposable installation; do not delete `%APPDATA%\trio` or its POSIX counterpart unless you intend to remove saved work. No global package installation, Git tag or published release is required by this procedure.
