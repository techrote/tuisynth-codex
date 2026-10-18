from __future__ import annotations

import time

import numpy as np
import pytest

from trio_aurora.instrument import AuroraInstrument, aurora_spec
from trio_aurora.padsynth import table_set_key
from trio_kit.engine import OfflineEngine
from trio_kit.events import NoteOff, NoteOn, Panic, ParamSet


def _start_tables(engine: OfflineEngine) -> None:
    instrument = engine.instrument
    instrument.wait_for_regeneration(timeout=60)
    engine.render(1)
    engine.render(engine.block - 1)
    instrument.wait_for_regeneration(timeout=60, active=True)


def test_background_regeneration_is_debounced_swapped_at_boundaries_and_joined() -> None:
    instrument = AuroraInstrument()
    engine = OfflineEngine(instrument, sample_rate=44_100, max_voices=8, registry=instrument.registry)
    try:
        profile_a = [1.0] + [0.0] * 63
        profile_b = [0.0, 1.0] + [0.0] * 62
        instrument.set_extras({"harmonics": profile_a})
        instrument.wait_for_regeneration(timeout=60)
        assert instrument._pending_tables is not None
        instrument.set_extras({"harmonics": profile_b})
        instrument.wait_for_regeneration(timeout=60)
        expected_key = table_set_key(44_100, instrument.registry.defaults(), profile_b)
        assert instrument._pending_tables is not None
        assert instrument._pending_tables.key == expected_key
        assert instrument.telemetry()["table_generation"] <= 3
        engine.render(1)
        engine.render(engine.block - 1)
        instrument.wait_for_regeneration(timeout=60, active=True)
        assert instrument._active_tables is not None
        assert instrument._active_tables.zones[0].left.flags.writeable is False

        engine.push(NoteOn(1, 60, 0.8, "test"))
        before = engine.render(1_024)
        instrument.set_extras({"harmonics": [0.5, 0.0, 0.5] + [0.0] * 61})
        instrument.wait_for_regeneration(timeout=60)
        # The completed table cannot become visible until the next whole block.
        old_key = instrument._active_tables.key
        swapped_block = engine.render(engine.block)
        assert np.max(np.abs(swapped_block[0] - before[-1])) <= 0.2
        tail = engine.render(3_072)
        instrument.wait_for_regeneration(timeout=60, active=True)
        joined = np.concatenate((before, tail), axis=0)
        assert np.isfinite(joined).all()
        assert np.max(np.abs(joined), initial=0.0) <= 0.950001
        assert instrument._active_tables is not None and instrument._active_tables.key != old_key
        assert instrument._old_tables is None
        assert len(instrument._table_cache) <= 2
        telemetry = engine.telemetry().instrument
        assert telemetry["spectrum_centroid_hz"] > 0
        assert telemetry["spectrum_peak_hz"] > 0
        assert telemetry["voice_rms"] >= 0
        assert telemetry["voice_envelope_sum"] > 0
        assert 0 <= telemetry["voice_lfo_level"] <= 1
        assert len(telemetry["table_magnitude"]) == 64
        assert max(telemetry["table_magnitude"]) == pytest.approx(1.0)
    finally:
        engine.close()
    assert instrument._thread is None


def test_pitch_tracking_stereo_width_filter_modes_and_envelope_release() -> None:
    instrument = AuroraInstrument()
    initial = {
        "amp.a": 0.002,
        "amp.d": 0.01,
        "amp.s": 0.8,
        "amp.r": 0.05,
        "osc.detune": 0,
        "osc.width": 1,
        "flt.cut": 12_000,
        "fx.chorus.mix": 0,
        "fx.delay.mix": 0,
        "fx.reverb.mix": 0,
        "master.level": 1,
        "master.drive": 0,
    }
    engine = OfflineEngine(instrument, sample_rate=48_000, max_voices=8, registry=instrument.registry, initial_params=initial)
    try:
        _start_tables(engine)
        measured: dict[int, np.ndarray] = {}
        for note_id, pitch in enumerate((36, 60, 84), start=1):
            engine.push(Panic())
            engine.push(NoteOn(note_id, pitch, 0.8, "pitch-test"))
            rendered = engine.render(48_000)
            measured[pitch] = rendered
            assert np.isfinite(rendered).all()
        frequencies = np.fft.rfftfreq(48_000, d=1 / 48_000)
        for pitch, rendered in measured.items():
            spectrum = np.abs(np.fft.rfft(rendered[:, 0].astype(np.float64)))
            target = 440.0 * 2.0 ** ((pitch - 69.0) / 12.0)
            window = (frequencies >= target * 0.98) & (frequencies <= target * 1.02)
            assert window.any()
            measured_peak = frequencies[window][np.argmax(spectrum[window])]
            # PADsynth deliberately paints a bounded bandwidth around each
            # partial, so validate the carrier within that spectral spread.
            assert measured_peak == pytest.approx(target, rel=0.025)

        wide = measured[60]
        assert np.corrcoef(wide[4_096:, 0], wide[4_096:, 1])[0, 1] < 0.5

        engine.push(Panic())
        engine.push(ParamSet("osc.width", 0))
        engine.push(NoteOn(10, 60, 0.8, "width-test"))
        narrow = engine.render(48_000)
        assert np.corrcoef(narrow[4_096:, 0], narrow[4_096:, 1])[0, 1] > 0.99

        engine.push(Panic())
        engine.push(ParamSet("flt.mode", 0))
        engine.push(ParamSet("flt.cut", 1_200))
        engine.push(NoteOn(11, 48, 0.8, "filter-test"))
        lowpass = engine.render(16_384)
        engine.push(Panic())
        engine.push(ParamSet("flt.mode", 2))
        engine.push(NoteOn(12, 48, 0.8, "filter-test"))
        highpass = engine.render(16_384)
        assert np.sqrt(np.mean(highpass[4_096:] ** 2)) < np.sqrt(np.mean(lowpass[4_096:] ** 2))
        engine.push(Panic())
        engine.push(ParamSet("flt.mode", 1))
        engine.push(NoteOn(13, 48, 0.8, "filter-test"))
        bandpass = engine.render(16_384)
        assert not np.allclose(bandpass[4_096:], lowpass[4_096:])
        assert not np.allclose(bandpass[4_096:], highpass[4_096:])

        engine.push(Panic())
        engine.push(ParamSet("flt.mode", 2))
        engine.push(NoteOn(14, 48, 0.8, "release-test"))
        held = engine.render(16_384)
        engine.push(NoteOff(14))
        released = engine.render(16_384)
        assert np.sqrt(np.mean(released[-4_096:] ** 2)) < np.sqrt(np.mean(held[-4_096:] ** 2)) * 0.15

        engine.push(Panic())
        engine.push(ParamSet("osc.width", 1))
        engine.push(ParamSet("lfo.depth", 0))
        engine.push(NoteOn(20, 60, 0.8, "lfo-test"))
        baseline = engine.render(8_192)
        for target in range(4):
            engine.push(Panic())
            engine.push(ParamSet("lfo.rate", 5))
            engine.push(ParamSet("lfo.depth", 1))
            engine.push(ParamSet("lfo.wave", 0))
            engine.push(ParamSet("lfo.tgt", target))
            engine.push(NoteOn(21 + target, 60, 0.8, "lfo-test"))
            modulated = engine.render(8_192)
            assert np.isfinite(modulated).all()
            assert not np.allclose(modulated[1_024:], baseline[1_024:])
    finally:
        engine.close()


def test_eight_voice_dense_render_is_finite_and_bounded() -> None:
    spec = aurora_spec()
    engine = OfflineEngine(
        spec.instrument_factory(),
        sample_rate=48_000,
        max_voices=spec.max_voices,
        registry=spec.registry,
    )
    try:
        _start_tables(engine)
        for key, value in (
            ("spec.count", 2),
            ("spec.bw", 300),
            ("spec.bwscale", 1.8),
            ("spec.noise", 0.35),
            ("amp.a", 0.01),
            ("fx.reverb.mix", 0.0),
            ("fx.delay.mix", 0.0),
            ("fx.chorus.mix", 0.0),
        ):
            engine.push(ParamSet(key, value))
        engine.push(NoteOn(1, 48, 0.8, "bench"))
        engine.push(NoteOn(2, 52, 0.8, "bench"))
        engine.push(NoteOn(3, 55, 0.8, "bench"))
        engine.push(NoteOn(4, 60, 0.8, "bench"))
        engine.push(NoteOn(5, 64, 0.8, "bench"))
        engine.push(NoteOn(6, 67, 0.8, "bench"))
        engine.push(NoteOn(7, 72, 0.8, "bench"))
        engine.push(NoteOn(8, 76, 0.8, "bench"))
        # Allow the 64-partial spectral request to settle before measuring voice DSP.
        engine.render(1)
        engine.render(engine.block - 1)
        instrument = engine.instrument
        instrument.wait_for_regeneration(timeout=60)
        engine.render(1)
        engine.render(engine.block - 1)
        engine.render(3_072)
        instrument.wait_for_regeneration(timeout=60, active=True)
        started = time.perf_counter()
        result = engine.render(48_000)
        elapsed = time.perf_counter() - started
        assert elapsed < 15.0
        assert result.shape == (48_000, 2)
        assert np.isfinite(result).all()
        assert engine.telemetry().active_voices == 8
    finally:
        engine.close()
