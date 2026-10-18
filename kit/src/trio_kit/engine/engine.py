"""Block engine with sample-offset events and arbitrary-size output requests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import math
import time
from types import MappingProxyType
from typing import Any

import numpy as np

from trio_kit.constants import BLOCK, DEFAULT_SAMPLE_RATE, OUTPUT_CEILING, SUPPORTED_SAMPLE_RATES
from trio_kit.events import (
    ControlChange,
    Event,
    EventQueue,
    InstrumentEvent,
    ModWheel,
    NoteOff,
    NoteOn,
    Panic,
    ParamSet,
    PresetApply,
    PitchBend,
    RetargetNote,
    Sustain,
    Transport,
)
from trio_kit.engine.master import MasterBus
from trio_kit.engine.voices import VoiceManager
from trio_kit.params import ParamError, ParamRegistry, ParamSnapshot, ParamState


@dataclass(frozen=True, slots=True)
class EngineTelemetry:
    sample_rate: int
    block: int
    active_voices: int
    max_voices: int
    event_queue_depth: int
    dropped_events: int
    overflow_count: int
    overflow_panics: int
    nonfinite_resets: int
    limited_blocks: int
    limiter_gain: float
    render_load: float
    callback_seconds: float
    callback_errors: int
    backend: str
    last_error: str | None
    instrument: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        data: dict[str, object] = {}
        try:
            for index, (key, value) in enumerate(self.instrument.items()):
                if index >= 64 or len(data) >= 16:
                    break
                if not isinstance(key, str):
                    continue
                if isinstance(value, (str, bool, int)) or value is None:
                    data[key[:64]] = value[:128] if isinstance(value, str) else value
                elif isinstance(value, float) and math.isfinite(value):
                    data[key[:64]] = value
                elif isinstance(value, (tuple, list)) and len(value) <= 64:
                    # Bounded numeric vectors support compact instrument visualizers
                    # without allowing arbitrary mutable or unbounded telemetry.
                    if not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value):
                        continue
                    try:
                        vector = tuple(float(item) for item in value)
                    except (OverflowError, ValueError):
                        continue
                    if all(math.isfinite(item) for item in vector):
                        data[key[:64]] = vector
        except Exception:
            data.clear()
        object.__setattr__(self, "instrument", MappingProxyType(data))


class Engine:
    """Shared real-time core; all queued changes are applied at internal blocks."""

    def __init__(
        self,
        instrument: Any,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        block: int = BLOCK,
        max_voices: int = 16,
        seed: int = 0,
        *,
        registry: ParamRegistry | None = None,
        initial_params: Mapping[str, object] | None = None,
        event_queue: EventQueue | None = None,
        master: MasterBus | None = None,
    ) -> None:
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate not in SUPPORTED_SAMPLE_RATES:
            raise ValueError(f"sample_rate must be one of {SUPPORTED_SAMPLE_RATES}")
        if isinstance(block, bool) or not isinstance(block, int) or block != BLOCK:
            raise ValueError(f"block must equal the fixed {BLOCK}-frame block size")
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        self.instrument = instrument
        candidate_registry = registry if registry is not None else getattr(instrument, "registry", None)
        if candidate_registry is None:
            candidate_registry = ParamRegistry()
        if not isinstance(candidate_registry, ParamRegistry):
            raise TypeError("registry must be a ParamRegistry")
        self.registry = candidate_registry
        self._param_state = ParamState(self.registry, initial_params)
        self.event_queue = event_queue if event_queue is not None else EventQueue()
        if not isinstance(self.event_queue, EventQueue):
            raise TypeError("event_queue must be an EventQueue")
        self.sample_rate = sample_rate
        self.block = block
        self.max_voices = max_voices
        self.seed = seed
        self.voice_manager = VoiceManager(
            instrument,
            max_voices,
            sample_rate,
            seed,
            max_tails=max_voices + self.event_queue.maxsize * 2,
        )
        self.master = master if master is not None else MasterBus(sample_rate, ceiling=OUTPUT_CEILING)
        if not isinstance(self.master, MasterBus):
            raise TypeError("master must be a MasterBus")
        if self.master.sample_rate != sample_rate:
            raise ValueError("master sample rate must match the engine sample rate")
        if self.master.ceiling > OUTPUT_CEILING:
            raise ValueError(f"master ceiling must not exceed {OUTPUT_CEILING}")
        self._pending = np.zeros((0, 2), dtype=np.float32)
        self._pending_cursor = 0
        self._render_load = 0.0
        self._callback_seconds = 0.0
        self._callback_errors = 0
        self._backend_name = "offline"
        self._last_error: str | None = None
        self._closed = False
        prepare = getattr(instrument, "prepare", None)
        if callable(prepare):
            prepare(sample_rate, block)

    @property
    def param_snapshot(self) -> ParamSnapshot:
        return self._param_state.snapshot

    def push(self, event: Event) -> bool:
        if self._closed:
            return False
        return self.event_queue.push(event)

    def render(self, frames: int) -> np.ndarray:
        if isinstance(frames, bool) or not isinstance(frames, int) or frames <= 0:
            raise ValueError("frames must be a positive integer")
        if self._closed:
            raise RuntimeError("engine is closed")
        output = np.empty((frames, 2), dtype=np.float32)
        written = 0
        while written < frames:
            if self._pending_cursor >= len(self._pending):
                self._pending = self._render_block()
                self._pending_cursor = 0
            count = min(frames - written, len(self._pending) - self._pending_cursor)
            output[written : written + count] = self._pending[self._pending_cursor : self._pending_cursor + count]
            written += count
            self._pending_cursor += count
        return output

    def _render_block(self) -> np.ndarray:
        started = time.perf_counter()
        events = self.event_queue.drain()
        changes: dict[str, object] = {}
        preset_extras: Mapping[str, object] | None = None
        dispatch: list[Event] = []
        for event in events:
            if isinstance(event, ParamSet):
                try:
                    changes[event.key] = self.registry.validate_value(event.key, event.value)
                except ParamError as error:
                    self._last_error = str(error)[:256]
            elif isinstance(event, PresetApply):
                try:
                    changes = self.registry.validate(event.params)
                    preset_extras = event.extras
                except ParamError as error:
                    self._last_error = str(error)[:256]
            else:
                dispatch.append(event)
        if preset_extras is not None:
            try:
                self.set_extras(_thaw_preset_value(preset_extras))
            except Exception as error:
                self._last_error = f"preset extras: {error}"[:256]
        try:
            snapshot = self._param_state.apply(changes) if changes else self._param_state.snapshot
        except ParamError as error:
            # A valid update in the same block should still take effect even if
            # a custom mapping or registry reports an unrelated invalid item.
            self._last_error = str(error)[:256]
            snapshot = self._param_state.snapshot

        on_block_boundary = getattr(self.instrument, "on_block_boundary", None)
        if callable(on_block_boundary):
            try:
                on_block_boundary(snapshot)
            except Exception as error:
                self._last_error = f"instrument block-boundary callback failed: {error}"[:256]

        result = np.zeros((self.block, 2), dtype=np.float32)
        cursor = 0
        for event in sorted(dispatch, key=lambda item: getattr(item, "frame", 0)):
            frame = int(getattr(event, "frame", 0))
            if frame > cursor:
                result[cursor:frame] = self._render_segment(frame - cursor, snapshot)
                cursor = frame
            self._dispatch(event, snapshot)
        if cursor < self.block:
            result[cursor:] = self._render_segment(self.block - cursor, snapshot)
        resets_before = self.master.nonfinite_resets
        result = self.master.process(result)
        if self.master.nonfinite_resets != resets_before:
            self.voice_manager.reset()
            reset = getattr(self.instrument, "reset", None)
            if callable(reset):
                try:
                    reset()
                except Exception as error:
                    self._last_error = f"instrument reset failed: {error}"[:256]
        elapsed = time.perf_counter() - started
        relative = elapsed / (self.block / self.sample_rate)
        self._render_load = relative if self._render_load == 0.0 else 0.9 * self._render_load + 0.1 * relative
        return result

    def _render_segment(self, frames: int, params: ParamSnapshot) -> np.ndarray:
        mix = self.voice_manager.render(frames, params)
        process_bus = getattr(self.instrument, "process_bus", None)
        if callable(process_bus):
            result = process_bus(mix, params)
            if result is not None:
                mix = np.asarray(result, dtype=np.float32)
        if mix.shape != (frames, 2):
            raise ValueError(f"instrument bus must preserve shape ({frames}, 2)")
        return mix

    def _dispatch(self, event: Event, params: ParamSnapshot) -> None:
        if isinstance(event, NoteOn):
            self.voice_manager.note_on(event, params)
            return
        if isinstance(event, NoteOff):
            self.voice_manager.note_off(event)
            return
        if isinstance(event, RetargetNote):
            self.voice_manager.retarget(event.note_id, event.pitch)
            return
        if isinstance(event, Sustain):
            self.voice_manager.set_sustain(event.on)
            return
        if isinstance(event, Panic):
            self.voice_manager.panic()
            return
        if isinstance(event, InstrumentEvent):
            self._instrument_event(event.name, event.payload)
            return
        if isinstance(event, PitchBend):
            self._instrument_event("pitch_bend", (event.semitones,))
            return
        if isinstance(event, ModWheel):
            self._instrument_event("mod_wheel", (event.value,))
            return
        if isinstance(event, ControlChange):
            self._instrument_event("control_change", (event.cc, event.value))
            return
        if isinstance(event, Transport):
            self._instrument_event("transport", (event.tempo, event.swing, event.playing))

    def _instrument_event(self, name: str, payload: tuple[float | int | str, ...]) -> None:
        callback = getattr(self.instrument, "on_event", None)
        if callable(callback):
            callback(name, payload)

    def get_extras(self) -> dict[str, object]:
        getter = getattr(self.instrument, "get_extras", None)
        return getter() if callable(getter) else {}

    def set_extras(self, extras: Mapping[str, object]) -> None:
        setter = getattr(self.instrument, "set_extras", None)
        if not callable(setter):
            if extras:
                raise ValueError("instrument does not support preset extras")
            return
        setter(extras)

    def record_callback_error(self, error: BaseException) -> None:
        self._callback_errors += 1
        self._last_error = f"audio callback: {error}"[:256]

    def record_callback_time(self, seconds: float) -> None:
        if math.isfinite(seconds) and seconds >= 0:
            self._callback_seconds = seconds

    def set_backend_name(self, name: str) -> None:
        self._backend_name = str(name)[:64]

    def telemetry(self) -> EngineTelemetry:
        instrument_telemetry: Mapping[str, object] = {}
        getter = getattr(self.instrument, "telemetry", None)
        if callable(getter):
            try:
                candidate = getter()
                if isinstance(candidate, Mapping):
                    instrument_telemetry = candidate
            except Exception as error:
                self._last_error = f"instrument telemetry: {error}"[:256]
        return EngineTelemetry(
            sample_rate=self.sample_rate,
            block=self.block,
            active_voices=self.voice_manager.active_count,
            max_voices=self.max_voices,
            event_queue_depth=len(self.event_queue),
            dropped_events=self.event_queue.dropped_events,
            overflow_count=self.event_queue.overflow_count,
            overflow_panics=self.event_queue.panic_fallbacks,
            nonfinite_resets=self.master.nonfinite_resets,
            limited_blocks=self.master.limited_blocks,
            limiter_gain=self.master.last_limiter_gain,
            render_load=self._render_load,
            callback_seconds=self._callback_seconds,
            callback_errors=self._callback_errors,
            backend=self._backend_name,
            last_error=self._last_error,
            instrument=instrument_telemetry,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.voice_manager.reset()
        self.event_queue.drain()
        self.master.reset()
        close = getattr(self.instrument, "close", None)
        if callable(close):
            close()


class OfflineEngine(Engine):
    """Engine alias used for deterministic rendering without a device backend."""


def _thaw_preset_value(value: object) -> object:
    """Convert an immutable queued preset payload back to fresh JSON containers."""
    if isinstance(value, Mapping):
        return {key: _thaw_preset_value(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw_preset_value(child) for child in value]
    return value


__all__ = ["Engine", "EngineTelemetry", "OfflineEngine"]
