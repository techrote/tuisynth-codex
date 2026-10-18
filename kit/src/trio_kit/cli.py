"""Shared CLI flows for instrument shells, offline renders and snapshots."""

from __future__ import annotations

import argparse
import math
import re
import sys
import wave
from pathlib import Path
from typing import Sequence

import numpy as np

from trio_kit.constants import DEFAULT_SAMPLE_RATE, OUTPUT_CEILING
from trio_kit.engine import OfflineEngine
from trio_kit.engine.master import MasterBus
from trio_kit.events import NoteIds, NoteOff, NoteOn, PresetApply
from trio_kit.preset import Preset, PresetError, PresetLibrary
from trio_kit.shell import InstrumentSpec, Shell
from trio_kit.skins import SkinLibrary


_NOTE_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")
_PITCH_CLASSES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def parse_note_name(value: str) -> int:
    if not isinstance(value, str):
        raise ValueError("note names must be strings such as C4 or F#3")
    match = _NOTE_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"invalid note name {value!r}; expected names such as C4, F#3 or Bb2")
    letter, accidental, octave_text = match.groups()
    pitch_class = _PITCH_CLASSES[letter.upper()] + (1 if accidental == "#" else -1 if accidental == "b" else 0)
    pitch = (int(octave_text) + 1) * 12 + pitch_class
    if not 0 <= pitch <= 127:
        raise ValueError(f"note {value!r} is outside MIDI range 0..127")
    return pitch


def _preset_library(spec: InstrumentSpec, data_dir: str | None) -> PresetLibrary:
    if spec.registry is None:
        instrument = spec.instrument_factory()
        registry = getattr(instrument, "registry", None)
        if registry is None:
            raise ValueError("instrument must expose a ParamRegistry or InstrumentSpec.registry")
    else:
        registry = spec.registry
    return PresetLibrary(
        spec.identifier,
        registry,
        data_dir=data_dir,
        factory_package=spec.factory_package,
        factory_dir=spec.factory_presets_dir,
        extras_validator=spec.extras_validator,
    )


def _make_parser(command: str, version: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=command, description=f"{command} shared TRIO synthesizer shell")
    parser.add_argument("--version", action="version", version=f"{command} {version}")
    parser.add_argument("--skin")
    parser.add_argument("--preset")
    parser.add_argument("--midi", help="MIDI input port index or name substring")
    parser.add_argument("--midi-channel", type=int, default=0, choices=range(17), metavar="0..16")
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--device", help="audio output device index or name")
    parser.add_argument("--sample-rate", type=int, choices=(44_100, 48_000), default=DEFAULT_SAMPLE_RATE)
    parser.add_argument("--ascii", action="store_true", help="use a monochrome ASCII-safe view")
    parser.add_argument("--mono", action="store_true", help="force the built-in monochrome skin")
    parser.add_argument("--data-dir", type=str)
    parser.add_argument("--list-skins", action="store_true")
    parser.add_argument("--list-presets", action="store_true")
    parser.add_argument("--list-midi", action="store_true")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--render", metavar="OUT.wav")
    parser.add_argument("--notes", default="C4,E4,G4")
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--snapshot", metavar="COLSxROWS")
    return parser


def _snapshot_screens(spec: InstrumentSpec) -> tuple[str, ...]:
    return ("main", "help", "palette", "skins", "midi", "presets", *spec.screen_names)


def _add_screen_argument(parser: argparse.ArgumentParser, spec: InstrumentSpec) -> None:
    parser.add_argument("--screen", default="main", choices=_snapshot_screens(spec))


def _print_snapshot(snapshot: str) -> None:
    """Write a cell-aligned frame even when a Windows console lacks Unicode."""
    encoding = getattr(sys.stdout, "encoding", None)
    if encoding:
        snapshot = snapshot.encode(encoding, errors="replace").decode(encoding)
    print(snapshot)


def _device_value(value: str | None) -> int | str | None:
    if value is None:
        return None
    return int(value) if value.isdecimal() else value


def _parse_snapshot_size(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{1,4})[xX](\d{1,4})", value)
    if match is None:
        raise ValueError("snapshot dimensions must be written COLSxROWS")
    width, height = map(int, match.groups())
    if not 1 <= width <= 500 or not 1 <= height <= 200:
        raise ValueError("snapshot dimensions must be within 1x1 and 500x200")
    return width, height


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    if samples.ndim != 2 or samples.shape[1] != 2 or not np.isfinite(samples).all():
        raise ValueError("offline engine produced invalid stereo samples")
    peak = float(np.max(np.abs(samples), initial=0.0))
    if peak > OUTPUT_CEILING + 1e-6:
        raise ValueError(f"offline render exceeded the output ceiling ({peak:.6f})")
    quantized = np.rint(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2", copy=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(quantized.tobytes())


def _prepare_offline_instrument(engine: OfflineEngine) -> None:
    """Wait for optional asynchronous instrument state before offline notes render."""
    instrument = engine.instrument
    wait = getattr(instrument, "wait_for_regeneration", None)
    if not callable(wait):
        return
    wait()
    # Promote worker output at the engine's next real block boundary, then drain
    # the remainder so the caller's first musical event begins on a fresh block.
    engine.render(1)
    engine.render(engine.block - 1)
    wait(active=True)


def _render(
    spec: InstrumentSpec,
    path: Path,
    notes: tuple[int, ...],
    seconds: float,
    sample_rate: int,
    seed: int,
    preset: Preset | None,
) -> int:
    if not math.isfinite(seconds) or not 0.01 <= seconds <= 120.0:
        raise ValueError("--seconds must be finite and within 0.01..120")
    engine = OfflineEngine(
        spec.instrument_factory(),
        sample_rate=sample_rate,
        seed=seed,
        max_voices=spec.max_voices,
        registry=spec.registry,
    )
    try:
        if preset is not None:
            engine.push(PresetApply(engine.registry.validate(preset.params), preset.extras))
            # Preset extras apply when the engine drains its queue at the first
            # block boundary. Give that request time to regenerate before notes.
            if callable(getattr(engine.instrument, "wait_for_regeneration", None)):
                engine.render(1)
                engine.render(engine.block - 1)
        _prepare_offline_instrument(engine)
        allocator = NoteIds(1)
        for pitch in notes:
            engine.push(NoteOn(allocator.next(), pitch, 0.7, "offline-render"))
        total = round(seconds * sample_rate)
        gate = max(1, round(total * 0.78))
        held = engine.render(gate)
        # Note IDs are stable and sequential for this offline-only render.
        for note_id in range(1, len(notes) + 1):
            engine.push(NoteOff(note_id))
        tail = engine.render(total - gate) if total > gate else np.zeros((0, 2), dtype=np.float32)
        audio = np.concatenate((held, tail), axis=0)
        _write_wav(path, audio, sample_rate)
        return len(audio)
    finally:
        engine.close()


def _selftest(spec: InstrumentSpec, data_dir: str | None, sample_rate: int, seed: int) -> tuple[int, str]:
    presets = _preset_library(spec, data_dir).list_factory_presets()
    if not presets:
        raise RuntimeError("selftest found no factory or user presets")
    skins = SkinLibrary.for_instrument(spec.identifier, data_dir=data_dir, factory_dir=spec.factory_skins_dir, include_user=False)
    if not skins.ids:
        raise RuntimeError("selftest found no usable skin")
    limiter = MasterBus(sample_rate)
    stress = limiter.process(np.full((256, 2), 2.0, dtype=np.float32))
    if float(np.max(np.abs(stress), initial=0.0)) > OUTPUT_CEILING + 1e-6 or limiter.limited_blocks == 0:
        raise RuntimeError("selftest master limiter did not hold its output ceiling")
    renders = 0
    for preset_index, preset in enumerate(presets):
        engine = OfflineEngine(
            spec.instrument_factory(),
            sample_rate=sample_rate,
            seed=seed,
            max_voices=spec.max_voices,
            registry=spec.registry,
        )
        try:
            engine.push(PresetApply(engine.registry.validate(preset.params), preset.extras))
            if callable(getattr(engine.instrument, "wait_for_regeneration", None)):
                engine.render(1)
                engine.render(engine.block - 1)
            _prepare_offline_instrument(engine)
            for note_id, pitch in enumerate((60, 64, 67), start=1):
                engine.push(NoteOn(note_id, pitch, 0.7, "selftest"))
            rendered = engine.render(2 * sample_rate)
            if rendered.shape != (2 * sample_rate, 2) or not np.isfinite(rendered).all():
                raise RuntimeError(f"preset {preset.id!r} produced invalid audio")
            peak = float(np.max(np.abs(rendered), initial=0.0))
            if peak > OUTPUT_CEILING + 1e-6 or peak < 1e-8:
                raise RuntimeError(f"preset {preset.id!r} produced silent or unbounded audio (peak {peak:g})")
            if engine.telemetry().nonfinite_resets:
                raise RuntimeError(f"preset {preset.id!r} triggered a non-finite audio reset")
            renders += 1
        finally:
            engine.close()
    for skin_id in skins.ids:
        shell = Shell(
            spec,
            no_audio=True,
            data_dir=data_dir,
            skin_id=skin_id,
            mono=skin_id == "mono",
            start_midi=False,
            sample_rate=sample_rate,
            seed=seed,
        )
        try:
            frame = shell.snapshot(100, 30)
            if len(frame.splitlines()) != 30 or not any(char.strip() for char in frame):
                raise RuntimeError(f"skin {skin_id!r} failed the headless render")
        finally:
            shell.shutdown()
    return renders, f"selftest passed: {len(presets)} presets, {len(skins.ids)} skins, {renders * 2} offline render-seconds"


def run_cli(
    spec: InstrumentSpec,
    *,
    argv: Sequence[str] | None = None,
    command: str | None = None,
    version: str = "0.1.0",
) -> int:
    """Run the common CLI for an instrument spec; never opens devices for offline commands."""
    program = command or spec.identifier
    parser = _make_parser(program, version)
    _add_screen_argument(parser, spec)
    arguments = parser.parse_args(argv)
    try:
        if arguments.list_skins:
            library = SkinLibrary.for_instrument(spec.identifier, data_dir=arguments.data_dir, factory_dir=spec.factory_skins_dir, mono=arguments.mono or arguments.ascii)
            print("\n".join(library.ids))
            return 0
        if arguments.list_presets:
            for preset in _preset_library(spec, arguments.data_dir).list_presets():
                print(f"{preset.id}\t{preset.name}")
            return 0
        if arguments.list_midi:
            from trio_kit.input.midi_backend import RtMidiBackend

            try:
                ports = RtMidiBackend().list_ports()
            except Exception as error:
                print(f"MIDI unavailable: {error}")
                return 0
            print("\n".join(f"{index}\t{name}" for index, name in enumerate(ports)))
            return 0
        if arguments.list_devices:
            try:
                devices = __import__("sounddevice").query_devices()
            except Exception as error:
                print(f"Audio devices unavailable: {error}")
                return 0
            print("\n".join(f"{index}\t{device['name']}" for index, device in enumerate(devices)))
            return 0
        if arguments.selftest:
            _, message = _selftest(spec, arguments.data_dir, arguments.sample_rate, arguments.seed)
            print(message)
            return 0
        if arguments.render:
            notes = tuple(parse_note_name(part) for part in arguments.notes.split(",") if part.strip())
            if not notes:
                raise ValueError("--notes must contain at least one comma-separated note")
            if isinstance(arguments.seed, bool) or arguments.seed < 0:
                raise ValueError("--seed must be a non-negative integer")
            library = _preset_library(spec, arguments.data_dir)
            preset = library.get(arguments.preset) if arguments.preset else None
            frames = _render(
                spec,
                Path(arguments.render),
                notes,
                arguments.seconds,
                arguments.sample_rate,
                arguments.seed,
                preset,
            )
            print(f"Wrote {arguments.render} ({frames} stereo frames at {arguments.sample_rate} Hz)")
            return 0
        if arguments.snapshot:
            width, height = _parse_snapshot_size(arguments.snapshot)
            snapshot_mono = arguments.mono or arguments.ascii or arguments.skin is None
            shell = Shell(
                spec,
                no_audio=True,
                skin_id=arguments.skin,
                mono=snapshot_mono,
                data_dir=arguments.data_dir,
                start_midi=False,
                sample_rate=arguments.sample_rate,
                seed=arguments.seed,
            )
            try:
                if arguments.preset:
                    shell.load_preset(arguments.preset)
                _print_snapshot(shell.snapshot(width, height, screen=arguments.screen))
            finally:
                shell.shutdown()
            return 0
        shell = Shell(
            spec,
            no_audio=arguments.no_audio,
            device=_device_value(arguments.device),
            sample_rate=arguments.sample_rate,
            seed=arguments.seed,
            skin_id=arguments.skin,
            mono=arguments.mono or arguments.ascii,
            data_dir=arguments.data_dir,
            midi_selection=_device_value(arguments.midi),
            midi_channel=arguments.midi_channel,
        )
        if arguments.preset:
            shell.load_preset(arguments.preset)
        shell.run()
        return 0
    except (OSError, ValueError, RuntimeError, PresetError) as error:
        print(f"{program}: {error}", file=sys.stderr)
        return 1


__all__ = ["parse_note_name", "run_cli"]
