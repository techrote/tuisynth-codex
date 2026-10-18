"""AURORA instrument, polyphonic PADsynth voices and table regeneration worker."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Mapping, Sequence

import numpy as np

from trio_aurora.padsynth import (
    TABLE_SIZE,
    PadsynthTableSet,
    TableSetCache,
    note_frequency,
)
from trio_aurora.params import (
    FILTER_CHOICES,
    LFO_TARGETS,
    LFO_WAVES,
    aurora_registry,
    validate_extras,
)
from trio_kit.dsp import Adsr, Biquad, Chorus, Lfo, Reverb, StereoDelay
from trio_kit.params import ParamSnapshot


_SPECTRAL_KEYS = (
    "spec.count",
    "spec.bw",
    "spec.bwscale",
    "spec.stretch",
    "spec.tilt",
    "spec.noise",
    "spec.seed",
)
_DETUNE_MIX = 10.0 ** (-6.0 / 20.0)


def _read(table: np.ndarray, positions: np.ndarray) -> np.ndarray:
    wrapped = np.mod(positions, TABLE_SIZE)
    base = np.floor(wrapped).astype(np.int64)
    fraction = wrapped - base
    following = (base + 1) % TABLE_SIZE
    return table[base] * (1.0 - fraction) + table[following] * fraction


def _phase_positions(phase: float, increments: np.ndarray) -> tuple[np.ndarray, float]:
    offsets = np.cumsum(increments, dtype=np.float64) - increments
    return phase + offsets, float((phase + float(np.sum(increments))) % TABLE_SIZE)


class AuroraVoice:
    """One phase-continuous stereo table voice with independent envelopes and LFO."""

    def __init__(self, instrument: AuroraInstrument, sample_rate: int, seed: int, phase: float) -> None:
        self.instrument = instrument
        self.sample_rate = sample_rate
        self.pitch = 60.0
        self.velocity = 0.0
        self.finished = True
        self._phase_primary = 0.0
        self._phase_detune_left = 0.0
        self._phase_detune_right = 0.0
        self._amp = Adsr(sample_rate, attack=1.8, decay=1.5, sustain=0.8, release=4.0)
        self._filter_env = Adsr(sample_rate, attack=2.5, decay=2.0, sustain=0.5, release=5.0)
        self._lfo = Lfo(sample_rate, rate=0.15, waveform="smooth_random", seed=seed, phase=phase)
        self._filters = {
            mode: (
                Biquad(sample_rate, kind=mode, cutoff=5_000.0, q=0.707),
                Biquad(sample_rate, kind=mode, cutoff=5_000.0, q=0.707),
            )
            for mode in ("lowpass", "bandpass", "highpass")
        }

    def start(self, pitch: float, velocity: float, params: ParamSnapshot) -> None:
        self.pitch = float(pitch)
        self.velocity = float(velocity)
        self._phase_primary = 0.0
        self._phase_detune_left = 0.0
        self._phase_detune_right = 0.0
        self._set_envelope_parameters(params)
        self._amp.reset()
        self._filter_env.reset()
        self._lfo.reset()
        for filters in self._filters.values():
            for filt in filters:
                filt.reset()
        self._amp.gate_on(1.0)
        self._filter_env.gate_on(1.0)
        self.finished = False

    def release(self) -> None:
        self._amp.gate_off()
        self._filter_env.gate_off()

    def retarget(self, pitch: float) -> None:
        self.pitch = float(pitch)

    def _set_envelope_parameters(self, params: ParamSnapshot) -> None:
        self._amp.set_parameters(
            attack=float(params["amp.a"]),
            decay=float(params["amp.d"]),
            sustain=float(params["amp.s"]),
            release=float(params["amp.r"]),
        )
        self._filter_env.set_parameters(
            attack=float(params["fenv.a"]),
            decay=float(params["fenv.d"]),
            sustain=float(params["fenv.s"]),
            release=float(params["fenv.r"]),
        )

    def _read_state(
        self,
        old_tables: PadsynthTableSet | None,
        active_tables: PadsynthTableSet,
        midi_pitch: float,
        positions: np.ndarray,
        frames: int,
        fade_position: int,
        fade_frames: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        active_zone = active_tables.zone_for_pitch(midi_pitch)
        active_left = _read(active_zone.left, positions)
        active_right_full = _read(active_zone.right, positions)
        if old_tables is None or fade_frames <= 0:
            return active_left, active_right_full
        old_zone = old_tables.zone_for_pitch(midi_pitch)
        old_left = _read(old_zone.left, positions)
        old_right = _read(old_zone.right, positions)
        fade = np.clip((fade_position + np.arange(frames, dtype=np.float64) + 1.0) / fade_frames, 0.0, 1.0)
        return (
            old_left * (1.0 - fade) + active_left * fade,
            old_right * (1.0 - fade) + active_right_full * fade,
        )

    def render(self, frames: int, params: ParamSnapshot) -> np.ndarray:
        if frames == 0:
            return np.zeros((0, 2), dtype=np.float32)
        if self.finished:
            return np.zeros((frames, 2), dtype=np.float32)

        self._set_envelope_parameters(params)
        amp = self._amp.process(frames)
        filter_env = self._filter_env.process(frames)
        lfo_rate = float(params["lfo.rate"])
        self._lfo.set_rate(lfo_rate)
        self._lfo.waveform = LFO_WAVES[int(params["lfo.wave"])]
        modulation = self._lfo.process(frames).astype(np.float64) * float(params["lfo.depth"])
        lfo_target = LFO_TARGETS[int(params["lfo.tgt"])]

        zone_pitch = self.pitch + 12.0 * float(params["osc.octave"])
        pitch: float | np.ndarray = zone_pitch
        if lfo_target == "pitch":
            pitch = pitch + modulation * 0.5
        pitch_values = np.clip(pitch, 0.0, 127.0)
        frequencies = 440.0 * np.exp2((pitch_values - 69.0) / 12.0)
        frequencies = np.asarray(frequencies, dtype=np.float64)
        if frequencies.ndim == 0:
            frequencies = np.full(frames, float(frequencies), dtype=np.float64)
        self.instrument._last_note_frequency = float(np.mean(frequencies))

        old_tables, active_tables, fade_position, fade_frames = self.instrument._table_state()
        if active_tables is None:
            self.finished = self._amp.finished
            return np.zeros((frames, 2), dtype=np.float32)

        primary_zone = active_tables.zone_for_pitch(zone_pitch)
        increments = frequencies / primary_zone.frequency
        positions, self._phase_primary = _phase_positions(self._phase_primary, increments)
        left, right = self._read_state(
            old_tables,
            active_tables,
            zone_pitch,
            positions,
            frames,
            fade_position,
            fade_frames,
        )

        detune = float(params["osc.detune"])
        if detune > 0:
            detune_ratio = 2.0 ** (detune / 1_200.0)
            left_positions, self._phase_detune_left = _phase_positions(
                self._phase_detune_left,
                increments * detune_ratio,
            )
            right_positions, self._phase_detune_right = _phase_positions(
                self._phase_detune_right,
                increments / detune_ratio,
            )
            left_second, _ = self._read_state(
                old_tables,
                active_tables,
                zone_pitch,
                left_positions,
                frames,
                fade_position,
                fade_frames,
            )
            _, right_second_full = self._read_state(
                old_tables,
                active_tables,
                zone_pitch,
                right_positions,
                frames,
                fade_position,
                fade_frames,
            )
            right_second = left_second * (1.0 - float(params["osc.width"])) + right_second_full * float(params["osc.width"])
            right = left * (1.0 - float(params["osc.width"])) + right * float(params["osc.width"])
            left = (left + _DETUNE_MIX * left_second) / (1.0 + _DETUNE_MIX)
            right = (right + _DETUNE_MIX * right_second) / (1.0 + _DETUNE_MIX)
        else:
            self._phase_detune_left = self._phase_primary
            self._phase_detune_right = self._phase_primary
            width = float(params["osc.width"])
            right = left * (1.0 - width) + right * width

        cutoff = float(params["flt.cut"])
        cutoff *= 2.0 ** (float(params["flt.env"]) * float(np.mean(filter_env)) * 5.0)
        cutoff *= 2.0 ** (float(params["flt.key"]) * (self.pitch - 60.0) / 12.0)
        if lfo_target == "cutoff":
            cutoff *= 2.0 ** (float(np.mean(modulation)) * 2.0)
        cutoff = min(max(cutoff, 20.0), 0.45 * self.sample_rate)
        resonance = 0.5 + 19.5 * float(params["flt.res"])
        for filters in self._filters.values():
            for filt in filters:
                filt.set_parameters(cutoff=cutoff, q=resonance)
        filtered: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for mode, filters in self._filters.items():
            filtered[mode] = (filters[0].process(left), filters[1].process(right))
        selected_mode = FILTER_CHOICES[int(params["flt.mode"])]
        mode_key = {"lp": "lowpass", "bp": "bandpass", "hp": "highpass"}[selected_mode]
        left, right = filtered[mode_key]

        velocity_sensitivity = float(params["amp.vel"])
        velocity_gain = (1.0 - velocity_sensitivity) + velocity_sensitivity * self.velocity
        amplitude = amp.astype(np.float64) * velocity_gain * 0.35
        if lfo_target == "amplitude":
            amplitude *= np.maximum(0.0, 1.0 + modulation)
        if lfo_target == "pan":
            pan = np.clip(modulation, -1.0, 1.0)
            angle = (pan + 1.0) * (math.pi / 4.0)
            left *= np.cos(angle) * math.sqrt(2.0)
            right *= np.sin(angle) * math.sqrt(2.0)
        output = np.column_stack((left * amplitude, right * amplitude)).astype(np.float32)
        self.finished = self._amp.finished
        return output


class AuroraInstrument:
    """Seven-zone AURORA instrument with debounced background table regeneration."""

    def __init__(self, *, table_cache: TableSetCache | None = None) -> None:
        self.registry = aurora_registry()
        self.sample_rate = 48_000
        self.block = 256
        self._harmonics = tuple(validate_extras({})["harmonics"])
        self._table_cache = TableSetCache() if table_cache is None else table_cache
        self._condition = threading.Condition(threading.RLock())
        self._thread: threading.Thread | None = None
        self._stop_worker = False
        self._prepared = False
        self._current_params: dict[str, int | float] = self.registry.defaults()
        self._latest_signature: tuple[object, ...] | None = None
        self._request_version = 0
        self._requested_state: tuple[int, dict[str, int | float], tuple[float, ...]] | None = None
        self._request_deadline = 0.0
        self._pending_tables: PadsynthTableSet | None = None
        self._pending_version: int | None = None
        self._active_tables: PadsynthTableSet | None = None
        self._active_version: int | None = None
        self._old_tables: PadsynthTableSet | None = None
        self._fade_position = 0
        self._fade_frames = int(round(0.05 * self.sample_rate))
        self._generation_count = 0
        self._generation_error: str | None = None
        self._error_version: int | None = None
        self._last_note_frequency = 0.0
        self._last_voice_rms = 0.0
        self._chorus: Chorus | None = None
        self._delay: StereoDelay | None = None
        self._reverb: Reverb | None = None

    def prepare(self, sample_rate: int, block: int) -> None:
        if sample_rate not in (44_100, 48_000) or block != 256:
            raise ValueError("AURORA requires 44.1/48 kHz and 256-frame blocks")
        with self._condition:
            if self._prepared:
                if self.sample_rate != sample_rate or self.block != block:
                    raise RuntimeError("AURORA cannot be prepared twice with different engine settings")
                return
            self.sample_rate = sample_rate
            self.block = block
            self._fade_frames = int(round(0.05 * sample_rate))
            self._chorus = Chorus(sample_rate, mix=float(self._current_params["fx.chorus.mix"]), seed=173)
            self._delay = StereoDelay(
                sample_rate,
                delay_seconds=float(self._current_params["fx.delay.time"]),
                feedback=float(self._current_params["fx.delay.fb"]),
                mix=float(self._current_params["fx.delay.mix"]),
            )
            self._reverb = Reverb(
                sample_rate,
                size=float(self._current_params["fx.reverb.size"]),
                damp=float(self._current_params["fx.reverb.damp"]),
                mix=float(self._current_params["fx.reverb.mix"]),
            )
            self._prepared = True
            self._thread = threading.Thread(target=self._worker_loop, name="aurora-padsynth", daemon=True)
            self._thread.start()
            self._request_tables_locked(self._current_params, self._harmonics)

    def create_voice(self, rng: np.random.Generator) -> AuroraVoice:
        seed = int(rng.integers(0, 2**32, dtype=np.uint64))
        phase = float(rng.random())
        return AuroraVoice(self, self.sample_rate, seed, phase)

    @staticmethod
    def _spectral_signature(
        sample_rate: int,
        params: Mapping[str, int | float],
        harmonics: Sequence[float],
    ) -> tuple[object, ...]:
        return (sample_rate, *(params[key] for key in _SPECTRAL_KEYS), tuple(harmonics))

    def _request_tables_locked(self, params: Mapping[str, int | float], harmonics: Sequence[float]) -> None:
        signature = self._spectral_signature(self.sample_rate, params, harmonics)
        if signature == self._latest_signature:
            return
        self._latest_signature = signature
        self._request_version += 1
        self._requested_state = (self._request_version, dict(params), tuple(harmonics))
        self._request_deadline = time.monotonic() + 0.15
        # Pending tables are not visible to voices yet. Drop obsolete output so
        # offline waiters do not depend on another block arriving to clear it.
        self._pending_tables = None
        self._pending_version = None
        active_key = self._active_tables.key if self._active_tables is not None else None
        self._table_cache.retain(active_key)
        self._generation_error = None
        self._condition.notify_all()

    def set_extras(self, extras: Mapping[str, object]) -> None:
        validated = validate_extras(dict(extras))
        harmonics = tuple(float(value) for value in validated["harmonics"])
        with self._condition:
            if harmonics == self._harmonics:
                return
            self._harmonics = harmonics
            if self._prepared:
                self._request_tables_locked(self._current_params, self._harmonics)

    def get_extras(self) -> dict[str, object]:
        with self._condition:
            return {"harmonics": list(self._harmonics)}

    def on_block_boundary(self, params: ParamSnapshot) -> None:
        normalized = self.registry.validate(params)
        with self._condition:
            self._current_params = normalized
            self._request_tables_locked(normalized, self._harmonics)
            if self._pending_tables is not None:
                if self._pending_version != self._request_version:
                    self._pending_tables = None
                    self._pending_version = None
                    self._condition.notify_all()
                elif self._active_tables is None:
                    self._active_tables = self._pending_tables
                    self._active_version = self._pending_version
                    self._pending_tables = None
                    self._pending_version = None
                    self._condition.notify_all()
                elif self._pending_tables.key == self._active_tables.key:
                    self._active_version = self._pending_version
                    self._pending_tables = None
                    self._pending_version = None
                    self._condition.notify_all()
                elif self._old_tables is None:
                    self._old_tables = self._active_tables
                    self._active_tables = self._pending_tables
                    self._active_version = self._pending_version
                    self._pending_tables = None
                    self._pending_version = None
                    self._fade_position = 0
                    self._condition.notify_all()

    def _worker_loop(self) -> None:
        while True:
            with self._condition:
                while not self._stop_worker and self._requested_state is None:
                    self._condition.wait()
                if self._stop_worker:
                    return
                version, params, harmonics = self._requested_state
                while not self._stop_worker:
                    if version != self._request_version:
                        if self._requested_state is None:
                            break
                        version, params, harmonics = self._requested_state
                        continue
                    remaining = self._request_deadline - time.monotonic()
                    if remaining > 0:
                        self._condition.wait(remaining)
                        continue
                    if self._pending_tables is not None or self._old_tables is not None:
                        self._condition.wait(0.05)
                        continue
                    self._requested_state = None
                    active_key = self._active_tables.key if self._active_tables is not None else None
                    break
                if self._stop_worker:
                    return
                if self._requested_state is not None or version != self._request_version:
                    continue

            try:
                table_set = self._table_cache.get_or_generate(
                    self.sample_rate,
                    params,
                    harmonics,
                    registry=self.registry,
                    keep_key=active_key,
                )
            except Exception as error:
                with self._condition:
                    if version == self._request_version:
                        self._generation_error = f"{type(error).__name__}: {error}"[:256]
                        self._error_version = version
                        self._condition.notify_all()
                continue

            with self._condition:
                self._generation_count += 1
                if self._stop_worker:
                    return
                if version != self._request_version:
                    active_key = self._active_tables.key if self._active_tables is not None else None
                    self._table_cache.retain(active_key)
                    continue
                self._pending_tables = table_set
                self._pending_version = version
                self._generation_error = None
                self._condition.notify_all()

    def wait_for_regeneration(self, timeout: float = 60.0, *, active: bool = False) -> bool:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(float(timeout)) or timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
        deadline = time.monotonic() + float(timeout)
        with self._condition:
            target = self._request_version
            while True:
                if active:
                    if self._active_version == target and self._old_tables is None:
                        return True
                elif self._active_version == target or self._pending_version == target:
                    return True
                if self._error_version == target and self._generation_error:
                    raise RuntimeError(f"AURORA table generation failed: {self._generation_error}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("AURORA table regeneration did not finish before the timeout")
                self._condition.wait(min(remaining, 0.1))

    def _table_state(self) -> tuple[PadsynthTableSet | None, PadsynthTableSet | None, int, int]:
        with self._condition:
            return self._old_tables, self._active_tables, self._fade_position, self._fade_frames

    def _advance_crossfade(self, frames: int) -> None:
        with self._condition:
            if self._old_tables is None:
                return
            self._fade_position = min(self._fade_frames, self._fade_position + frames)
            if self._fade_position >= self._fade_frames:
                self._old_tables = None
                self._condition.notify_all()

    def process_bus(self, buffer: np.ndarray, params: ParamSnapshot) -> np.ndarray:
        samples = np.asarray(buffer, dtype=np.float32)
        if samples.ndim != 2 or samples.shape[1] != 2:
            raise ValueError("AURORA bus input must be stereo")
        if not np.isfinite(samples).all():
            return samples
        chorus = self._chorus
        delay = self._delay
        reverb = self._reverb
        if chorus is None or delay is None or reverb is None:
            return samples

        chorus.set_parameters(mix=float(params["fx.chorus.mix"]))
        delay.set_parameters(
            delay_seconds=float(params["fx.delay.time"]),
            feedback=float(params["fx.delay.fb"]),
            mix=float(params["fx.delay.mix"]),
        )
        reverb.set_parameters(
            size=float(params["fx.reverb.size"]),
            damp=float(params["fx.reverb.damp"]),
            mix=float(params["fx.reverb.mix"]),
        )
        effected = reverb.process(delay.process(chorus.process(samples)))
        drive = float(params["master.drive"])
        if drive > 0.0:
            shaped = np.tanh(effected * (1.0 + 9.0 * drive)) / math.tanh(1.0 + 9.0 * drive)
            effected = effected * (1.0 - drive) + shaped * drive
        output = (effected * float(params["master.level"])).astype(np.float32)
        self._advance_crossfade(len(samples))
        self._last_voice_rms = float(np.sqrt(np.mean(np.square(output, dtype=np.float64)))) if len(output) else 0.0
        return output

    def on_event(self, name: str, payload: tuple[float | int | str, ...]) -> None:
        if name == "harmonics":
            self.set_extras({"harmonics": list(payload)})
        elif name == "harmonic" and len(payload) == 2:
            index, value = payload
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 64:
                return
            harmonics = list(self.get_extras()["harmonics"])
            harmonics[index] = float(value)
            self.set_extras({"harmonics": harmonics})
        elif name == "reset_effects":
            self.reset()

    def telemetry(self) -> Mapping[str, object]:
        with self._condition:
            params = dict(self._current_params)
            harmonics = self._harmonics
            fundamental = self._last_note_frequency
            partial_count = int((16, 32, 64)[int(params["spec.count"])])
            stretch = float(params["spec.stretch"])
            tilt = float(params["spec.tilt"])
            weights = np.asarray(
                [
                    harmonics[index] * 10.0 ** (tilt * math.log2(index + 1) / 20.0)
                    for index in range(partial_count)
                ],
                dtype=np.float64,
            )
            frequencies = fundamental * np.arange(1, partial_count + 1, dtype=np.float64) ** stretch
            audible = frequencies <= 0.45 * self.sample_rate
            weights = np.where(audible, weights, 0.0)
            weight_sum = float(np.sum(weights))
            centroid = float(np.dot(frequencies, weights) / weight_sum) if weight_sum else 0.0
            peak_index = int(np.argmax(weights)) if weight_sum else 0
            peak_frequency = float(frequencies[peak_index]) if weight_sum else 0.0
            return {
                "tables_ready": self._active_tables is not None,
                "tables_pending": self._pending_tables is not None or self._requested_state is not None,
                "table_generation": self._generation_count,
                "generation_error": self._generation_error or "",
                "note_frequency": self._last_note_frequency,
                "voice_rms": self._last_voice_rms,
                "spectrum_centroid_hz": centroid,
                "spectrum_peak_hz": peak_frequency,
            }

    def reset(self) -> None:
        if self._chorus is not None:
            self._chorus.reset()
        if self._delay is not None:
            self._delay.reset()
        if self._reverb is not None:
            self._reverb.reset()

    def close(self) -> None:
        with self._condition:
            if self._stop_worker:
                return
            self._stop_worker = True
            self._condition.notify_all()
            worker = self._thread
        if worker is not None and worker is not threading.current_thread():
            worker.join()
        with self._condition:
            self._thread = None
            self._requested_state = None
            self._pending_tables = None
            self._old_tables = None
            self._active_tables = None
            self._table_cache.clear()


def aurora_spec():
    """Construct the shared-shell specification for offline and later UI use."""
    from pathlib import Path

    from trio_kit.shell import InstrumentSpec

    return InstrumentSpec(
        identifier="aurora",
        name="AURORA",
        instrument_factory=AuroraInstrument,
        registry=aurora_registry(),
        factory_package="trio_aurora",
        factory_presets_dir=Path(__file__).resolve().parent / "data" / "presets",
        max_voices=8,
        extras_validator=validate_extras,
    )


__all__ = ["AuroraInstrument", "AuroraVoice", "aurora_spec"]
