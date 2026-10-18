# TRIO-012 prepass — LOOM app and strum surface

## Reconciliation

- Issue #12 is open, has no owner comments, and has no competing open PR.
- TRIO-008 and TRIO-011 are merged to `main`; TRIO-011's post-merge CI run `39095989436` passed on Ubuntu/Windows with Python 3.11/3.14.
- The branch `trio-012-loom-app` starts at main revision `0c30541bb57ca3969c3293056cf335df67c5bb09`.
- Required read-first contracts are ATTEMPT.md, the implementation programme, RAG 12/13, the issue scope, RAG 07, RAG 00, RAG 04 and RAG 05. The issue tests and acceptance remain authoritative.

## Design findings

- `LoomInstrument.telemetry()` already supplies eight main-string pitches/levels and twelve sympathetic pitches/levels. TRIO-012 will add bounded phase and active-bow string indices so the view can animate from engine state without reading voice internals.
- `InstrumentEvent` already carries ordered `pluck`, `bow`, `mute` and `strum` events. UI drag interpolation belongs in an engine-independent widget; it will use the shared mouse router's captured SGR path and the existing `StrumModel.crossing_velocity` rule.
- Sustained bow capture needs explicit `bow_on`/`bow_off` events. Existing `bow` keeps its continuous-crossing behavior; UI tap gestures pair `bow_on` with `bow_off`, while captured gestures hold crossed strings until release. Chord-mode piano routing applies consistently to on-screen, computer-keyboard and MIDI events at the shared `Shell._push` boundary. The router tracks direct-mode note IDs so it can forward releases after a mode change without creating stuck voices.
- The shared shell currently has no event-routing/help hook. Add optional callbacks to `InstrumentSpec`, defaulting to current behavior for all existing instruments. `route_event` may translate one event into an ordered tuple; `help_rows` appends contextual instrument controls.
- The LOOM view will keep one underlying surface and use F2-F5 to focus strings, controls, sympathetic resonators and the shared library overlay. At 80x24 it will use a compact one-surface arrangement, keeping the shared short piano visible.
- RAG 05 defines built-in `mono` as an immutable kit fallback. LOOM therefore packages the three requested color skins (`rosewood`, `brass`, `indigo-loom`) and relies on the shared `mono` skin as the fourth option. All LOOM color skins must define the string glyph ramp, semantic string roles, and LOOM-specific art.
- Animation refresh is capped at 24 Hz, follows the engine's per-string phase/level telemetry, and is disabled during snapshots. No instrument imports another instrument.
- The LOOM CLI will use `trio_kit.cli.run_cli` so selftest, offline WAV rendering, snapshots and hardware-free flows share the qualified shell.

## Acceptance plan

- Exercise actual SGR mouse drag events across multiple string rows; verify exact event order, faster crossing velocity, bow start/release, and right-click mute.
- Verify chord-mode piano replaces the held tuning snapshot without direct NoteOn/NoteOff; direct mode retains both tuning and normal notes. Cover shared piano and non-onscreen producers.
- Verify telemetry-driven string/sympathetic animation and snapshot freeze, both layouts, focus keys, all color skins without warnings, and golden frames for 100x30/80x24.
- Run LOOM selftest/render/snapshot flows and all package/device-free plus clean-wheel checks. CI and a fresh highest-effort self-review will be recorded before merge.
- No physical audio/MIDI devices are required or exercised.

## Provenance

Codex desktop (GPT-6, configuration unknown), GitHub CLI, Git, PowerShell, Python/NumPy/SciPy and repository-provided test/packaging tools. An independent review tier is unavailable in this run; perform and record a fresh highest-effort self-review.

## Qualification and review

- Focused shared-shell/LOOM run: `pytest -q kit/tests/test_shell.py kit/tests/test_foundation.py loom/tests` — 64 passed.
- Full device-free and clean-wheel qualification: `python tools/check.py --package all --packaging` — 422 passed (kit 339, AURORA 38, LOOM 44, DRIFT 1); all four wheels built, installed into an isolated environment and passed import, resource and CLI checks.
- Installed entry point: `loom --selftest` passed with 8 presets, 4 skins and 16 offline render-seconds. `loom --render ... --seconds 0.25 --notes C4,E4,G4 --seed 17` wrote 12,000 stereo frames at 48 kHz.
- Fresh highest-effort self-review traced ordered SGR crossings, bow capture release across mode changes, note-ID release ownership after play-mode changes, panic clearing, telemetry ownership, compact geometry, fallback color roles, CLI packaging and RAG alignment. It found and fixed a mid-capture excitation-mode switch that could leave an unpaired bow, and moved bow-marker publication to an immutable audio-thread snapshot. Malformed sustained-bow events without a valid string index are ignored. No remaining blocking findings.
- `git diff --check` passed. No physical audio/MIDI devices or terminal hardware acceptance were exercised; those remain documented as separate physical acceptance.
