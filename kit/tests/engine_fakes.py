from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from trio_kit.params import ParamSnapshot


class FakeVoice:
    def __init__(self, instrument: FakeInstrument, rng: np.random.Generator, index: int) -> None:
        self.instrument = instrument
        self.rng = rng
        self.index = index
        self.finished = False
        self.release_calls = 0
        self.pitch = 0.0
        self.phase = 0.0
        self.amplitude = 0.0

    def start(self, pitch: float, velocity: float, params: ParamSnapshot) -> None:
        self.pitch = pitch
        scale = float(params.get("amp.gain", 1.0))
        random_scale = float(self.rng.random()) if self.instrument.random_level else 1.0
        self.amplitude = self.instrument.levels[self.index % len(self.instrument.levels)] * velocity * scale * random_scale

    def release(self) -> None:
        self.release_calls += 1

    def render(self, frames: int, params: ParamSnapshot) -> np.ndarray:
        self.instrument.render_params.append((params.version, params.get("amp.gain", 1.0)))
        if self.index in self.instrument.bad_voice_indices:
            return np.full((frames, 2), np.nan, dtype=np.float32)
        step = 0.071 + self.pitch / 20_000.0
        phase = self.phase + step * np.arange(frames, dtype=np.float64)
        signal = (np.sin(phase) * self.amplitude).astype(np.float32)
        self.phase += step * frames
        return np.column_stack((signal, signal)).astype(np.float32, copy=False)

    def retarget(self, pitch: float) -> None:
        self.pitch = pitch


class FakeInstrument:
    def __init__(
        self,
        *,
        levels: tuple[float, ...] = (0.5,),
        random_level: bool = False,
        bad_voice_indices: set[int] | None = None,
    ) -> None:
        self.levels = levels
        self.random_level = random_level
        self.bad_voice_indices = bad_voice_indices or set()
        self.created: list[FakeVoice] = []
        self.events: list[tuple[str, tuple[object, ...], int]] = []
        self.bus_frames = 0
        self.gain = 1.0
        self.reset_calls = 0
        self.close_calls = 0
        self.sample_rate = 0
        self.block = 0
        self.extras: dict[str, object] = {}
        self.render_params: list[tuple[int, object]] = []

    def create_voice(self, rng: np.random.Generator) -> FakeVoice:
        voice = FakeVoice(self, rng, len(self.created))
        self.created.append(voice)
        return voice

    def prepare(self, sample_rate: int, block: int) -> None:
        self.sample_rate = sample_rate
        self.block = block

    def process_bus(self, buffer: np.ndarray, params: ParamSnapshot) -> np.ndarray:
        self.bus_frames += len(buffer)
        return buffer * self.gain

    def on_event(self, name: str, payload: tuple[float | int | str, ...]) -> None:
        self.events.append((name, payload, self.bus_frames))
        if name == "gain" and payload:
            self.gain = float(payload[0])

    def telemetry(self) -> Mapping[str, object]:
        return {"created": len(self.created), "bus_frames": self.bus_frames}

    def reset(self) -> None:
        self.reset_calls += 1
        self.gain = 1.0

    def get_extras(self) -> dict[str, object]:
        return dict(self.extras)

    def set_extras(self, extras: Mapping[str, object]) -> None:
        self.extras = dict(extras)

    def close(self) -> None:
        self.close_calls += 1
