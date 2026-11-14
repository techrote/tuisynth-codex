# TRIO terminal synthesizers — 0.1.0 candidate

Three co-installable instruments share an audio engine and terminal toolkit, with different synthesis and performance gestures:

| Instrument | Sound engine | Main gesture | Guide |
|---|---|---|---|
| **AURORA** | Spectral PADsynth pads and choirs | Paint harmonic profiles above a full-width piano | [AURORA](aurora/README.md) |
| **LOOM** | Waveguide plucks, bows, bodies and sympathetic strings | Strum or bow a string surface | [LOOM](loom/README.md) |
| **DRIFT** | Granular breath/wind with morphing vowel filters | Steer a weather field and hold gusts | [DRIFT](drift/README.md) |
| **trio-kit** | Shared audio/input/TUI, sequencer, modulation and effects | Common piano, presets, skins and MIDI handling | [Controls](docs/CONTROLS.md) |

**Release status: candidate for owner review, Draft/HOLD.** TRIO-001–016 are merged; TRIO-017 completes the software release candidate. No tag or public release is authorized by this campaign. Automated qualification does not establish real audio, USB MIDI or physical Windows Terminal acceptance: the owner record is [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md).

## Start here

Install **64-bit Python 3.11 or newer**. Software qualification covers Python **3.11 and 3.14 on Ubuntu and Windows**. Use a mouse-capable terminal; Windows Terminal is the Windows evaluation target. A 100-column × 30-row window shows the full layout; 80×24 shows compact controls. Smaller windows ask you to enlarge the terminal.

From an extracted candidate bundle or repository checkout:

```powershell
# Windows / PowerShell: first run sets up a local environment, then opens AURORA.
.\launch.cmd aurora --no-audio
```

```sh
# POSIX: use sh when an archive extractor did not preserve the executable bit.
sh ./launch.sh aurora --no-audio
```

The launcher installs all four TRIO distributions once, then reuses its local `.trio-venv`. To enable actual audio and MIDI backends explicitly:

```powershell
.\launch.cmd --extras audio,midi aurora
# After quitting AURORA with Ctrl+Q:
.\launch.cmd loom
.\launch.cmd drift
```

On POSIX use `sh ./launch.sh` with the same arguments. First setup needs package access unless a complete `--wheelhouse` has been supplied. `--no-audio` disables audio device output; ordinary interactive startup may still probe optional MIDI ports. The selftest, offline render and snapshot commands never open devices.

Read [installation, launch and troubleshooting](docs/INSTALL.md) for Python selection, offline setup, repeat launch, data locations, optional dependencies and recovery. The [CLI reference](docs/CLI.md) lists the actual supported arguments.

## Essential controls

<!-- generated:quick-controls:start -->

| Key or keys | Action |
| --- | --- |
| `F1` | Open help; arrows/PageUp/PageDown/Home/End or wheel scroll; Escape closes it. |
| `Shift+F3` | Open/focus the step sequencer. |
| `Shift+F4` | Open/focus modulation and the effects rack. |
| `F9` | Panic: release sounding notes and clear held/latch state. |

`Ctrl+Q` quits. Play computer notes with `z s x d c v g b h n j m` or click the on-screen piano. See [complete keyboard/mouse controls](docs/CONTROLS.md), including focus and timed-note behavior.

<!-- generated:quick-controls:end -->

## Try the software without devices

```powershell
.\launch.cmd aurora --selftest
.\launch.cmd loom --selftest
.\launch.cmd drift --selftest
.\launch.cmd aurora --preset glacier-choir --render "aurora audition.wav" --notes C4,E4,G4 --seconds 4
.\launch.cmd loom --preset rosewood-harp --render "loom audition.wav" --seconds 4
.\launch.cmd drift --preset squall-choir --render "drift audition.wav" --seconds 4
.\launch.cmd drift --snapshot 100x30 --screen map --skin squall
```

Selftests exercise every factory preset and skin, finite/limited offline audio and deterministic terminal drawing. Rendered WAVs still need human listening. Each instrument contains eight factory presets and three colourways plus the shared ASCII-safe `mono` skin; its guide lists their actual IDs and includes an existing frozen text view.

## Release and evaluation

- [0.1.0 release notes](docs/RELEASE-NOTES-0.1.0.md) describe the delivered scope and limitations.
- [Changelog](CHANGELOG.md) preserves all 17 programme issue IDs.
- [Release/reproduction procedure](docs/RELEASE.md) explains source revision, artifacts, checksums and repeatability.
- [Engineering handoff](docs/RELEASE-QUALIFICATION.md) inventories every change, software gate and repaired review finding.
- [Owner acceptance](docs/ACCEPTANCE.md) contains a single-paste Windows evaluation sequence and the separate listening/MIDI/terminal/stability checklist.
- [Provenance ledger](docs/PROVENANCE.md) records implementation and review roles.

## Development and qualification

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pip install --no-deps --no-build-isolation --editable kit --editable aurora --editable loom --editable drift
.\.venv\Scripts\python tools/check.py --package all
.\.venv\Scripts\python tools/documentation.py --check
```

On POSIX substitute `.venv/bin/python`. `tools/check.py --package all --packaging` adds clean wheel/install qualification; see the release guide for an offline dependency wheelhouse and reproducible candidate build. Generated documentation is refreshed deliberately with `tools/documentation.py --write`; tests reject stale control tables, option metadata, factory inventories and embedded snapshot fixtures. Existing golden snapshots update only through the explicit `--update-snapshots` test option.

The product and engineering contracts are indexed in [docs/rag/INDEX.md](docs/rag/INDEX.md). The [programme](docs/programme/IMPLEMENTATION-PROGRAMME.md), [AGENTS.md](AGENTS.md) and [ATTEMPT.md](ATTEMPT.md) define independent attempt ownership and qualification. No licence is granted by this candidate; a licence requires an owner decision.
