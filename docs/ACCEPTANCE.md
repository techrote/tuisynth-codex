# Manual physical acceptance

**CI cannot mark these passed.** All physical checks below remain **not run** until an operator performs them on the stated candidate and records the result. A software-qualified build can be ready for this evaluation while these cells remain unperformed.

| Instrument | real audio/listening | Windows Terminal mouse/keys | USB MIDI notes/sustain/bend/mod/learn | 10-min stability/CPU | notes/date/operator |
|---|---|---|---|---|---|
| AURORA | not run | not run | not run | not run | |
| LOOM | not run | not run | not run | not run | |
| DRIFT | not run | not run | not run | not run | |

## Candidate identity and test environment

Record the exact commit from the handoff and `SOURCE.json`, artifact filename and SHA-256, Windows build, Windows Terminal version, Python version, CPU, audio output/driver and sample rate, MIDI device/port and display font/size. Give dates/operator names and observations for each instrument; do not copy results from another revision without explaining the unchanged scope.

Obtain the candidate ZIP and manifest from the exact CI run linked in the PR. Verify it using [the release procedure](RELEASE.md), then extract it to a writable evaluation folder. Keep any owner data in a separate folder and begin at a low listening volume. Python is required; it is not bundled.

## Single-paste Windows 11 evaluation

Install **64-bit Python 3.11 with the Python Launcher**, open **Windows Terminal with PowerShell**, change into the extracted candidate root containing `launch.cmd`, and paste this block. By default it selects `py -3.11` for the upstream prebuilt MIDI wheel. An explicitly set `TRIO_PYTHON` is respected; Python 3.13+ additionally requires `TRIO_WHEELHOUSE` pointing to a complete wheelhouse prepared using that same interpreter and the [native prerequisites](INSTALL.md#python-314-midi-wheelhouse).

The block installs explicit audio/MIDI dependencies, performs device-free selftests/renders, prints available devices/ports and opens the three instruments in sequence. Each interactive run continues until Ctrl+Q; every native command checks its exit code. Setup requires internet access unless a complete matching wheelhouse has been supplied. It does not silently fall back from a requested Python 3.14 interpreter to another version. For Python 3.14, the matching Windows wheelhouse artifact from the qualified CI run can be extracted and used directly; local native build tools are only needed when preparing a new wheelhouse.

```powershell
$ErrorActionPreference = 'Stop'
if (-not (Test-Path .\launch.cmd)) { throw 'Change into the extracted TRIO candidate folder first.' }
$launch = (Resolve-Path .\launch.cmd).Path
if (-not $env:TRIO_PYTHON) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Install 64-bit Python 3.11 with the Python Launcher, or set TRIO_PYTHON explicitly.' }
    $selected = & py -3.11 -I -c "import struct, sys; assert struct.calcsize('P') == 8; print(sys.executable)"
    if ($LASTEXITCODE -ne 0 -or -not $selected) { throw '64-bit Python 3.11 was not found.' }
    $env:TRIO_PYTHON = $selected.Trim()
}
& $env:TRIO_PYTHON -I -c "import os, struct, sys; assert struct.calcsize('P') == 8 and sys.version_info >= (3,11), '64-bit Python 3.11+ required'; assert sys.version_info < (3,13) or os.environ.get('TRIO_WHEELHOUSE'), 'Python 3.13+ MIDI needs a matching prepared TRIO_WHEELHOUSE'"
if ($LASTEXITCODE -ne 0) { throw 'Python/MIDI setup prerequisites are incomplete.' }
$env:TRIO_VENV = Join-Path $PWD '.trio-venv'
$evaluation = Join-Path $PWD ('owner-evaluation-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $evaluation | Out-Null
function Invoke-Trio {
    & $launch @args
    if ($LASTEXITCODE -ne 0) { throw "TRIO exited with code $LASTEXITCODE`: $args" }
}
Invoke-Trio --extras 'audio,midi' --setup-only aurora
$presets = @{ aurora = 'glacier-choir'; loom = 'rosewood-harp'; drift = 'squall-choir' }
foreach ($synth in 'aurora','loom','drift') {
    Invoke-Trio $synth --selftest --data-dir $evaluation
    Invoke-Trio $synth --preset $presets[$synth] --render (Join-Path $evaluation "$synth.wav") --notes 'C4,E4,G4' --seconds 4 --data-dir $evaluation
}
Invoke-Trio aurora --list-devices
Invoke-Trio aurora --list-midi
foreach ($synth in 'aurora','loom','drift') {
    Read-Host "Enter to open $synth. Test it, then Ctrl+Q to continue" | Out-Null
    Invoke-Trio $synth --preset $presets[$synth] --data-dir $evaluation
}
Write-Host "Evaluation files and saved user data: $evaluation"
```

If startup chooses the wrong device/port, use `--device`/`--midi` on a subsequent launcher invocation or F7 for MIDI selection. `--no-audio` is useful for isolating terminal interactions but cannot pass the audio column. A printed “unavailable” message is diagnostic, not a hardware pass. To repeat after a failure, keep the failed evidence and rerun the applicable command; do not record a skipped check as passed.

## Audio and listening checks

For **each** instrument, test the selected real output at 48 kHz and, if the device supports it, 44.1 kHz. Audition the eight factory presets at modest output volume. Play single notes and chords across the practical pitch range, sustain/release, change presets and controls during sounding notes, and confirm stereo output and expected tails. Listen to the exported WAV as well as live output; finite offline samples do not establish acceptable live latency, clicks or sound quality.

For AURORA, hold a chord while painting the harmonic profile and confirm table regeneration completes without a stuck note or long frozen UI. For LOOM, compare plucks and sustained mouse bows, body and sympathetic response, DIRECT/CHORD mode and opposite-direction strums. For DRIFT, move the field through its extremes, compare vowels/density and mouse versus keyboard gust release. Press F9 with held/latched notes and confirm the sound stops safely; play again, then Ctrl+Q and confirm cleanup.

Record output name/driver, sample rate, audible results, glitches and any device fallback. If an instrument silently uses the null backend, its audio test remains not run or failed, according to what was actually attempted.

## USB MIDI checks

Connect a real controller and select its actual port. For each instrument:

1. Play notes, including repeated same-pitch notes and overlapping chords; verify corresponding note-offs and velocity response. In LOOM CHORD mode, confirm held pitches tune the surface and strumming sounds them.
2. Test sustain CC64, release the pedal, move pitch bend in both directions and back to center, and move mod wheel CC1 with a preset/route that makes the change audible.
3. Focus a parameter, press Ctrl+L, move a hardware CC and confirm it controls that parameter. Quit/reopen with the same evaluation data root and confirm the map persists. Repeat learn, press Escape before sending a CC, and confirm the canceled learn does not create a new assignment.
4. With a note held, unplug/replug the controller. Confirm MIDI-owned notes release and the service reconnects to the same named port when available. Change ports using F7 and repeat note playback. Test a chosen channel with `--midi-channel 1` and confirm other channels are filtered; default 0 is omni.
5. Send controller panic/all-notes-off if available and press F9. Confirm no stuck notes survive, then play normally again.

Record controller model, port name, channel and each result. An absent controller leaves this column **not run**; fake-backend CI is not a substitute.

## Windows Terminal interactions

At **100×30** and **80×24**, verify readable layout, focus and resize behavior for all factory skins and mono. Resize below 80×24, observe the enlarge-terminal message, restore size and continue. Try ASCII fallback if glyphs render incorrectly.

Check the on-screen piano's white/black cells, top versus bottom click velocity, drag glissando, right-click latch, wheel octave and release outside the piano. Compare the computer-keyboard timed gate and apostrophe latch. Tab/Shift+Tab should move focus; focused controls respond to arrows, default reset and documented coarse changes. Confirm Ctrl+Q from an overlay as well as the main view.

Exercise each main gesture: AURORA paint/erase through several bars and outside bounds; LOOM pluck/strum/bow and outside release; DRIFT steer/gust/recenter and outside release. Test F5/F8 preset operations, saved user-preset round-trip, F6 skin changes, Ctrl+P palette, F7 MIDI picker and modal Escape. Factory presets should resist rename/delete. Confirm keyboard and mouse selection agree and long overlays can be scrolled.

Open Shift+F3, toggle several steps, drag velocity, change probability, start/stop with Space and test arpeggio choices with a held chord. Open Shift+F4, create/clear a route, adjust its amount, use V to switch rack focus, select every pedal, bypass/change mix/reorder and save/reload a user preset. Escape should restore the preceding instrument area. If Windows Terminal captures modified F-keys, note that explicitly and test the available command-palette action rather than claiming the shortcut passed.

## Ten-minute stability and CPU record

Run each instrument for **at least ten continuous minutes** on the real audio backend. Include sustained notes/chords, several presets, normal controls/gestures, sequencer plus arp, modulation and enabled effects. Include ordinary window resizing and at least one panic/recovery. Keep workloads bounded by the instrument's normal controls; this is a practical listening/performance session, not a claim that every worst-case preset has arbitrary hardware headroom.

Record start/end time, elapsed duration, sample rate, CPU observations (idle and playing, how measured), glitches/dropouts, unresponsive periods, memory growth if observed, exceptions and successful shutdown. A failure should include exact preset/controls, steps, whether audio fell back, and the candidate SHA. Only an actually completed and acceptable session may change the stability/CPU cell to passed.

## Result record

Use a separate dated entry for each session:

```text
Candidate commit:
Artifact / SHA-256:
Date / operator:
Windows / Terminal / Python:
CPU / audio device and driver / sample rate:
MIDI device / port / channel:
Instrument / presets / data directory:
Audio/listening: not run | pass | fail — observations
Terminal interaction: not run | pass | fail — observations
USB MIDI: not run | pass | fail — observations
10-minute session: not run | pass | fail — times, duration, CPU and glitches
Reproduction steps / evidence / follow-up:
```

The owner decides whether physical findings require repairs before release approval. Software CI, review or a successful offline selftest never edits this record to a fabricated pass.
