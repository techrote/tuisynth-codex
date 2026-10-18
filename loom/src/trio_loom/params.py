"""LOOM parameter registry shared by its DSP, CLI, presets, and later UI."""

from __future__ import annotations

from trio_kit.params import ParamRegistry, ParamSpec


def loom_registry() -> ParamRegistry:
    """Return a fresh registry containing every parameter consumed by LOOM."""
    specs = (
        ParamSpec("play.mode", "Play mode", "", 0, 1, 0, kind="choice", choices=("direct", "chord"), group="Play"),
        ParamSpec("exc.mode", "Excitation", "", 0, 1, 0, kind="choice", choices=("pluck", "bow"), group="Excite"),
        ParamSpec("exc.hardness", "Hardness", "", 0, 1, 0.55, modulatable=True, modulation_scope="voice", group="Excite"),
        ParamSpec("exc.pressure", "Bow pressure", "", 0, 1, 0.5, modulatable=True, modulation_scope="voice", group="Excite"),
        ParamSpec("exc.speed", "Bow speed", "", 0, 1, 0.7, modulatable=True, modulation_scope="voice", group="Excite"),
        ParamSpec("exc.noise", "Bow rosin noise", "", 0, 1, 0.3, modulatable=True, modulation_scope="voice", group="Excite"),
        ParamSpec("str.decay", "String decay", "s", 0.2, 30, 6, curve="log", modulatable=True, modulation_scope="voice", group="String"),
        ParamSpec("str.release", "String release", "s", 0.05, 5, 0.4, curve="log", modulatable=True, modulation_scope="voice", group="String"),
        ParamSpec("str.bright", "Brightness", "", 0, 1, 0.6, modulatable=True, modulation_scope="voice", group="String"),
        ParamSpec("str.pickpos", "Pick position", "", 0.02, 0.5, 0.13, modulatable=True, modulation_scope="voice", group="String"),
        ParamSpec("sym.mix", "Sympathetic mix", "", 0, 1, 0.3, modulatable=True, group="Sympathetic"),
        ParamSpec("sym.couple", "Sympathetic coupling", "", 0, 1, 0.4, modulatable=True, group="Sympathetic"),
        ParamSpec("sym.decay", "Sympathetic decay", "s", 0.5, 40, 12, curve="log", modulatable=True, group="Sympathetic"),
        ParamSpec("sym.tuning", "Sympathetic tuning", "", 0, 2, 0, kind="choice", choices=("scale", "drone", "chord"), group="Sympathetic"),
        ParamSpec("sym.scale", "Sympathetic scale", "", 0, 5, 2, kind="choice", choices=("major", "minor", "dorian", "pentatonic", "bhairav", "hijaz"), group="Sympathetic"),
        ParamSpec("sym.root", "Sympathetic root", "semitones", 0, 11, 2, kind="discrete", group="Sympathetic"),
        ParamSpec("body.type", "Body", "", 0, 5, 1, kind="choice", choices=("none", "guitar", "violin", "cello", "harp", "sitar"), group="Body"),
        ParamSpec("body.mix", "Body mix", "", 0, 1, 0.5, modulatable=True, group="Body"),
        ParamSpec("body.size", "Body size", "", 0.5, 2, 1, group="Body"),
        ParamSpec("strum.strings", "Strings", "", 4, 12, 8, kind="discrete", group="Play"),
        ParamSpec("strum.spread", "Strum spread", "ms", 0, 80, 18, group="Play"),
        ParamSpec("fx.reverb.size", "Reverb size", "", 0.2, 1.6, 0.7, curve="log", modulatable=True, group="Space"),
        ParamSpec("fx.reverb.damp", "Reverb damping", "", 0, 1, 0.5, modulatable=True, group="Space"),
        ParamSpec("fx.reverb.mix", "Reverb mix", "", 0, 1, 0.25, modulatable=True, group="Space"),
        ParamSpec("master.level", "Master level", "", 0, 1, 0.8, group="Master"),
        ParamSpec("master.drive", "Master drive", "", 0, 1, 0.05, group="Master"),
    )
    return ParamRegistry(specs)


__all__ = ["loom_registry"]
