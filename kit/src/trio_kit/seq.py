"""Validated step-sequencer and arpeggiator models plus a block scheduler."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
import math
import random
import threading
from typing import Literal

from trio_kit.constants import BLOCK
from trio_kit.events import Event, InstrumentEvent, NoteIds, NoteOff, NoteOn, Panic, RetargetNote, Transport


ArpMode = Literal["up", "down", "updown", "random", "as-played"]
ARP_RATES = ("1/4", "1/8", "1/8T", "1/16", "1/16T", "1/32")
_ARP_RATE_BEATS = {"1/4": 1.0, "1/8": 0.5, "1/8T": 1 / 3, "1/16": 0.25, "1/16T": 1 / 6, "1/32": 0.125}


def _number(value: object, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} must be in the range {minimum:g}..{maximum:g}")
    return number


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in the range {minimum}..{maximum}")
    return value


@dataclass(frozen=True, slots=True)
class Step:
    on: bool = False
    note: int | None = None
    velocity: float = 0.8
    gate: float = 0.8
    probability: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.on, bool):
            raise ValueError("step on must be a boolean")
        if self.note is not None:
            _integer(self.note, "step note", 0, 127)
        object.__setattr__(self, "velocity", _number(self.velocity, "step velocity", 0.0, 1.0))
        object.__setattr__(self, "gate", _number(self.gate, "step gate", 0.05, 1.0))
        object.__setattr__(self, "probability", _number(self.probability, "step probability", 0.0, 1.0))

    def to_dict(self) -> dict[str, object]:
        return {"on": self.on, "note": self.note, "velocity": self.velocity, "gate": self.gate, "probability": self.probability}

    @classmethod
    def from_dict(cls, value: object) -> Step:
        if not isinstance(value, Mapping):
            raise ValueError("each sequencer step must be an object")
        unknown = set(value) - {"on", "note", "velocity", "gate", "probability"}
        if unknown:
            raise ValueError(f"unknown sequencer step fields: {', '.join(sorted(map(str, unknown)))}")
        return cls(
            on=value.get("on", False),
            note=value.get("note"),
            velocity=value.get("velocity", 0.8),
            gate=value.get("gate", 0.8),
            probability=value.get("probability", 1.0),
        )


def _default_lanes(length: int) -> tuple[tuple[Step, ...], ...]:
    return (tuple(Step() for _ in range(length)),)


@dataclass(frozen=True, slots=True)
class Pattern:
    length: int = 16
    lanes: tuple[tuple[Step, ...], ...] = field(default_factory=lambda: _default_lanes(16))

    def __post_init__(self) -> None:
        length = _integer(self.length, "pattern length", 1, 32)
        if not isinstance(self.lanes, tuple) or not 1 <= len(self.lanes) <= 4:
            raise ValueError("pattern must contain 1..4 lanes")
        checked: list[tuple[Step, ...]] = []
        for lane in self.lanes:
            if not isinstance(lane, tuple) or len(lane) != length or not all(isinstance(step, Step) for step in lane):
                raise ValueError("each lane must contain exactly pattern length steps")
            checked.append(tuple(lane))
        object.__setattr__(self, "lanes", tuple(checked))

    def to_dict(self) -> dict[str, object]:
        return {"length": self.length, "lanes": [[step.to_dict() for step in lane] for lane in self.lanes]}

    @classmethod
    def from_dict(cls, value: object) -> Pattern:
        if not isinstance(value, Mapping):
            raise ValueError("sequencer pattern must be an object")
        unknown = set(value) - {"length", "lanes"}
        if unknown:
            raise ValueError(f"unknown sequencer pattern fields: {', '.join(sorted(map(str, unknown)))}")
        length = _integer(value.get("length", 16), "pattern length", 1, 32)
        if "lanes" not in value:
            return cls(length, _default_lanes(length))
        raw_lanes = value["lanes"]
        if not isinstance(raw_lanes, (list, tuple)) or not 1 <= len(raw_lanes) <= 4:
            raise ValueError("pattern must contain 1..4 lanes")
        lanes_list: list[tuple[Step, ...]] = []
        for raw_lane in raw_lanes:
            if not isinstance(raw_lane, (list, tuple)) or len(raw_lane) != length:
                raise ValueError("each lane must contain exactly pattern length steps")
            lanes_list.append(tuple(Step.from_dict(step) for step in raw_lane))
        lanes = tuple(lanes_list)
        return cls(length, lanes)

    def step(self, lane: int, index: int) -> Step:
        return self.lanes[lane][index % self.length]

    def with_step(self, lane: int, index: int, step: Step) -> Pattern:
        lane = _integer(lane, "lane", 0, len(self.lanes) - 1)
        index = _integer(index, "step index", 0, self.length - 1)
        if not isinstance(step, Step):
            raise TypeError("step must be a Step")
        lanes = [list(items) for items in self.lanes]
        lanes[lane][index] = step
        return Pattern(self.length, tuple(tuple(items) for items in lanes))


@dataclass(frozen=True, slots=True)
class ArpeggiatorConfig:
    enabled: bool = False
    mode: ArpMode = "up"
    octaves: int = 1
    rate: str = "1/8"
    latch: bool = False
    seed: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool) or not isinstance(self.latch, bool):
            raise ValueError("arpeggiator enabled and latch must be booleans")
        if not isinstance(self.mode, str) or self.mode not in {"up", "down", "updown", "random", "as-played"}:
            raise ValueError("unsupported arpeggiator mode")
        object.__setattr__(self, "octaves", _integer(self.octaves, "arpeggiator octaves", 1, 4))
        if not isinstance(self.rate, str) or self.rate not in ARP_RATES:
            raise ValueError(f"arpeggiator rate must be one of {', '.join(ARP_RATES)}")
        object.__setattr__(self, "seed", _integer(self.seed, "arpeggiator seed", 0, 2**31 - 1))

    def to_dict(self) -> dict[str, object]:
        return {"enabled": self.enabled, "mode": self.mode, "octaves": self.octaves, "rate": self.rate, "latch": self.latch, "seed": self.seed}

    @classmethod
    def from_dict(cls, value: object) -> ArpeggiatorConfig:
        if not isinstance(value, Mapping):
            raise ValueError("arpeggiator settings must be an object")
        unknown = set(value) - {"enabled", "mode", "octaves", "rate", "latch", "seed"}
        if unknown:
            raise ValueError(f"unknown arpeggiator fields: {', '.join(sorted(map(str, unknown)))}")
        return cls(**{key: value[key] for key in value})  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class SequenceConfig:
    pattern: Pattern = field(default_factory=Pattern)
    tempo: float = 120.0
    swing: float = 0.0
    playing: bool = False
    arpeggiator: ArpeggiatorConfig = field(default_factory=ArpeggiatorConfig)

    def __post_init__(self) -> None:
        if not isinstance(self.pattern, Pattern) or not isinstance(self.arpeggiator, ArpeggiatorConfig):
            raise ValueError("sequencer pattern and arpeggiator settings are invalid")
        object.__setattr__(self, "tempo", _number(self.tempo, "tempo", 40.0, 240.0))
        object.__setattr__(self, "swing", _number(self.swing, "swing", 0.0, 0.6))
        if not isinstance(self.playing, bool):
            raise ValueError("transport playing must be a boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "pattern": self.pattern.to_dict(),
            "tempo": self.tempo,
            "swing": self.swing,
            "playing": self.playing,
            "arpeggiator": self.arpeggiator.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> SequenceConfig:
        if not isinstance(value, Mapping):
            raise ValueError("sequencer settings must be an object")
        unknown = set(value) - {"pattern", "tempo", "swing", "playing", "arpeggiator"}
        if unknown:
            raise ValueError(f"unknown sequencer fields: {', '.join(sorted(map(str, unknown)))}")
        return cls(
            pattern=Pattern.from_dict(value.get("pattern", {})),
            tempo=value.get("tempo", 120.0),
            swing=value.get("swing", 0.0),
            playing=value.get("playing", False),
            arpeggiator=ArpeggiatorConfig.from_dict(value.get("arpeggiator", {})),
        )


def validate_extras(extras: object, instrument_validator=None, registry=None) -> dict[str, object]:
    """Validate shared sequencer/modulation state and instrument-private extras."""
    if not isinstance(extras, Mapping):
        raise ValueError("preset extras must be an object")
    raw = dict(extras)
    shared = SequenceConfig.from_dict(raw.pop("sequencer", {}))
    # Imported lazily to keep the modulation source module independent of the
    # sequencer scheduler while maintaining one public extras entry point.
    from trio_kit.modulation import validate_modulation

    modulation = validate_modulation(raw.pop("modulation", {}), registry=registry)
    private = instrument_validator(raw) if instrument_validator is not None else raw
    if not isinstance(private, Mapping):
        raise ValueError("instrument extras validator must return an object")
    return {**dict(private), "sequencer": shared.to_dict(), "modulation": modulation}


class Arpeggiator:
    """Deterministic pitch ordering, including an explicitly seeded random mode."""

    def __init__(self, config: ArpeggiatorConfig = ArpeggiatorConfig()) -> None:
        self.config = config
        self._random = random.Random(config.seed)

    def set_config(self, config: ArpeggiatorConfig) -> None:
        self.config = config
        self._random = random.Random(config.seed)

    def order(self, pitches: Sequence[float]) -> tuple[float, ...]:
        notes = [float(pitch) + 12 * octave for octave in range(self.config.octaves) for pitch in pitches if 0 <= float(pitch) + 12 * octave <= 127]
        if self.config.mode == "as-played":
            result = notes
        else:
            result = sorted(notes)
            if self.config.mode == "down":
                result.reverse()
            elif self.config.mode == "updown" and len(result) > 2:
                result = result + result[-2:0:-1]
            elif self.config.mode == "random":
                self._random.shuffle(result)
        return tuple(result)


def arp_interval_frames(sample_rate: int, tempo: float, rate: str) -> int:
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError("sample rate must be a positive integer")
    tempo = _number(tempo, "tempo", 40.0, 240.0)
    if rate not in _ARP_RATE_BEATS:
        raise ValueError("unsupported arpeggiator rate")
    return max(1, round(sample_rate * 60.0 / tempo * _ARP_RATE_BEATS[rate]))


class SequencerProcessor:
    """Sample-frame scheduler used by Engine before events reach VoiceManager."""

    def __init__(self, sample_rate: int, *, seed: int = 0) -> None:
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
            raise ValueError("sample rate must be a positive integer")
        self.sample_rate = sample_rate
        self._note_ids = NoteIds(1_000_000_000)
        self._lock = threading.Lock()
        self._config = SequenceConfig()
        self._pending: SequenceConfig | None = None
        self._tempo = 120.0
        self._swing = 0.0
        self._playing = False
        self._seq_anchor = 0
        self._seq_index = 0
        self._seq_active: dict[int, int] = {}
        self._held: dict[int, float] = {}
        self._held_velocity: dict[int, float] = {}
        self._physical_held: set[int] = set()
        self._loom_held: tuple[float, ...] = ()
        self._arp = Arpeggiator()
        self._arp_next: int | None = None
        self._arp_active: dict[int, int] = {}
        self._arp_index = 0
        self._arp_signature: tuple[float, ...] = ()
        self._random = random.Random(seed)

    @property
    def config(self) -> SequenceConfig:
        with self._lock:
            return self._pending or self._config

    def set_config(self, config: SequenceConfig) -> None:
        if not isinstance(config, SequenceConfig):
            raise TypeError("config must be a SequenceConfig")
        with self._lock:
            self._pending = config

    def _release_seq(self, frame: int) -> list[NoteOff]:
        releases = [NoteOff(note_id, frame) for note_id in self._seq_active]
        self._seq_active.clear()
        return releases

    def _release_arp(self, frame: int) -> list[NoteOff]:
        releases = [NoteOff(note_id, frame) for note_id in self._arp_active]
        self._arp_active.clear()
        return releases

    def _release_active(self, frame: int) -> list[NoteOff]:
        return [*self._release_seq(frame), *self._release_arp(frame)]

    def _held_pitches(self) -> tuple[float, ...]:
        if self._held:
            return tuple(self._held.values())
        return self._loom_held

    def _step_frame(self, index: int) -> int:
        step = self.sample_rate * 60.0 / self._tempo / 4.0
        return round(self._seq_anchor + index * step + (self._swing * step if index % 2 == 1 else 0.0))

    def _next_seq_frame(self) -> int | None:
        return self._step_frame(self._seq_index) if self._playing else None

    def _process_seq_tick(self, absolute: int, start: int, generated: list[Event]) -> None:
        pattern = self._config.pattern
        index = self._seq_index % pattern.length
        next_boundary = self._step_frame(self._seq_index + 1)
        step_len = max(1, next_boundary - absolute)
        for lane in pattern.lanes:
            step = lane[index]
            if not step.on or step.probability <= 0.0 or step.probability < 1.0 and self._random.random() >= step.probability:
                continue
            if step.note is None:
                pitches = self._held_pitches()
            else:
                pitches = (float(step.note),)
            for pitch in pitches:
                if not 0.0 <= pitch <= 127.0:
                    continue
                note_id = self._note_ids.next()
                frame = absolute - start
                generated.append(NoteOn(note_id, pitch, step.velocity, "sequencer", frame))
                duration = max(1, round(step_len * step.gate))
                self._seq_active[note_id] = absolute + duration
        self._seq_index += 1

    def _process_arp_tick(self, absolute: int, start: int, generated: list[Event]) -> None:
        if self._arp_active:
            generated.extend(NoteOff(note_id, absolute - start) for note_id in tuple(self._arp_active))
            self._arp_active.clear()
        pitches = self._held_pitches()
        if not pitches:
            self._arp_next = None
            return
        signature = tuple(pitches)
        if signature != self._arp_signature:
            self._arp_signature = signature
            self._arp_index = 0
        ordered = self._arp.order(signature)
        if not ordered:
            self._arp_next = None
            return
        pitch = ordered[self._arp_index % len(ordered)]
        self._arp_index += 1
        base_pitch = pitch % 12
        velocity = next(
            (self._held_velocity[note_id] for note_id, held_pitch in self._held.items() if int(round(held_pitch)) % 12 == int(round(base_pitch)) % 12),
            0.8,
        )
        note_id = self._note_ids.next()
        generated.append(NoteOn(note_id, pitch, velocity, "arpeggiator", absolute - start))
        interval = arp_interval_frames(self.sample_rate, self._tempo, self._config.arpeggiator.rate)
        self._arp_active[note_id] = absolute + interval
        self._arp_next = absolute + interval

    def process_block(self, block_start: int, events: Sequence[Event]) -> tuple[Event, ...]:
        """Merge generated notes with inputs, preserving block-relative frames."""
        if isinstance(block_start, bool) or not isinstance(block_start, int) or block_start < 0:
            raise ValueError("block_start must be a non-negative integer")
        generated: list[Event] = []
        with self._lock:
            pending = self._pending
            if pending is not None:
                self._pending = None
        if pending is not None:
            previous = self._config
            pattern_changed = pending.pattern != previous.pattern
            transport_changed = (pending.tempo, pending.swing, pending.playing) != (previous.tempo, previous.swing, previous.playing)
            arp_changed = pending.arpeggiator != previous.arpeggiator
            if pattern_changed or transport_changed:
                generated.extend(self._release_seq(0))
            if arp_changed:
                generated.extend(self._release_arp(0))
            old_latch = self._config.arpeggiator.latch
            self._config = pending
            if transport_changed:
                self._tempo, self._swing, self._playing = pending.tempo, pending.swing, pending.playing
            if pattern_changed or transport_changed:
                self._seq_anchor, self._seq_index = block_start, 0
            if arp_changed:
                self._arp.set_config(pending.arpeggiator)
            if old_latch and not pending.arpeggiator.latch:
                for note_id in tuple(self._held):
                    if note_id not in self._physical_held:
                        self._held.pop(note_id, None)
                        self._held_velocity.pop(note_id, None)
            if arp_changed:
                self._arp_signature = ()
                self._arp_index = 0
                self._arp_next = block_start if pending.arpeggiator.enabled and self._held_pitches() else None

        passthrough: list[Event] = []
        ordered = sorted(enumerate(events), key=lambda pair: (getattr(pair[1], "frame", 0), pair[0]))
        event_index = 0
        block_end = block_start + BLOCK
        while True:
            next_input = block_start + getattr(ordered[event_index][1], "frame", 0) if event_index < len(ordered) else block_end
            next_step = self._next_seq_frame()
            next_seq_off = min(self._seq_active.values(), default=block_end)
            next_arp = self._arp_next if self._config.arpeggiator.enabled and self._arp_next is not None else block_end
            next_arp_off = min(self._arp_active.values(), default=block_end)
            at = min(next_input, next_step if next_step is not None else block_end, next_seq_off, next_arp, next_arp_off, block_end)
            if at >= block_end:
                break
            offset = at - block_start
            # Releases at a boundary precede any new trigger at that boundary.
            for note_id, due in tuple(self._seq_active.items()):
                if due <= at:
                    generated.append(NoteOff(note_id, offset))
                    del self._seq_active[note_id]
            for note_id, due in tuple(self._arp_active.items()):
                if due <= at:
                    generated.append(NoteOff(note_id, offset))
                    del self._arp_active[note_id]
            while event_index < len(ordered) and block_start + getattr(ordered[event_index][1], "frame", 0) == at:
                event = ordered[event_index][1]
                event_index += 1
                if isinstance(event, Transport):
                    changed = (event.tempo != self._tempo or event.swing != self._swing or event.playing != self._playing)
                    if changed:
                        generated.extend(self._release_active(offset))
                        self._tempo, self._swing, self._playing = event.tempo, event.swing, event.playing
                        # Transport events are the live source of truth too. Keep
                        # the shared preset/config view in step with the scheduler
                        # so a later edit (for example an arp setting) does not
                        # compare against stale tempo or playing values.
                        self._config = replace(self._config, tempo=event.tempo, swing=event.swing, playing=event.playing)
                        self._seq_anchor, self._seq_index = at, 0
                        self._arp_next = at if self._config.arpeggiator.enabled and self._held_pitches() else None
                        self._arp_index = 0
                    passthrough.append(event)
                elif isinstance(event, NoteOn):
                    self._held[event.note_id] = event.pitch
                    self._held_velocity[event.note_id] = event.velocity
                    self._physical_held.add(event.note_id)
                    if self._config.arpeggiator.enabled:
                        if self._arp_next is None:
                            self._arp_next = at
                    else:
                        passthrough.append(event)
                elif isinstance(event, NoteOff):
                    self._physical_held.discard(event.note_id)
                    if not self._config.arpeggiator.latch:
                        self._held.pop(event.note_id, None)
                        self._held_velocity.pop(event.note_id, None)
                    if not self._config.arpeggiator.enabled:
                        passthrough.append(event)
                    if self._config.arpeggiator.enabled and not self._held_pitches():
                        self._arp_next = None
                        generated.extend(NoteOff(note_id, offset) for note_id in tuple(self._arp_active))
                        self._arp_active.clear()
                elif isinstance(event, RetargetNote):
                    if event.note_id in self._held:
                        self._held[event.note_id] = event.pitch
                    if not self._config.arpeggiator.enabled:
                        passthrough.append(event)
                elif isinstance(event, InstrumentEvent) and event.name == "held":
                    self._loom_held = tuple(float(value) for value in event.payload if isinstance(value, (int, float)) and 0 <= float(value) <= 127)
                    passthrough.append(event)
                elif isinstance(event, Panic):
                    generated.extend(self._release_active(offset))
                    self._held.clear()
                    self._held_velocity.clear()
                    self._physical_held.clear()
                    self._loom_held = ()
                    self._arp_next = None
                    if self._next_seq_frame() == at:
                        self._seq_index += 1
                    passthrough.append(event)
                else:
                    passthrough.append(event)
            # Input controls at this exact sample can stop/restart transport or
            # introduce held notes, so recalculate due ticks before triggering.
            if self._next_seq_frame() == at:
                self._process_seq_tick(at, block_start, generated)
            if self._config.arpeggiator.enabled and self._arp_next == at:
                self._process_arp_tick(at, block_start, generated)
        merged = [*passthrough, *generated]
        return tuple(sorted(merged, key=lambda event: (getattr(event, "frame", 0), 0 if isinstance(event, NoteOff) else 1)))

    def reset(self) -> None:
        self._seq_active.clear()
        self._arp_active.clear()
        self._held.clear()
        self._held_velocity.clear()
        self._physical_held.clear()
        self._loom_held = ()
        self._arp_next = None
        self._playing = False


__all__ = [
    "ARP_RATES", "Arpeggiator", "ArpeggiatorConfig", "Pattern", "SequenceConfig", "SequencerProcessor", "Step",
    "arp_interval_frames", "validate_extras",
]
