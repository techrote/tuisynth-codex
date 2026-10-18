"""LOOM waveguide instrument, bounded event voices, sympathetic bank and body."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from weakref import WeakValueDictionary

import numpy as np

from trio_kit.dsp import Biquad, Reverb
from trio_kit.params import ParamSnapshot
from trio_loom.body import BodyResonator
from trio_loom.params import loom_registry
from trio_loom.strum import StrumModel
from trio_loom.voice import LoomVoice
from trio_loom.waveguide import WaveguideString


_SCALES: dict[str, tuple[int, ...]] = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "pentatonic": (0, 2, 4, 7, 9),
    "bhairav": (0, 1, 4, 5, 7, 8, 11),
    "hijaz": (0, 1, 4, 5, 7, 8, 11),
}
_SYMPATHETIC_INPUT_GAIN = 0.0035


def _fold_string_pitch(pitch: float) -> float:
    """Fold a MIDI pitch by octaves into the waveguide's supported range."""
    value = float(pitch)
    while value > 100.0:
        value -= 12.0
    while value < 24.0:
        value += 12.0
    return value


def _choice(params: ParamSnapshot, key: str, choices: tuple[str, ...]) -> str:
    index = int(params[key])
    return choices[min(max(index, 0), len(choices) - 1)]


@dataclass(slots=True)
class _ScheduledVoice:
    due: int
    pitch: float
    velocity: float
    mode: str
    string_index: int
    order: int


@dataclass(slots=True)
class _EventVoice:
    voice: LoomVoice
    string_index: int
    order: int
    note_id: int
    started_frame: int
    released_frame: int | None = None
    level: float = 0.0
    fade_total: int = 0
    fade_position: int = 0


class LoomInstrument:
    """Seeded multi-string instrument with one-way resonant sympathetic feedback."""

    def __init__(self, *, seed: int = 0) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        self.seed = seed
        self.registry = loom_registry()
        self.sample_rate = 48_000
        self.block = 256
        self._params = ParamSnapshot(self.registry.defaults())
        self._extras: dict[str, object] = {}
        self._event_counter = 0
        self._modulation_note_counter = 0
        self._modulation_processor: object | None = None
        self._frame_clock = 0
        self._main_voice_count = 0
        self._main_voice_limit = 8
        self._event_voices: list[_EventVoice] = []
        self._bow_voices: dict[int, _EventVoice] = {}
        self._bow_strings: tuple[int, ...] = ()
        self._scheduled: list[_ScheduledVoice] = []
        self._held_pitches: tuple[float, ...] = ()
        self._voice_activity: dict[int, tuple[float, float]] = {}
        self._voices: WeakValueDictionary[int, LoomVoice] = WeakValueDictionary()
        self._strum = StrumModel(8)
        self._body = BodyResonator(self.sample_rate)
        self._reverb = Reverb(self.sample_rate, size=0.7, damp=0.5, mix=0.25)
        self._sym_lowpass = Biquad(self.sample_rate, kind="lowpass", cutoff=5_000.0, q=0.707)
        self._sympathetic = [WaveguideString(self.sample_rate, pitch=48 + index * 2, brightness=0.8) for index in range(12)]
        self._sympathetic_levels = np.zeros(12, dtype=np.float64)
        self._sympathetic_pitches = tuple(48 + index * 2 for index in range(12))
        self._pending_retune: list[float | None] = [None] * 12
        self._pre_master_peak = 0.0
        self._closed = False
        self._body.configure("guitar", 1.0)

    def prepare(self, sample_rate: int, block: int) -> None:
        self.sample_rate = int(sample_rate)
        self.block = int(block)
        self._body = BodyResonator(self.sample_rate)
        self._body.configure("guitar", 1.0)
        self._reverb = Reverb(self.sample_rate, size=0.7, damp=0.5, mix=0.25)
        self._sym_lowpass = Biquad(self.sample_rate, kind="lowpass", cutoff=min(5_000.0, 0.45 * self.sample_rate), q=0.707)
        self._sympathetic = [WaveguideString(self.sample_rate, pitch=48 + index * 2, brightness=0.8) for index in range(12)]
        self._sympathetic_levels.fill(0.0)
        self._pending_retune = [None] * 12

    def create_voice(self, rng: np.random.Generator) -> LoomVoice:
        voice = LoomVoice(self.sample_rate, rng, self._update_voice)
        self._voices[id(voice)] = voice
        return voice

    def set_engine_seed(self, seed: int) -> None:
        """Seed auxiliary event voices from the same deterministic engine seed."""
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("engine seed must be a non-negative integer")
        self.seed = seed
        self._event_counter = 0
        self._modulation_note_counter = 0

    def set_modulation_processor(self, processor: object) -> None:
        """Attach the shared engine modulation evaluator to surface-triggered voices."""
        if not callable(getattr(processor, "voice_snapshot", None)):
            raise TypeError("modulation processor must provide voice_snapshot")
        self._modulation_processor = processor

    def voice_limit(self, params: ParamSnapshot) -> int:
        """Set polyphony to eight plucks or four bows at each engine boundary."""
        return 4 if _choice(params, "exc.mode", ("pluck", "bow")) == "bow" else 8

    def set_main_voice_count(self, count: int, limit: int) -> None:
        """Share the mode's voice budget with string-surface event voices."""
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("main voice count must be a non-negative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("active voice limit must be a positive integer")
        self._main_voice_count = count
        self._main_voice_limit = limit
        self._trim_event_voices()

    def _event_voice_budget(self) -> int:
        limit = min(self.voice_limit(self._params), self._main_voice_limit)
        return max(0, limit - self._main_voice_count)

    def _fade_event_voice(self, item: _EventVoice) -> None:
        if item.fade_total > 0:
            return
        self._release_event_voice(item)
        item.fade_total = max(1, int(round(0.005 * self.sample_rate)))
        item.fade_position = 0
        if self._bow_voices.get(item.string_index) is item:
            self._bow_voices.pop(item.string_index, None)
            self._bow_strings = tuple(sorted(self._bow_voices))

    def _release_event_voice(self, item: _EventVoice) -> None:
        if item.released_frame is None:
            item.released_frame = self._frame_clock
            item.voice.release()

    def _event_voice_params(
        self,
        item: _EventVoice,
        params: ParamSnapshot,
        *,
        frame_index: int,
        frames: int,
        pitch: float | None = None,
        velocity: float | None = None,
    ) -> ParamSnapshot:
        processor = self._modulation_processor
        snapshot = getattr(processor, "voice_snapshot", None)
        if not callable(snapshot):
            return params
        released = None if item.released_frame is None else max(0, frame_index - item.released_frame)
        return snapshot(
            params,
            note_id=item.note_id,
            pitch=item.voice.pitch if pitch is None else pitch,
            velocity=item.voice.velocity if velocity is None else velocity,
            age_frames=max(0, frame_index - item.started_frame),
            released_frames=released,
            frames=frames,
        )

    def _trim_event_voices(self) -> None:
        active = sorted(
            (item for item in self._event_voices if item.fade_total == 0 and not item.voice._released),
            key=lambda item: item.order,
        )
        budget = self._event_voice_budget()
        for item in active[: max(0, len(active) - budget)]:
            self._fade_event_voice(item)

    def on_block_boundary(self, params: ParamSnapshot) -> None:
        self._params = params
        self._strum.set_string_count(int(params["strum.strings"]))
        self._body.configure(_choice(params, "body.type", ("none", "guitar", "violin", "cello", "harp", "sitar")), float(params["body.size"]))
        self._reverb.set_parameters(
            size=float(params["fx.reverb.size"]),
            damp=float(params["fx.reverb.damp"]),
            mix=float(params["fx.reverb.mix"]),
        )
        self._retune_bank(params)

    def _desired_sympathetic_pitches(self, params: ParamSnapshot) -> tuple[float, ...]:
        tuning = _choice(params, "sym.tuning", ("scale", "drone", "chord"))
        root = int(params["sym.root"])
        if tuning == "drone":
            pitches = [36 + root + 12 * octave + interval for octave in range(4) for interval in (0, 7)]
            return tuple(float(pitches[index % len(pitches)]) for index in range(12))
        if tuning == "chord":
            held = self._held_pitches
            pitches = self._strum.pitches("chord", held) if held else self._strum.pitches("direct")
            if len(pitches) >= 12:
                return tuple(_fold_string_pitch(pitch) for pitch in pitches[:12])
            extended = list(pitches)
            while len(extended) < 12:
                extended.append(extended[-1] + 12)
            return tuple(_fold_string_pitch(pitch) for pitch in extended[:12])
        scale_name = _choice(params, "sym.scale", ("major", "minor", "dorian", "pentatonic", "bhairav", "hijaz"))
        scale = _SCALES[scale_name]
        base = 48 + root
        pitches = tuple(float(base + (index // len(scale)) * 12 + scale[index % len(scale)]) for index in range(12))
        return pitches

    def _retune_bank(self, params: ParamSnapshot) -> None:
        desired = self._desired_sympathetic_pitches(params)
        for index, (resonator, pitch) in enumerate(zip(self._sympathetic, desired)):
            pending = self._pending_retune[index]
            target = pitch if pending is None else pending
            if target != pitch and abs(pitch - target) > 0.01:
                target = pitch
            if abs(target - resonator.pitch) <= 0.01:
                self._pending_retune[index] = None
                continue
            if self._sympathetic_levels[index] <= 0.001:
                resonator.set_pitch(target)
                self._sympathetic_pitches = tuple(
                    float(item.pitch) for item in self._sympathetic
                )
                self._pending_retune[index] = None
            else:
                self._pending_retune[index] = target

    def _update_voice(self, identity: int, pitch: float, rms: float) -> None:
        self._prune_voice_activity()
        if rms <= 0.0:
            self._voice_activity.pop(identity, None)
            return
        if identity not in self._voice_activity and len(self._voice_activity) >= 16:
            self._voice_activity.pop(next(iter(self._voice_activity)))
        self._voice_activity[identity] = (float(pitch), float(rms))

    def _prune_voice_activity(self) -> None:
        for identity in tuple(self._voice_activity):
            voice = self._voices.get(identity)
            if voice is None or voice.finished:
                self._voice_activity.pop(identity, None)

    def _new_event_voice(
        self,
        pitch: float,
        velocity: float,
        mode: str,
        string_index: int,
        *,
        start_frame: int | None = None,
    ) -> _EventVoice | None:
        limit = self._event_voice_budget()
        if limit <= 0:
            return None
        active = [item for item in self._event_voices if item.fade_total == 0 and not item.voice._released]
        if len(active) >= limit:
            oldest = min(active, key=lambda item: item.order)
            self._fade_event_voice(oldest)
        rng = np.random.default_rng(np.random.SeedSequence([self.seed, self._event_counter]))
        self._event_counter += 1
        self._modulation_note_counter += 1
        # Surface event IDs use a high namespace disjoint from ordinary MIDI and
        # sequencer note IDs while remaining deterministic for seeded renders.
        note_id = (1 << 62) + self._modulation_note_counter
        started = self._frame_clock if start_frame is None else int(start_frame)
        voice = self.create_voice(rng)
        item = _EventVoice(voice, string_index, self._event_counter, note_id, started)
        voice.start_event(
            pitch,
            velocity,
            self._event_voice_params(
                item, self._params, frame_index=started, frames=0,
                pitch=pitch, velocity=velocity,
            ),
            mode,
        )
        self._event_voices.append(item)
        while len(self._event_voices) > max(1, self.voice_limit(self._params)) * 3:
            oldest_tail = next((item for item in self._event_voices if item.fade_total > 0), None)
            if oldest_tail is None:
                break
            self._event_voices.remove(oldest_tail)
            finished = getattr(self._modulation_processor, "note_finished", None)
            if callable(finished):
                finished(oldest_tail.note_id)
        return item

    @staticmethod
    def _number(value: float | int | str, default: float) -> float:
        if isinstance(value, str):
            try:
                result = float(value)
            except ValueError:
                return default
        else:
            result = float(value)
        return result if math.isfinite(result) else default

    def on_event(self, name: str, payload: tuple[float | int | str, ...]) -> None:
        """Handle string crossings, sustained bow gestures, and keyboard strums.

        `strum` payload is `(direction, rows_per_second, held_pitch...)`; direction
        accepts +1/`down` or -1/`up`. Individual string `pluck` and `bow` events take
        `(pitch, velocity[, string_index])`; `mute` takes a string index. `bow_on`/`bow_off`
        hold and release a bowed string; `bow` retains the continuous crossing behavior.
        `held` replaces the keyboard chord snapshot, including when it is empty.
        """
        if name == "held":
            self._held_pitches = tuple(
                pitch for value in payload[:12]
                if 0 <= (pitch := self._number(value, -1.0)) <= 127
            )
            return
        if name == "bow_off":
            if payload:
                index = int(self._number(payload[0], -1))
                item = self._bow_voices.pop(index, None)
                if item is not None:
                    self._release_event_voice(item)
                    self._bow_strings = tuple(sorted(self._bow_voices))
            return
        if name == "bow_on":
            if len(payload) < 3:
                return
            pitch = self._number(payload[0], 60.0)
            velocity = min(1.0, max(0.0, self._number(payload[1], 0.7)))
            string_index = int(self._number(payload[2], -1)) if len(payload) > 2 else -1
            if not 0 <= string_index < int(self._params["strum.strings"]):
                return
            previous = self._bow_voices.pop(string_index, None)
            if previous is not None:
                self._release_event_voice(previous)
            item = self._new_event_voice(pitch, velocity, "bow", string_index)
            if item is not None:
                self._bow_voices[string_index] = item
            self._bow_strings = tuple(sorted(self._bow_voices))
            return
        if not payload:
            return
        if name in {"pluck", "bow"}:
            if len(payload) < 2:
                return
            pitch = self._number(payload[0], 60.0)
            velocity = min(1.0, max(0.0, self._number(payload[1], 0.7)))
            string_index = int(self._number(payload[2], -1)) if len(payload) > 2 else -1
            self._new_event_voice(pitch, velocity, name, string_index)
            return
        if name == "mute":
            index = int(self._number(payload[0], -1))
            pitches = self._strum.pitches(
                _choice(self._params, "play.mode", ("direct", "chord")),
                self._held_pitches,
            )
            target_pitch = pitches[index] if 0 <= index < len(pitches) else None
            if target_pitch is not None:
                for voice in tuple(self._voices.values()):
                    if not voice.finished and abs(voice.pitch - target_pitch) < 0.5:
                        voice.choke()
            for item in self._event_voices:
                if item.string_index == index:
                    self._fade_event_voice(item)
            self._bow_voices.pop(index, None)
            self._bow_strings = tuple(sorted(self._bow_voices))
            self._scheduled = [item for item in self._scheduled if item.string_index != index]
            return
        if name != "strum" or len(self._scheduled) > 52:
            return
        direction_value = payload[0]
        direction = -1 if direction_value in ("up", -1) or (not isinstance(direction_value, str) and self._number(direction_value, 1) < 0) else 1
        speed = self._number(payload[1], 20.0) if len(payload) > 1 else 20.0
        held = tuple(self._number(value, -1) for value in payload[2:14])
        held = tuple(pitch for pitch in held if 0 <= pitch <= 127)
        self._held_pitches = held
        mode = _choice(self._params, "play.mode", ("direct", "chord"))
        pitches = self._strum.pitches(mode, self._held_pitches)
        velocity = self._strum.crossing_velocity(speed)
        string_count = self._strum.string_count
        spread_frames = int(round(float(self._params["strum.spread"]) * self.sample_rate / 1_000.0))
        crossings = self._strum.ordered_crossings(string_count, direction)
        for rank, string_index in enumerate(crossings):
            delay = int(round(rank * spread_frames / max(1, string_count - 1)))
            self._scheduled.append(
                _ScheduledVoice(
                    due=self._frame_clock + delay,
                    pitch=float(pitches[string_index]),
                    velocity=velocity,
                    mode=_choice(self._params, "exc.mode", ("pluck", "bow")),
                    string_index=string_index,
                    order=self._event_counter + rank,
                )
            )
        self._scheduled.sort(key=lambda item: (item.due, item.order))

    def _render_event_voices(self, frames: int, params: ParamSnapshot, *, frame_index: int) -> np.ndarray:
        output = np.zeros((frames, 2), dtype=np.float32)
        live: list[_EventVoice] = []
        for item in self._event_voices:
            voice_params = self._event_voice_params(item, params, frame_index=frame_index, frames=frames)
            buffer = item.voice.render(frames, voice_params)
            if item.fade_total > 0:
                count = min(frames, item.fade_total - item.fade_position)
                gains = np.maximum(
                    0.0,
                    1.0 - (item.fade_position + np.arange(count, dtype=np.float64)) / item.fade_total,
                ).astype(np.float32)
                buffer[:count] *= gains[:, None]
                if count < frames:
                    buffer[count:] = 0.0
                item.fade_position += count
            item.level = float(np.sqrt(np.mean(np.square(buffer, dtype=np.float64)))) if frames else 0.0
            output += buffer
            if not item.voice.finished and (item.fade_total == 0 or item.fade_position < item.fade_total):
                live.append(item)
            else:
                finished = getattr(self._modulation_processor, "note_finished", None)
                if callable(finished):
                    finished(item.note_id)
        self._event_voices = live
        return output

    def process_pre_fx(self, buffer: np.ndarray, params: ParamSnapshot) -> np.ndarray:
        samples = np.asarray(buffer, dtype=np.float32)
        if samples.ndim != 2 or samples.shape[1] != 2:
            raise ValueError("LOOM bus expects stereo buffers")
        self._params = params
        frames = len(samples)
        result = np.array(samples, dtype=np.float32, copy=True)
        cursor = 0
        while cursor < frames:
            due_offset = self._scheduled[0].due - self._frame_clock if self._scheduled else frames
            if due_offset > cursor:
                count = min(frames - cursor, due_offset - cursor)
                result[cursor : cursor + count] += self._render_event_voices(
                    count, params, frame_index=self._frame_clock + cursor,
                )
                cursor += count
                continue
            due_frame = self._frame_clock + cursor
            while self._scheduled and self._scheduled[0].due <= due_frame:
                item = self._scheduled.pop(0)
                self._new_event_voice(
                    item.pitch, item.velocity, item.mode, item.string_index,
                    start_frame=due_frame,
                )
            if not self._scheduled and cursor < frames:
                count = frames - cursor
                result[cursor:] += self._render_event_voices(
                    count, params, frame_index=self._frame_clock + cursor,
                )
                cursor = frames

        # Surface-triggered string voices have already been added to result. Feed
        # both those strings and keyboard/MIDI voices into the same one-way bank.
        mono = np.mean(result.astype(np.float64), axis=1)
        coupled = self._sym_lowpass.process(mono).astype(np.float64) * (
            _SYMPATHETIC_INPUT_GAIN * float(params["sym.couple"])
        )
        sympathetic = np.zeros(frames, dtype=np.float64)
        for index, resonator in enumerate(self._sympathetic):
            wave = resonator.process(coupled, float(params["sym.decay"])).astype(np.float64)
            resonant = wave - coupled
            sympathetic += resonant
            self._sympathetic_levels[index] = float(np.sqrt(np.mean(np.square(resonant)))) if frames else 0.0
            pending = self._pending_retune[index]
            if pending is not None and self._sympathetic_levels[index] <= 0.001:
                resonator.set_pitch(pending)
                self._pending_retune[index] = None
        self._sympathetic_pitches = tuple(float(item.pitch) for item in self._sympathetic)
        sym_mix = float(params["sym.mix"])
        if sym_mix:
            sym_stereo = np.column_stack((sympathetic, sympathetic)).astype(np.float32)
            result += sym_stereo * sym_mix

        body_mix = float(params["body.mix"])
        if body_mix and self._body.filters:
            body = self._body.process(result)
            result = (result * (1.0 - body_mix) + body * body_mix).astype(np.float32)
        return result.astype(np.float32, copy=False)

    def process_fx_unit(self, name: str, buffer: np.ndarray, params: ParamSnapshot) -> np.ndarray:
        result = np.asarray(buffer, dtype=np.float32)
        if name != "reverb":
            return result
        self._reverb.set_parameters(size=float(params["fx.reverb.size"]), damp=float(params["fx.reverb.damp"]), mix=float(params["fx.reverb.mix"]))
        return self._reverb.process(result)

    def process_post_fx(self, buffer: np.ndarray, params: ParamSnapshot) -> np.ndarray:
        result = np.asarray(buffer, dtype=np.float32)
        frames = len(result)
        drive = float(params["master.drive"])
        if drive:
            result = (np.tanh(result.astype(np.float64) * (1.0 + 5.0 * drive)) / (1.0 + 5.0 * drive)).astype(np.float32)
        result *= float(params["master.level"])
        if result.size:
            self._pre_master_peak = max(self._pre_master_peak, float(np.max(np.abs(result))))
        self._frame_clock += frames
        return result.astype(np.float32, copy=False)

    def process_bus(self, buffer: np.ndarray, params: ParamSnapshot) -> np.ndarray:
        """Compatibility wrapper preserving direct bus callers."""
        output = self.process_pre_fx(buffer, params)
        output = self.process_fx_unit("reverb", output, params)
        return self.process_post_fx(output, params)

    def telemetry(self) -> Mapping[str, object]:
        self._prune_voice_activity()
        mode = _choice(self._params, "play.mode", ("direct", "chord"))
        pitches = self._strum.pitches(mode, self._held_pitches)
        levels = [0.0] * len(pitches)
        for pitch, level in self._voice_activity.values():
            if pitches:
                index = min(range(len(pitches)), key=lambda item: abs(pitches[item] - pitch))
                levels[index] = max(levels[index], float(level))
        for item in self._event_voices:
            if 0 <= item.string_index < len(levels):
                levels[item.string_index] = max(levels[item.string_index], item.level)
        phase_turn = self._frame_clock / self.sample_rate * 0.7
        phases = tuple((phase_turn + index * 0.137) % 1.0 for index in range(len(pitches)))
        return {
            "string_pitches": tuple(float(item) for item in pitches),
            "string_levels": tuple(levels),
            "string_phases": phases,
            # The audio thread publishes this immutable snapshot when the map
            # changes; UI telemetry never mutates audio-owned voice state.
            "bow_strings": self._bow_strings,
            "sympathetic_pitches": self._sympathetic_pitches,
            "sympathetic_levels": tuple(float(level) for level in self._sympathetic_levels),
            "event_voices": sum(item.fade_total == 0 and not item.voice._released for item in self._event_voices),
            "pending_strums": len(self._scheduled),
            "body": _choice(self._params, "body.type", ("none", "guitar", "violin", "cello", "harp", "sitar")),
            "excitation": _choice(self._params, "exc.mode", ("pluck", "bow")),
            "pre_master_peak": self._pre_master_peak,
        }

    def reset(self) -> None:
        finished = getattr(self._modulation_processor, "note_finished", None)
        if callable(finished):
            for item in self._event_voices:
                finished(item.note_id)
        self._event_voices.clear()
        self._bow_voices.clear()
        self._bow_strings = ()
        self._scheduled.clear()
        self._voice_activity.clear()
        self._held_pitches = ()
        self._main_voice_count = 0
        self._frame_clock = 0
        self._pre_master_peak = 0.0
        self._sympathetic_levels.fill(0.0)
        for resonator in self._sympathetic:
            resonator.reset()
        self._sym_lowpass.reset()
        self._body.reset()
        self._reverb.reset()

    def get_extras(self) -> dict[str, object]:
        return dict(self._extras)

    def set_extras(self, extras: Mapping[str, object]) -> None:
        if not isinstance(extras, Mapping):
            raise ValueError("LOOM extras must be a mapping")
        self._extras = dict(extras)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.reset()


__all__ = ["LoomInstrument"]
