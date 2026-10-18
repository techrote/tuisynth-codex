"""Seeded bounded granular air and formant instrument."""

from __future__ import annotations

from collections.abc import Mapping
import math

import numpy as np
from scipy.signal import lfilter

from trio_kit.dsp import Biquad, Lfo, Reverb, StereoDelay
from trio_kit.params import ParamSnapshot
from trio_drift.formant import FormantBank
from trio_drift.grain import Grain, GrainPool, poisson_arrivals
from trio_drift.params import WINDOWS, drift_registry
from trio_drift.voice import DriftVoice


_MAX_STREAMS = 6
_SOURCE_FADE_SECONDS = 0.05
_GUST_RAMP_SECONDS = 0.3
_VOWEL_SMOOTH_SECONDS = 0.02


def _rms_normalize(signal: np.ndarray, target: float = 0.25) -> np.ndarray:
    rms = float(np.sqrt(np.mean(np.square(signal, dtype=np.float64))))
    if rms <= 1e-12:
        return np.zeros_like(signal, dtype=np.float32)
    return np.asarray(signal * (target / rms), dtype=np.float32)


class DriftInstrument:
    """Six note streams drive a shared, capacity-bounded granular renderer."""

    legato_glide = True

    def __init__(self, *, seed: int = 0) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        self.seed = seed
        self.registry = drift_registry()
        self.sample_rate = 48_000
        self.block = 256
        self._params = ParamSnapshot(self.registry.defaults())
        self._pool = GrainPool(64)
        self._sources: dict[str, np.ndarray] | None = None
        self._old_sources: dict[str, np.ndarray] | None = None
        self._source_fade_position = 0
        self._source_fade_frames = 1
        self._source_color = math.nan
        self._source_regenerations = 0
        self._source_rng = np.random.default_rng(np.random.SeedSequence([seed, 0xD12F7]))
        self._wind_lfo = Lfo(self.sample_rate, rate=0.12, waveform="smooth_random", seed=seed ^ 0x71D0)
        self._wind_value = 0.0
        self._howl_rng = np.random.default_rng(np.random.SeedSequence([seed, 0xA017]))
        self._howl_filter: _HowlFilter | None = None
        self._formants = FormantBank(self.sample_rate)
        self._vowel_current = 0.0
        self._vowel_target = 0.0
        self._vowel_start = 0.0
        self._vowel_elapsed = 0
        self._vowel_smooth_frames = max(1, int(round(_VOWEL_SMOOTH_SECONDS * self.sample_rate)))
        self._vowel_dirty = True
        self._last_formant_vowel = math.nan
        self._brightness_filter: Biquad | None = None
        self._delay: StereoDelay | None = None
        self._reverb: Reverb | None = None
        self._block_serial = -1
        self._block_cursor = 0
        self._absolute_frame = 0
        self._gust_held = False
        self._gust_start = 0.0
        self._gust_target = 0.0
        self._gust_started_at = 0
        self._gust_ramp_frames = max(1, int(round(_GUST_RAMP_SECONDS * self.sample_rate)))
        self._last_voice_rms = 0.0
        self._closed = False

    @staticmethod
    def voice_limit(params: ParamSnapshot) -> int:
        """DRIFT uses exactly six note streams, independent of grain capacity."""
        return _MAX_STREAMS

    def set_engine_seed(self, seed: int) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("engine seed must be a non-negative integer")
        self.seed = seed
        self._source_rng = np.random.default_rng(np.random.SeedSequence([seed, 0xD12F7]))
        self._wind_lfo = Lfo(self.sample_rate, rate=0.12, waveform="smooth_random", seed=seed ^ 0x71D0)
        self._howl_rng = np.random.default_rng(np.random.SeedSequence([seed, 0xA017]))

    def prepare(self, sample_rate: int, block: int) -> None:
        if sample_rate not in (44_100, 48_000) or block != 256:
            raise ValueError("DRIFT requires 44.1/48 kHz and 256-frame blocks")
        if self._sources is not None:
            if self.sample_rate != sample_rate or self.block != block:
                raise RuntimeError("DRIFT cannot be prepared twice with different engine settings")
            return
        self.sample_rate = sample_rate
        self.block = block
        self._params = ParamSnapshot(self.registry.defaults())
        self._pool.set_capacity(int(self._params["gr.max"]))
        self._formants = FormantBank(sample_rate)
        self._vowel_smooth_frames = max(1, int(round(_VOWEL_SMOOTH_SECONDS * sample_rate)))
        self._gust_ramp_frames = max(1, int(round(_GUST_RAMP_SECONDS * sample_rate)))
        self._wind_lfo = Lfo(sample_rate, rate=float(self._params["wind.rate"]), waveform="smooth_random", seed=self.seed ^ 0x71D0)
        self._brightness_filter = Biquad(sample_rate, kind="highpass", cutoff=1_200.0, q=0.707)
        self._howl_filter = _HowlFilter(sample_rate, 1_200.0, 25.0)
        self._delay = StereoDelay(
            sample_rate,
            delay_seconds=float(self._params["fx.delay.time"]),
            feedback=float(self._params["fx.delay.feedback"]),
            mix=float(self._params["fx.delay.mix"]),
        )
        self._reverb = Reverb(
            sample_rate,
            size=float(self._params["fx.reverb.size"]),
            damp=float(self._params["fx.reverb.damp"]),
            mix=float(self._params["fx.reverb.mix"]),
        )
        self._source_color = float(self._params["src.color"])
        self._sources = self._generate_sources(self._source_color)
        self._source_regenerations = 1
        self._vowel_current = float(self._params["fmt.vowel"])
        self._vowel_target = self._vowel_current
        self._formants.configure(self._vowel_current, float(self._params["fmt.shift"]), float(self._params["fmt.q"]))

    def _generate_sources(self, color: float) -> dict[str, np.ndarray]:
        length = 2 * self.sample_rate
        white = self._source_rng.standard_normal(length)
        spectrum = np.fft.rfft(white)
        frequencies = np.fft.rfftfreq(length, 1.0 / self.sample_rate)
        safe_frequency = np.maximum(frequencies, 20.0)
        tilt = np.power(10.0, float(color) * 6.0 * np.log2(safe_frequency / 1_000.0) / 20.0)
        tilt[0] = 0.0
        noise = _rms_normalize(np.fft.irfft(spectrum * tilt, n=length))

        positions = np.arange(length, dtype=np.float64) / self.sample_rate
        phases = self._source_rng.uniform(0.0, 2.0 * math.pi, size=8)
        tone = np.zeros(length, dtype=np.float64)
        for harmonic, phase in enumerate(phases, start=1):
            frequency = 220.0 * harmonic
            if frequency < self.sample_rate * 0.45:
                tone += np.sin(2.0 * math.pi * frequency * positions + phase) / harmonic
        tone = _rms_normalize(tone)

        breath_filter = Biquad(self.sample_rate, kind="bandpass", cutoff=1_200.0, q=0.75)
        breath_b, breath_a = breath_filter.coefficients
        breath, _ = lfilter(breath_b, breath_a, white, zi=np.zeros(2, dtype=np.float64))
        breath = _rms_normalize(breath)
        return {"noise": noise, "tone": tone, "breath": breath}

    def create_voice(self, rng: np.random.Generator) -> DriftVoice:
        return DriftVoice(self, self.sample_rate, rng)

    def on_block_boundary(self, params: ParamSnapshot) -> None:
        self._params = params
        self._block_serial += 1
        self._block_cursor = 0
        self._pool.set_capacity(int(params["gr.max"]))
        color = float(params["src.color"])
        if color != self._source_color:
            self._old_sources = self._sources
            self._sources = self._generate_sources(color)
            self._source_color = color
            self._source_regenerations += 1
            self._source_fade_position = 0
            self._source_fade_frames = max(1, int(round(_SOURCE_FADE_SECONDS * self.sample_rate)))

        self._wind_lfo.set_rate(float(params["wind.rate"]))
        wind_block = self._wind_lfo.process(self.block)
        self._wind_value = float(np.mean(wind_block, dtype=np.float64))
        target = self._effective_vowel(params)
        if target != self._vowel_target:
            self._vowel_target = target
            self._vowel_start = self._vowel_current
            self._vowel_elapsed = 0
        advance = min(self.block, self._vowel_smooth_frames - self._vowel_elapsed)
        if advance > 0:
            self._vowel_elapsed += advance
            fraction = min(1.0, self._vowel_elapsed / self._vowel_smooth_frames)
            self._vowel_current = self._vowel_start + (self._vowel_target - self._vowel_start) * fraction
        if self._vowel_dirty or self._vowel_current != self._last_formant_vowel:
            self._formants.configure(self._vowel_current, float(params["fmt.shift"]), float(params["fmt.q"]))
            self._last_formant_vowel = self._vowel_current
            self._vowel_dirty = False
        else:
            # Shift and Q can change while the vowel itself remains fixed.
            self._formants.configure(self._vowel_current, float(params["fmt.shift"]), float(params["fmt.q"]))

    @staticmethod
    def _effective_vowel(params: ParamSnapshot) -> float:
        amount = float(params["field.amount"])
        return (1.0 - amount) * float(params["fmt.vowel"]) + amount * float(params["field.x"]) * 4.0

    @staticmethod
    def field_density_scale(field_y: float) -> float:
        return 0.25 + 3.75 * min(1.0, max(0.0, float(field_y)))

    def density_for(self, params: ParamSnapshot, held_gust: float) -> float:
        """Return the Poisson rate after field, wind, and held-gust controls."""
        held = min(1.0, max(0.0, float(held_gust)))
        effective_wind = min(1.0, float(params["wind.gust"]) + 0.5 * held)
        density = float(params["gr.density"]) * self.field_density_scale(float(params["field.y"]))
        density *= (1.0 + held) * (1.0 + effective_wind * 0.8 * self._wind_value)
        return max(0.0, density)

    def _gust_at(self, absolute_frame: int) -> float:
        if absolute_frame <= self._gust_started_at:
            return self._gust_start
        fraction = min(1.0, (absolute_frame - self._gust_started_at) / self._gust_ramp_frames)
        return self._gust_start + (self._gust_target - self._gust_start) * fraction

    def _schedule_voice(self, voice: DriftVoice, envelope: np.ndarray, params: ParamSnapshot) -> None:
        if voice._scheduled_block != self._block_serial:
            remaining = self.block - self._block_cursor
            held = self._gust_at(self._absolute_frame)
            density = self.density_for(params, held)
            voice._arrivals = poisson_arrivals(
                voice.rng,
                density,
                remaining,
                self.sample_rate,
                start_frame=self._block_cursor,
            )
            voice._arrival_cursor = 0
            voice._scheduled_block = self._block_serial

        segment_start = self._block_cursor
        segment_end = segment_start + len(envelope)
        while voice._arrival_cursor < len(voice._arrivals):
            arrival = voice._arrivals[voice._arrival_cursor]
            if arrival >= segment_end:
                break
            if arrival >= segment_start:
                absolute_start = self._absolute_frame + arrival - segment_start
                self._spawn_grain(voice, absolute_start, float(envelope[arrival - segment_start]), params)
            voice._arrival_cursor += 1

    def _spawn_grain(self, voice: DriftVoice, start_frame: int, envelope: float, params: ParamSnapshot) -> None:
        rng = voice.rng
        size_jitter = float(params["gr.size_jit"])
        duration_ms = float(params["gr.size"]) * (1.0 + size_jitter * float(rng.uniform(-0.5, 0.5)))
        duration_ms = min(500.0, max(5.0, duration_ms))
        length = max(2, int(round(duration_ms * self.sample_rate / 1_000.0)))
        field_position = (float(params["field.x"]) - 0.5) * float(params["field.amount"])
        position = (float(params["gr.pos"]) + field_position + float(params["gr.pos_scatter"]) * float(rng.uniform(-0.5, 0.5))) % 1.0
        frequency = 440.0 * (2.0 ** ((voice.pitch - 69.0) / 12.0))
        cents = float(params["gr.pitch_scatter"]) * float(rng.uniform(-1.0, 1.0))
        ratio = frequency / 220.0 * (2.0 ** (cents / 1_200.0))
        pan = min(1.0, max(0.0, 0.5 + float(params["gr.spread"]) * float(rng.uniform(-0.5, 0.5))))
        window = WINDOWS[int(params["gr.window"])]
        self._pool.spawn(Grain(start_frame, length, position, ratio, pan, voice.velocity * envelope, window))

    def _render_voice(self, voice: DriftVoice, envelope: np.ndarray, params: ParamSnapshot) -> None:
        self._schedule_voice(voice, envelope, params)

    def process_pre_fx(self, buffer: np.ndarray, params: ParamSnapshot) -> np.ndarray:
        samples = np.asarray(buffer, dtype=np.float32)
        if samples.ndim != 2 or samples.shape[1] != 2:
            raise ValueError("DRIFT bus expects stereo buffers")
        if len(samples) == 0:
            return np.zeros((0, 2), dtype=np.float32)
        if self._sources is None or self._formants is None:
            raise RuntimeError("DRIFT must be prepared by Engine before rendering")

        source_fade: np.ndarray | None = None
        if self._old_sources is not None:
            source_fade = np.clip(
                (self._source_fade_position + np.arange(len(samples), dtype=np.float64) + 1.0) / self._source_fade_frames,
                0.0,
                1.0,
            )
        grains = self._pool.render(
            len(samples),
            block_offset=self._absolute_frame,
            sample_rate=self.sample_rate,
            sources=self._sources,
            old_sources=self._old_sources,
            source_fade=source_fade,
            tone=float(params["src.tone"]),
            breath=float(params["src.breath"]),
        )
        grain_mix = samples + grains
        self._last_voice_rms = float(np.sqrt(np.mean(np.square(grains, dtype=np.float64))))

        held_gust = self._gust_at(self._absolute_frame)
        effective_wind = min(1.0, float(params["wind.gust"]) + 0.5 * held_gust)
        brightness_delta = min(0.4, max(-0.4, (float(params["field.y"]) - 0.5) * 0.5 + self._wind_value * effective_wind * 0.2))
        if self._brightness_filter is not None and brightness_delta != 0:
            bright = self._brightness_filter.process(grain_mix)
            grain_mix = grain_mix + (bright - grain_mix) * brightness_delta
        formant = self._formants.process(grain_mix, float(params["fmt.mix"]))

        howl_amount = float(params["wind.howl"])
        if howl_amount > 0 and self._howl_filter is not None:
            center = 600.0 + min(1.0, max(0.0, (self._wind_value + 1.0) * 0.5)) * 1_900.0
            self._howl_filter.set_parameters(center, 25.0)
            noise = self._howl_rng.standard_normal((len(samples), 2)).astype(np.float64)
            formant = formant + (self._howl_filter.process(noise) * (0.04 * howl_amount)).astype(np.float32)

        return formant.astype(np.float32, copy=False)

    def process_fx_unit(self, name: str, buffer: np.ndarray, params: ParamSnapshot) -> np.ndarray:
        samples = np.asarray(buffer, dtype=np.float32)
        if name == "delay" and self._delay is not None:
            self._delay.set_parameters(delay_seconds=float(params["fx.delay.time"]), feedback=float(params["fx.delay.feedback"]), mix=float(params["fx.delay.mix"]))
            return self._delay.process(samples)
        if name == "reverb" and self._reverb is not None:
            self._reverb.set_parameters(size=float(params["fx.reverb.size"]), damp=float(params["fx.reverb.damp"]), mix=float(params["fx.reverb.mix"]))
            return self._reverb.process(samples)
        return samples

    def process_post_fx(self, buffer: np.ndarray, params: ParamSnapshot) -> np.ndarray:
        formant = np.asarray(buffer, dtype=np.float32)
        if formant.ndim != 2 or formant.shape[1] != 2:
            raise ValueError("DRIFT bus expects stereo buffers")
        if len(formant) == 0:
            return formant
        effected = formant
        drive = float(params["master.drive"])
        if drive > 0:
            shaped = np.tanh(effected * (1.0 + 9.0 * drive)) / math.tanh(1.0 + 9.0 * drive)
            effected = effected * (1.0 - drive) + shaped * drive
        output = (effected * float(params["master.level"])).astype(np.float32)

        if self._old_sources is not None:
            self._source_fade_position += len(formant)
            if self._source_fade_position >= self._source_fade_frames:
                self._old_sources = None
        self._block_cursor += len(formant)
        self._absolute_frame += len(formant)
        return output

    def process_bus(self, buffer: np.ndarray, params: ParamSnapshot) -> np.ndarray:
        """Compatibility wrapper retaining the original bus entry point."""
        pre = self.process_pre_fx(buffer, params)
        if len(pre) == 0:
            return pre
        pre = self.process_fx_unit("delay", pre, params)
        pre = self.process_fx_unit("reverb", pre, params)
        return self.process_post_fx(pre, params)

    def set_gust_held(self, held: bool) -> None:
        if not isinstance(held, bool):
            raise ValueError("held must be a boolean")
        if held == self._gust_held:
            return
        self._gust_start = self._gust_at(self._absolute_frame)
        self._gust_target = 1.0 if held else 0.0
        self._gust_started_at = self._absolute_frame
        self._gust_held = held

    def on_event(self, name: str, payload: tuple[float | int | str, ...]) -> None:
        if name in {"gust", "gust_on", "gust_off"}:
            if name == "gust_on":
                self.set_gust_held(True)
            elif name == "gust_off":
                self.set_gust_held(False)
            elif payload:
                value = payload[0]
                if isinstance(value, str):
                    held = value.strip().lower() in {"1", "true", "on", "yes"}
                else:
                    held = float(value) >= 0.5
                self.set_gust_held(held)

    def get_extras(self) -> dict[str, object]:
        return {}

    def set_extras(self, extras: Mapping[str, object]) -> None:
        if extras:
            raise ValueError("DRIFT has no instrument-specific preset extras")

    def telemetry(self) -> Mapping[str, object]:
        grains = self._pool.grain_snapshot
        return {
            "active_grains": len(grains),
            "spawned_grains": self._pool.spawned,
            "dropped_grains": self._pool.dropped,
            "grain_density": float(self._params["gr.density"]),
            "field_x": float(self._params["field.x"]),
            "field_y": float(self._params["field.y"]),
            "vowel": float(self._vowel_current),
            "wind": float(self._wind_value),
            "gust": float(self._gust_at(self._absolute_frame)),
            "source_color": float(self._source_color) if math.isfinite(self._source_color) else 0.0,
            "source_regenerations": self._source_regenerations,
            "voice_rms": self._last_voice_rms,
            "grain_pan": tuple(grain.pan for grain in grains),
            "grain_ratio": tuple(grain.ratio for grain in grains),
            "grain_amplitude": tuple(grain.amplitude for grain in grains),
            "grain_age": tuple(min(1.0, max(0.0, (self._absolute_frame - grain.start_frame) / grain.length)) for grain in grains),
        }

    def reset(self) -> None:
        self._pool.grains.clear()
        self._formants.reset()
        if self._brightness_filter is not None:
            self._brightness_filter.reset()
        if self._howl_filter is not None:
            self._howl_filter.reset()
        if self._delay is not None:
            self._delay.reset()
        if self._reverb is not None:
            self._reverb.reset()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.reset()


class _HowlFilter:
    """Narrow Q=25 band-pass for the seeded, drifting wind howl."""

    def __init__(self, sample_rate: int, cutoff: float, q: float) -> None:
        self.sample_rate = sample_rate
        self.q = q
        self.cutoff = cutoff
        self._coefficients = self._design(cutoff)
        self._zi = np.zeros((2, 2), dtype=np.float64)

    def _design(self, cutoff: float) -> tuple[np.ndarray, np.ndarray]:
        omega = 2.0 * math.pi * min(cutoff, 0.45 * self.sample_rate) / self.sample_rate
        alpha = math.sin(omega) / (2.0 * self.q)
        cosine = math.cos(omega)
        a0 = 1.0 + alpha
        return (
            np.asarray((alpha / a0, 0.0, -alpha / a0), dtype=np.float64),
            np.asarray((1.0, -2.0 * cosine / a0, (1.0 - alpha) / a0), dtype=np.float64),
        )

    def set_parameters(self, cutoff: float, q: float) -> None:
        if cutoff == self.cutoff and q == self.q:
            return
        self.cutoff = float(cutoff)
        self.q = float(q)
        self._coefficients = self._design(self.cutoff)

    def process(self, noise: np.ndarray) -> np.ndarray:
        result, self._zi = lfilter(*self._coefficients, noise, axis=0, zi=self._zi)
        return result

    def reset(self) -> None:
        self._zi.fill(0.0)


__all__ = ["DriftInstrument"]
