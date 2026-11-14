"""Generate user-reference blocks from runtime bindings, CLI metadata and assets.

Run with --check in CI; run with --write only after reviewing a deliberate change.
No audio/MIDI device or user data is opened. Human descriptions are paired with
exact dispatch keys and checked against the relevant handler's source branches;
behavioral regressions in test_documentation.py exercise the public interaction.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import inspect
from pathlib import Path
import re
import tempfile
import textwrap
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
INSTRUMENTS = ("aurora", "loom", "drift")


@dataclass(frozen=True)
class Binding:
    keys: tuple[str, ...]
    label: str
    action: str


def row(keys: str, label: str, action: str) -> Binding:
    return Binding(tuple(keys.split()), label, action)


SHARED = (
    row("f1", "F1", "Open help; arrows/PageUp/PageDown/Home/End or wheel scroll; Escape closes it."),
    row("f2 f3 f4 f5", "F2–F5", "Open the instrument areas listed in its guide."),
    row("s-f3 shift-f3", "Shift+F3", "Open/focus the step sequencer."),
    row("s-f4 shift-f4", "Shift+F4", "Open/focus modulation and the effects rack."),
    row("f6 s-f6 shift-f6", "F6 / Shift+F6", "Cycle skins forward / backward."),
    row("f7", "F7", "Open MIDI input picker; arrows/wheel select, Enter or click connects."),
    row("f8", "F8", "Open preset actions; arrows/wheel select, Enter or click loads, S saves as, R renames and D deletes a user preset."),
    row("f9", "F9", "Panic: release sounding notes and clear held/latch state."),
    row("c-p", "Ctrl+P", "Open command palette; type a filter, arrows/wheel select, Enter or click runs."),
    row("c-l", "Ctrl+L", "Arm MIDI CC learn for the focused parameter (or first parameter when no parameter is focused); Escape cancels."),
    row("c-z c-y", "Ctrl+Z / Ctrl+Y", "Undo / redo individual parameter edits recorded by the shell; this is not full-session undo."),
    row("escape", "Escape", "Close an overlay, return from sequencer/MOD, or clear control focus."),
    row("space", "Space", "Start/stop the sequencer transport; in MOD, toggle the selected effect bypass. Overlays consume Space as their own input."),
)
PIANO = (
    row("left right", "Left / Right", "Move the focused on-screen piano cursor."),
    row("up down", "Up / Down", "Change on-screen piano octave."),
    row("enter", "Enter", "Play the cursor note with a timed gate."),
)
PARAMETERS = (
    row("left down right up", "Left/Down / Right/Up", "Decrease / increase by one control step."),
    row("pagedown pageup", "PageDown / PageUp", "Decrease / increase by ten control steps."),
    row("home end", "Home / End", "Set minimum / maximum."),
    row("delete", "Delete", "Restore the default."),
)
SEQUENCER = (
    row("left right", "Left / Right", "Select previous / next step."),
    row("up down", "Up / Down", "Select previous / next lane when multiple lanes exist."),
    row("enter", "Enter", "Toggle the selected step."),
    row("pageup pagedown", "PageUp / PageDown", "Raise / lower selected-step velocity by 0.05."),
    row("space", "Space", "Start / stop transport."),
    row("[ - ] =", "[ or - / ] or =", "Lower / raise tempo by 1 BPM (40–240)."),
    row(", .", ", / .", "Lower / raise swing by 0.02 (0–0.6)."),
    row("a", "A", "Toggle arpeggiator."),
    row("m", "M", "Cycle up, down, updown, random, as-played arpeggio order."),
    row("o", "O", "Cycle arpeggio octave count 1–4."),
    row("r", "R", "Cycle arpeggio rate."),
    row("l", "L", "Toggle arpeggio latch."),
)
MODULATION = (
    row("v", "V", "Switch matrix / rack focus."),
    row("left right", "Left / Right", "Select matrix slot, or effect unit with rack focus."),
    row("up down r enter", "Up / Down / R or Enter", "Previous / next source (R and Enter advance)."),
    row("t", "T", "Cycle valid destinations for the selected source."),
    row("+ = - _", "+ or = / - or _", "Raise / lower route amount by 0.05 (−1…1)."),
    row("pageup pagedown", "PageUp / PageDown", "Raise / lower route amount by 0.1."),
    row("delete backspace", "Delete / Backspace", "Clear selected route."),
    row("b space", "B / Space", "Toggle selected effect bypass."),
    row("[ ]", "[ / ]", "Move selected effect earlier / later in the rack."),
    row(", < . >", ", or < / . or >", "Lower / raise selected effect mix by 0.05 (0…1)."),
)
INSTRUMENT_KEYS = {
    "aurora": (
        row("left right", "Left / Right", "Select a harmonic bar."),
        row("up down", "Up / Down", "Raise / lower the selected amplitude by 0.05."),
        row("pageup pagedown", "PageUp / PageDown", "Raise / lower amplitude by 0.25."),
        row("delete", "Delete", "Erase the selected harmonic."),
        row("c-e", "Ctrl+E", "Erase even-numbered harmonics (2, 4, …)."),
        row("c-o", "Ctrl+O", "Erase odd-numbered harmonics (1, 3, …)."),
        row("c-r", "Ctrl+R", "Generate the next deterministic smooth random harmonic profile."),
    ),
    "loom": (
        row("up right down left", "Up/Right / Down/Left", "Select a higher / lower string index."),
        row("enter", "Enter", "Play the selected string; a keyboard bow trigger releases immediately."),
        row(", .", ", / .", "Strum in opposite directions across the current held chord."),
        row("/", "/", "Toggle DIRECT / CHORD piano mode; CHORD tunes the surface instead of playing direct notes."),
    ),
    "drift": (
        row("left right up down", "Arrow keys", "Move the field cursor 2% per press."),
        row("pageup pagedown", "PageUp / PageDown", "Move the cursor vertically by 10%."),
        row("enter", "Enter", "Toggle the keyboard gust; press again to release it."),
        row("delete", "Delete", "Recenter the field cursor."),
    ),
}
INSTRUMENT_MOUSE = {
    "aurora": (
        ("Left press/drag", "Paint harmonic amplitudes; skipped bars are interpolated."),
        ("Right press/drag", "Erase the traversed harmonics."),
        ("Wheel over a bar", "Adjust that harmonic by 0.05 per reported wheel step."),
    ),
    "loom": (
        ("Left press/drag across rows", "Pluck strings in crossing order; in bow excitation, sustain crossed strings until release."),
        ("Release, including outside the surface", "End the captured bow/strum gesture."),
        ("Right-click a string", "Mute that string."),
    ),
    "drift": (
        ("Left press/drag", "Steer field X/Y and hold a mouse gust until release."),
        ("Release, including outside the map", "Release the mouse gust; a separately latched keyboard gust remains active."),
        ("Right-click", "Recenter field X/Y."),
        ("Wheel", "Raise/lower grain density in its normalized parameter range."),
    ),
}
SNAPSHOTS = {
    "aurora": "aurora/tests/snapshots/aurora-play-borealis-100x30.txt",
    "loom": "loom/tests/snapshots/loom-rosewood-100x30.txt",
    "drift": "drift/tests/snapshots/map_squall_100x30.txt",
}


def specs() -> dict[str, object]:
    from trio_aurora.instrument import aurora_spec
    from trio_loom.ui import loom_spec
    from trio_drift.ui import drift_spec
    return {"aurora": aurora_spec(), "loom": loom_spec(), "drift": drift_spec()}


def compared_keys(handler: Callable) -> set[str]:
    """Read explicitly dispatched keys, not comments or unrelated string values."""
    parsed = ast.parse(textwrap.dedent(inspect.getsource(handler)))
    result: set[str] = set()
    for node in ast.walk(parsed):
        if not isinstance(node, ast.Compare):
            continue
        if not isinstance(node.left, ast.Name) or node.left.id not in {"key", "command", "typed"}:
            continue
        for operand in node.comparators:
            if isinstance(operand, ast.Constant) and isinstance(operand.value, str):
                result.add(operand.value)
            elif isinstance(operand, (ast.Set, ast.Tuple, ast.List)):
                result.update(value.value for value in operand.elts if isinstance(value, ast.Constant) and isinstance(value.value, str))
    return result


def binding_groups() -> tuple[tuple[str, Callable, tuple[Binding, ...], set[str]], ...]:
    from trio_kit.shell import Shell
    from trio_kit.tui.piano import PianoWidget
    from trio_kit.tui.widgets import ParamWidget
    from trio_kit.tui.sequencer import SequencerWidget
    from trio_kit.tui.modulation import ModulationWidget
    from trio_aurora.ui import HarmonicPainter
    from trio_loom.ui import StringSurface
    from trio_drift.ui import WeatherMap
    return (
        ("shared", Shell.handle_key, SHARED, {"any"}),
        # CanvasApp dispatches Space to the shell before these widgets.
        ("piano", PianoWidget.handle_key, PIANO, {"space"}),
        ("parameters", ParamWidget.handle_key, PARAMETERS, set()),
        ("sequencer", SequencerWidget.handle_key, SEQUENCER, {"any"}),
        # enter-unit is an internal action name, not a terminal key.
        ("modulation", ModulationWidget.handle_key, MODULATION, {"any", "enter-unit"}),
        ("aurora", HarmonicPainter.handle_key, INSTRUMENT_KEYS["aurora"], set()),
        ("loom", StringSurface.handle_key, INSTRUMENT_KEYS["loom"], {"any", "space"}),
        ("drift", WeatherMap.handle_key, INSTRUMENT_KEYS["drift"], set()),
    )


def validate_bindings() -> None:
    for name, handler, bindings, excluded in binding_groups():
        implemented = compared_keys(handler) - excluded
        documented = {key for binding in bindings for key in binding.keys}
        if implemented != documented:
            raise ValueError(f"{name} binding drift: undocumented={sorted(implemented - documented)}, nonexistent={sorted(documented - implemented)}")


def table(headers: tuple[str, ...], rows) -> str:
    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(cell(value) for value in values) + " |" for values in rows)
    return "\n".join(lines)


def binding_table(bindings: tuple[Binding, ...]) -> str:
    return table(("Key or keys", "Action"), ((f"`{binding.label}`", binding.action) for binding in bindings))


def controls_reference() -> str:
    from trio_kit.input.keyboard import _KEY_OFFSETS, _VELOCITIES, KeyboardPiano
    note_rows = []
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    for key, offset in _KEY_OFFSETS.items():
        pitch = 48 + offset
        note_rows.append((f"`{key}`", f"{names[pitch % 12]}{pitch // 12 - 1}", pitch))
    return "\n\n".join((
        "## Shared controls",
        "Controls apply when no overlay or focused instrument control consumes the key. Click a control or use Tab/Shift+Tab to focus it. Escape clears focus. Ctrl+Q quits from every view, including overlays. Space belongs to transport outside MOD, even when the piano or LOOM strings are focused.",
        binding_table(SHARED),
        "Shared F7/F8 and command-palette rows support click-to-activate and wheel selection. Skin-preview rows support hover-to-preview, click/Enter to keep and Escape to restore. Keyboard selection stays visible while long lists scroll. Tab remains inside a modal overlay; F9 panic and Ctrl+Q quit remain available.",
        "## Computer keyboard notes",
        f"Terminals do not send ordinary key-release events. A note closes after {KeyboardPiano().gate_ms} ms without repeat; repeat extends its gate. Apostrophe toggles latch, where pressing the note key again releases it. `-` / `=` shift the computer-keyboard octave (−3…+3); `[` / `]` select velocity from {', '.join(str(value) for value in _VELOCITIES)} (default {KeyboardPiano().velocity}). The table shows octave offset zero.",
        table(("Key", "Note", "MIDI number"), note_rows),
        "## On-screen piano",
        binding_table(PIANO),
        table(("Mouse gesture", "Action"), (("Left press", "Play with velocity set by click depth (0.35 at top, 1.0 at bottom)."), ("Drag across keys", "Glissando with the original velocity; release anywhere ends the captured note."), ("Right-click", "Toggle a per-key latch."), ("Wheel", "Shift the displayed piano octave."))),
        "## Standard parameter controls",
        binding_table(PARAMETERS),
        "Click/drag changes a value, wheel adjusts it, and right-click resets it. Control-specific panels may use the different navigation documented in the instrument guide. Shift+drag belongs to terminal text selection. Ctrl+wheel is coarse only when the terminal reports the modifier.",
        "## Sequencer and arpeggiator",
        "Open with Shift+F3; Escape restores the preceding instrument area. These keys apply while its grid is focused. Letter commands take priority over computer-note keys in this focus. Step note, gate, pattern length and extra lanes are preset data; the v0.1 grid edits step enable, velocity and probability, tempo/swing, and arpeggiator choices.",
        binding_table(SEQUENCER),
        table(("Mouse gesture", "Action"), (("Click a step", "Toggle it."), ("Drag a pressed step vertically", "Set its velocity."), ("Right-click a step", "Cycle probability through 0.25, 0.5, 0.75, 1.0."), ("Wheel over grid", "Adjust tempo by 1 BPM per event."))),
        "## Modulation and effects",
        "Open with Shift+F4; Escape returns. Eight slots route valid sources to parameters or effect controls. Voice sources only list destinations that support voice modulation. The rack contains tremolo/autopan, ring-mod, phaser, tape, chorus, delay and reverb; each has mix/bypass and can be reordered. LFO/ModEnv waveform, rate and envelope settings are stored in preset extras; the v0.1 matrix UI edits routing and amounts.",
        binding_table(MODULATION),
        table(("Mouse gesture", "Action"), (("Click matrix source/slot cell", "Choose source for that route."), ("Click destination detail row", "Cycle a valid destination."), ("Drag amount row or wheel over matrix", "Change bipolar route amount."), ("Right-click route", "Clear it."), ("Click pedal / right-click pedal", "Select the effect / toggle its bypass."), ("Drag pedal body", "Move it within rack order."), ("Drag pedal mix row or wheel over pedal", "Set wet mix."))),
    )) + "\n"


def instrument_reference(name: str, spec: object) -> str:
    from trio_kit.cli import _preset_library
    from trio_kit.skins import SkinLibrary
    with tempfile.TemporaryDirectory(prefix="trio-docs-") as temporary:
        presets = _preset_library(spec, temporary).list_factory_presets()
        skins = SkinLibrary.for_instrument(name, data_dir=temporary, factory_dir=spec.factory_skins_dir, include_user=False)
    snapshot = ROOT / SNAPSHOTS[name]
    sections = [
        "## Areas and controls",
        table(("Key", "Area"), ((f"`F{index}`", screen.upper()) for index, screen in enumerate(spec.screen_names, 2))),
        "The following keyboard controls act on the focused main gesture area. Shared piano, presets, skins, sequencing and MOD controls are in [the control reference](../docs/CONTROLS.md).",
        binding_table(INSTRUMENT_KEYS[name]),
        table(("Mouse gesture", "Action"), INSTRUMENT_MOUSE[name]),
        "## Factory presets",
        table(("Preset ID for --preset", "Name", "Description"), ((f"`{preset.id}`", preset.name, preset.description) for preset in presets)),
        "## Factory skins",
        table(("Skin ID for --skin", "Name"), ((f"`{skin_id}`", skins._skins[skin_id].name) for skin_id in skins.ids)),
        "## Frozen terminal view",
        f"This is the existing deterministic 100×30 text fixture [{snapshot.name}](tests/snapshots/{snapshot.name}); it is a software layout snapshot, not a photograph of a physical terminal. Colour/style is not represented in this text. Full and compact fixtures remain in [tests/snapshots](tests/snapshots).",
        "```text\n" + snapshot.read_text(encoding="utf-8").rstrip("\n") + "\n```",
    ]
    return "\n\n".join(sections) + "\n"


CLI_PURPOSES = {
    "help": "Show argument help and exit.", "version": "Print installed command/version and exit.",
    "skin": "Select a factory/user skin ID; unknown IDs fall back to mono with a warning.",
    "preset": "Load a factory/user preset by ID (not a JSON file path).",
    "midi": "Select MIDI input by zero-based port index or name substring.",
    "midi_channel": "Filter incoming MIDI: 0 means omni; 1–16 selects a channel.",
    "no_audio": "Use the device-free/null audio backend for interactive operation.",
    "device": "Select audio output by device index or name.",
    "sample_rate": "Engine/offline sample rate in Hz.",
    "ascii": "Force monochrome ASCII-safe drawing.", "mono": "Force the built-in mono skin.",
    "data_dir": "Use a shared user-data root; instrument name is appended.",
    "list_skins": "List installed factory/user skin IDs and exit.",
    "list_presets": "List factory/user preset IDs and names and exit.",
    "list_midi": "List MIDI ports (or a readable unavailable message) and exit.",
    "list_devices": "List audio devices (or a readable unavailable message) and exit.",
    "selftest": "Validate factory presets/skins and render offline audio; no devices opened.",
    "render": "Write a stereo 16-bit PCM WAV file without opening devices.",
    "notes": "Comma-separated render notes, for example C4,E4,G4 or F#3,Bb3.",
    "seconds": "Offline render duration, finite 0.01–120 seconds.",
    "seed": "Deterministic non-negative random seed.",
    "snapshot": "Print a deterministic terminal frame, for example 100x30 (maximum 500x200).",
    "screen": "Choose a snapshot screen; has no effect on normal interactive startup.",
}


def cli_reference(all_specs: dict[str, object]) -> str:
    from trio_kit.cli import _make_parser, _add_screen_argument
    parser = _make_parser("aurora", "0.1.0")
    _add_screen_argument(parser, all_specs["aurora"])
    actions = parser._actions
    if {action.dest for action in actions} != set(CLI_PURPOSES):
        raise ValueError("CLI options changed; reconcile the user-facing purpose table")
    rows = []
    for action in actions:
        default = action.default
        if default in (None, argparse.SUPPRESS) or action.dest in {"help", "version", "render", "snapshot"}:
            default = "—"
        choices = f" Choices: {', '.join(map(str, action.choices))}." if action.choices is not None and action.dest != "screen" else ""
        rows.append((", ".join(f"`{option}`" for option in action.option_strings), default, CLI_PURPOSES[action.dest] + choices))
    return "\n\n".join((
        "## Shared command options",
        "These options are read from the actual argparse parser. They apply to `aurora`, `loom` and `drift`, after the instrument name when using a launcher. Option/list/selftest/render/snapshot commands exit without entering the full-screen application. Device-listing commands may enumerate hardware; selftest/render/snapshot never do.",
        table(("Option", "Default", "Purpose"), rows),
        "## Snapshot screen names",
        table(("Command", "Accepted --screen values"), ((name, ", ".join(("main", "help", "palette", "skins", "midi", "presets", "sequencer", "modulation", *spec.screen_names))) for name, spec in all_specs.items())),
    )) + "\n"


def generated_blocks() -> dict[tuple[str, str], str]:
    validate_bindings()
    all_specs = specs()
    blocks = {
        ("docs/CONTROLS.md", "controls"): controls_reference(),
        ("docs/CLI.md", "cli"): cli_reference(all_specs),
    }
    for name, spec in all_specs.items():
        blocks[(f"{name}/README.md", "instrument")] = instrument_reference(name, spec)
    blocks[("README.md", "quick-controls")] = binding_table((SHARED[0], SHARED[2], SHARED[3], SHARED[7])) + "\n\n`Ctrl+Q` quits. Play computer notes with `z s x d c v g b h n j m` or click the on-screen piano. See [complete keyboard/mouse controls](docs/CONTROLS.md), including focus and timed-note behavior.\n"
    return blocks


def replace_block(text: str, name: str, content: str) -> str:
    start, end = f"<!-- generated:{name}:start -->", f"<!-- generated:{name}:end -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    if len(pattern.findall(text)) != 1:
        raise ValueError(f"expected one generated block {name!r}")
    return pattern.sub(lambda _match: f"{start}\n\n{content.rstrip()}\n\n{end}", text)


def check_or_write(*, write: bool = False, root: Path = ROOT) -> list[str]:
    stale = []
    for (filename, marker), content in generated_blocks().items():
        path = root / filename
        before = path.read_text(encoding="utf-8")
        after = replace_block(before, marker, content)
        if before != after:
            stale.append(filename)
            if write:
                path.write_text(after, encoding="utf-8", newline="\n")
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    stale = check_or_write(write=args.write)
    if stale:
        print(("Updated: " if args.write else "Stale generated documentation: ") + ", ".join(stale))
    else:
        print("Generated documentation matches runtime bindings, parser, assets and frozen snapshots.")
    return 1 if stale and not args.write else 0


if __name__ == "__main__":
    raise SystemExit(main())
