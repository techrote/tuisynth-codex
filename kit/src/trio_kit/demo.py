"""Deterministic sine instrument used to exercise the shared application stack."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Mapping

import numpy as np

from trio_kit.params import ParamRegistry, ParamSnapshot, ParamSpec
from trio_kit.shell import InstrumentSpec, Shell
from trio_kit.tui import Canvas, Rect
from trio_kit.tui.widgets import Fader


class SineVoice:
    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self.phase = 0.0
        self.frequency = 440.0
        self.level = 0.0
        self.release_ms = 350.0
        self.release_level = 0.0
        self.release_position = 0
        self.finished = True

    def start(self, pitch: float, velocity: float, params: ParamSnapshot) -> None:
        self.frequency = 440.0 * 2.0 ** ((float(pitch) - 69.0) / 12.0)
        self.level = float(velocity) * float(params["amp.level"]) * 0.32
        self.release_ms = float(params["env.release"])
        self.release_position = 0
        self.release_level = self.level
        self.finished = False

    def release(self) -> None:
        if self.finished or self.release_position:
            return
        self.release_level = self.level
        self.release_position = 1

    def retarget(self, pitch: float) -> None:
        self.frequency = 440.0 * 2.0 ** ((float(pitch) - 69.0) / 12.0)

    def render(self, frames: int, params: ParamSnapshot) -> np.ndarray:
        if self.finished:
            return np.zeros((frames, 2), dtype=np.float32)
        angles = self.phase + (2.0 * math.pi * self.frequency / self.sample_rate) * np.arange(frames)
        mono = np.sin(angles)
        self.phase = float((angles[-1] + 2.0 * math.pi * self.frequency / self.sample_rate) % (2.0 * math.pi)) if frames else self.phase
        if self.release_position:
            total = max(1, round(self.sample_rate * self.release_ms / 1_000.0))
            positions = self.release_position - 1 + np.arange(frames)
            envelope = np.maximum(0.0, 1.0 - positions / total)
            mono *= self.release_level * envelope
            self.release_position += frames
            if self.release_position > total:
                self.finished = True
        else:
            mono *= self.level
            self.release_level = self.level
        return np.column_stack((mono, mono)).astype(np.float32)


class SineInstrument:
    """Small finite mono oscillator with stereo output and legato retargeting."""

    def __init__(self) -> None:
        self.registry = demo_registry()
        self.sample_rate = 48_000
        self._extras: dict[str, object] = {}
        self._closed = False

    def prepare(self, sample_rate: int, block: int) -> None:
        self.sample_rate = sample_rate

    def create_voice(self, rng: np.random.Generator) -> SineVoice:
        del rng
        return SineVoice(self.sample_rate)

    def process_bus(self, buffer: np.ndarray, params: ParamSnapshot) -> np.ndarray:
        del params
        return buffer

    def telemetry(self) -> Mapping[str, object]:
        return {"instrument": "sine-demo"}

    def on_event(self, name: str, payload: tuple[float | int | str, ...]) -> None:
        del name, payload

    def get_extras(self) -> dict[str, object]:
        return dict(self._extras)

    def set_extras(self, extras: Mapping[str, object]) -> None:
        self._extras = dict(extras)

    def close(self) -> None:
        self._closed = True


def demo_registry() -> ParamRegistry:
    return ParamRegistry(
        (
            ParamSpec("amp.level", "Level", "%", 0.0, 1.0, 0.65, group="Voice"),
            ParamSpec("env.release", "Release", "ms", 20.0, 3_000.0, 350.0, curve="log", group="Envelope"),
        )
    )


def _draw(canvas: Canvas, shell: Shell) -> None:
    canvas.text(3, 3, "Shared TRIO kit demonstration", "accent", max_width=canvas.width - 6)
    canvas.text(3, 5, "A sine voice exercises notes, presets, telemetry and offline render.", "text", max_width=canvas.width - 6)
    canvas.text(3, 7, "No instrument package imports another instrument package.", "muted", max_width=canvas.width - 6)


def _widgets(shell: Shell, width: int, height: int):
    del width, height
    level = shell.registry["amp.level"]
    release = shell.registry["env.release"]
    return (
        Fader("demo-level", Rect(3, 10, 22, 3), level, shell._known_params["amp.level"], on_change=shell.set_param),
        Fader("demo-release", Rect(28, 10, 26, 3), release, shell._known_params["env.release"], on_change=shell.set_param),
    )


def demo_spec() -> InstrumentSpec:
    return InstrumentSpec(
        "demo",
        "TRIO DEMO",
        SineInstrument,
        registry=demo_registry(),
        draw=_draw,
        widgets=_widgets,
        factory_package="trio_kit",
        factory_presets_dir=Path(__file__).resolve().parent / "data" / "presets" / "demo",
        legato_glide=True,
    )


def main(argv: list[str] | None = None) -> int:
    from trio_kit.cli import run_cli

    return run_cli(demo_spec(), argv=argv, command="trio-demo", version="0.1.0")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["SineInstrument", "SineVoice", "demo_registry", "demo_spec", "main"]
