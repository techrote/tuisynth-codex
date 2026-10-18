"""DRIFT's complete instrument-owned parameter surface."""

from __future__ import annotations

from trio_kit.params import ParamRegistry, ParamSpec


WINDOWS = ("hann", "tukey", "expodec", "rexpodec")


def drift_registry() -> ParamRegistry:
    """Return a fresh registry for all DRIFT engine and shared controls."""
    return ParamRegistry((
        ParamSpec("src.color", "Source colour", "", -1, 1, -0.2, group="Source"),
        ParamSpec("src.tone", "Soft tone", "", 0, 1, 0.35, modulatable=True, group="Source"),
        ParamSpec("src.breath", "Breath", "", 0, 1, 0.2, modulatable=True, group="Source"),
        ParamSpec("gr.density", "Grains per second", "grains/s", 1, 200, 35, curve="log", modulatable=True, modulation_scope="both", group="Grain"),
        ParamSpec("gr.size", "Grain size", "ms", 5, 500, 90, curve="log", modulatable=True, modulation_scope="both", group="Grain"),
        ParamSpec("gr.size_jit", "Size scatter", "", 0, 1, 0.3, group="Grain"),
        ParamSpec("gr.pos", "Source position", "", 0, 1, 0.5, modulatable=True, modulation_scope="both", group="Grain"),
        ParamSpec("gr.pos_scatter", "Position scatter", "", 0, 1, 0.4, group="Grain"),
        ParamSpec("gr.spread", "Stereo spread", "", 0, 1, 0.7, modulatable=True, modulation_scope="both", group="Grain"),
        ParamSpec("gr.pitch_scatter", "Pitch scatter", "cents", 0, 1200, 12, group="Grain"),
        ParamSpec("gr.window", "Grain window", "", 0, 3, 0, kind="choice", choices=WINDOWS, group="Grain"),
        ParamSpec("gr.max", "Maximum grains", "", 16, 96, 64, kind="discrete", group="Grain"),
        ParamSpec("fmt.vowel", "Vowel", "", 0, 4, 0, group="Formant"),
        ParamSpec("fmt.shift", "Formant shift", "", 0.6, 1.5, 1.0, group="Formant"),
        ParamSpec("fmt.q", "Formant Q", "", 0.3, 3, 1.0, group="Formant"),
        ParamSpec("fmt.mix", "Formant mix", "", 0, 1, 0.7, group="Formant"),
        ParamSpec("field.x", "Field X", "", 0, 1, 0.0, modulatable=True, modulation_scope="both", group="Field"),
        ParamSpec("field.y", "Field Y", "", 0, 1, 0.5, modulatable=True, modulation_scope="both", group="Field"),
        ParamSpec("field.amount", "Field amount", "", 0, 1, 0.8, modulatable=True, modulation_scope="both", group="Field"),
        ParamSpec("wind.gust", "Wind gust", "", 0, 1, 0.3, modulatable=True, modulation_scope="both", group="Wind"),
        ParamSpec("wind.howl", "Howl", "", 0, 1, 0.1, modulatable=True, group="Wind"),
        ParamSpec("wind.rate", "Wind rate", "Hz", 0.01, 2, 0.12, curve="log", group="Wind"),
        ParamSpec("amp.a", "Attack", "s", 0.001, 20, 0.6, curve="log", modulatable=True, modulation_scope="both", group="Amplitude"),
        ParamSpec("amp.d", "Decay", "s", 0.01, 20, 0.8, curve="log", modulatable=True, modulation_scope="both", group="Amplitude"),
        ParamSpec("amp.s", "Sustain", "", 0, 1, 0.8, modulatable=True, modulation_scope="both", group="Amplitude"),
        ParamSpec("amp.r", "Release", "s", 0.01, 30, 2.5, curve="log", modulatable=True, modulation_scope="both", group="Amplitude"),
        ParamSpec("fx.reverb.size", "Reverb size", "", 0.2, 1.6, 0.9, curve="log", modulatable=True, group="Space"),
        ParamSpec("fx.reverb.mix", "Reverb", "", 0, 1, 0.3, modulatable=True, group="Space"),
        ParamSpec("fx.reverb.damp", "Reverb damping", "", 0, 1, 0.4, modulatable=True, group="Space"),
        ParamSpec("fx.delay.time", "Delay time", "s", 0.06, 2, 0.5, curve="log", modulatable=True, group="Space"),
        ParamSpec("fx.delay.feedback", "Delay feedback", "", 0, 0.9, 0.3, modulatable=True, group="Space"),
        ParamSpec("fx.delay.mix", "Delay", "", 0, 1, 0.2, modulatable=True, group="Space"),
        ParamSpec("master.level", "Master level", "", 0, 1, 0.75, group="Master"),
        ParamSpec("master.drive", "Master drive", "", 0, 1, 0, group="Master"),
    ))


__all__ = ["WINDOWS", "drift_registry"]
