"""Validated semantic skins and safe terminal art assets."""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias

from wcwidth import wcswidth

from trio_kit.userdata import get_user_data_dir


SKIN_SCHEMA = "md-editor-theme/1.1"
MAX_SKIN_BYTES = 128 * 1024
MAX_NESTING = 4
MAX_ART_LINES = 40
MAX_ART_COLUMNS = 160
MAX_GLYPHS = 16
MAX_RAMP_STOPS = 16
_SKIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_INSTRUMENT_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_FRAME_STYLES = frozenset({"round", "square", "heavy", "double", "ascii"})
_STYLE_ATTRIBUTES = frozenset({"fg", "bg", "bold", "italic", "underline", "reverse"})
_GLYPH_TABLE_ATTRIBUTES = frozenset({"symbols", "on", "off"})
_KNOWN_TOP_LEVEL = frozenset(
    {
        "schema",
        "id",
        "name",
        "instrument",
        "fps",
        "palette",
        "styles",
        "glyphs",
        "ramps",
        "art",
        "fallbacks",
        # Historical metadata/sections accepted but intentionally not rendered here.
        "description",
        "seed",
        "seed_mode",
        "geometry",
    }
)
_ROLE_ALIASES = {
    "status_ok": "status",
    "status_warn": "warning",
    "status_err": "error",
    "sel": "selected",
    "focus": "focused",
    "press": "pressed",
}

REQUIRED_ROLES = (
    "background",
    "text",
    "muted",
    "border",
    "title",
    "heading",
    "accent",
    "status",
    "warning",
    "error",
    "focused",
    "hover",
    "pressed",
    "selected",
    "disabled",
    "key_white",
    "key_black",
    "key_pressed",
    "meter_low",
    "meter_mid",
    "meter_high",
)

_ColorMap: TypeAlias = Mapping[str, str]
_Glyph: TypeAlias = str | tuple[str, ...] | Mapping[str, object]


def _is_hex_color(value: object) -> bool:
    return isinstance(value, str) and _COLOR_RE.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class Style:
    """A semantic role's resolved foreground, background, and text attributes."""

    fg: str | None = None
    bg: str | None = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    reverse: bool = False

    def __post_init__(self) -> None:
        for name in ("fg", "bg"):
            color = getattr(self, name)
            if color is not None and not _is_hex_color(color):
                raise ValueError(f"{name} must be a resolved #rrggbb color or None")
        for name in ("bold", "italic", "underline", "reverse"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a boolean")

    def as_prompt_toolkit(self, *, colors: bool = True) -> str:
        """Return a prompt_toolkit style fragment for the validated role."""
        parts: list[str] = []
        if colors:
            if self.fg is not None:
                parts.append(f"fg:{self.fg}")
            if self.bg is not None:
                parts.append(f"bg:{self.bg}")
        for name in ("bold", "italic", "underline", "reverse"):
            if getattr(self, name):
                parts.append(name)
        return " ".join(parts)


@dataclass(frozen=True, slots=True)
class Skin:
    """Immutable, validated data used by layouts and terminal renderers."""

    id: str
    name: str
    instrument: str
    fps: int
    palette: _ColorMap
    styles: Mapping[str, Style]
    glyphs: Mapping[str, _Glyph]
    ramps: Mapping[str, tuple[str, ...]]
    art: Mapping[str, tuple[str, ...]]
    fallbacks: Mapping[str, object]
    schema: str = SKIN_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _SKIN_ID_RE.fullmatch(self.id):
            raise ValueError("skin id must match ^[a-z0-9][a-z0-9-]{0,31}$")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("skin name must be a non-empty string")
        if not isinstance(self.instrument, str) or not (
            self.instrument == "any" or _INSTRUMENT_RE.fullmatch(self.instrument)
        ):
            raise ValueError("instrument must be 'any' or a lowercase instrument id")
        if isinstance(self.fps, bool) or not isinstance(self.fps, int) or not 1 <= self.fps <= 60:
            raise ValueError("fps must be an integer in the range 1..60")
        for field_name in ("palette", "styles", "glyphs", "ramps", "art", "fallbacks"):
            value = getattr(self, field_name)
            if not isinstance(value, Mapping):
                raise ValueError(f"{field_name} must be a mapping")
            object.__setattr__(self, field_name, _freeze_mapping(value))
        if "text" not in self.styles or not isinstance(self.styles["text"], Style):
            raise ValueError("skin styles must include a text Style")

    def style(self, role: str) -> Style:
        """Resolve a semantic role, falling back to the safe text style."""
        if not isinstance(role, str):
            return self.styles["text"]
        return self.styles.get(role, self.styles["text"])

    def ramp(self, name: str) -> tuple[str, ...]:
        """Return a color ramp, or an empty tuple for an unknown ramp."""
        return self.ramps.get(name, ()) if isinstance(name, str) else ()

    def glyph(self, name: str, *, on: bool = False) -> str:
        """Resolve a named glyph set to its active/on or inactive/off symbol."""
        value = self.glyphs.get(name) if isinstance(name, str) else None
        if isinstance(value, str):
            return value
        if isinstance(value, tuple):
            if not value:
                return " "
            return value[-1] if on else value[0]
        if isinstance(value, Mapping):
            state = value.get("on" if on else "off")
            if isinstance(state, str):
                return state
            symbols = value.get("symbols")
            if isinstance(symbols, tuple) and symbols:
                return symbols[-1] if on else symbols[0]
        return " "

    def art_block(self, name: str) -> tuple[str, ...]:
        """Return validated art rows, or no rows when the name is unknown."""
        return self.art.get(name, ()) if isinstance(name, str) else ()

    @property
    def ascii_glyphs(self) -> Mapping[str, _Glyph]:
        """Return explicit ASCII fallback glyphs when the skin defines them."""
        fallback = self.fallbacks.get("ascii")
        if isinstance(fallback, Mapping):
            glyphs = fallback.get("glyphs")
            if isinstance(glyphs, Mapping):
                return glyphs
        return MappingProxyType({})


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze(item) for key, item in value.items()})


def _mono_skin() -> Skin:
    black, white, gray = "#000000", "#ffffff", "#888888"
    palette = {"black": black, "white": white, "gray": gray}
    text = Style(fg=white, bg=black)
    styles = {
        "background": text,
        "text": text,
        "muted": Style(fg=gray, bg=black),
        "border": Style(fg=gray, bg=black),
        "title": Style(fg=white, bg=black, bold=True),
        "heading": Style(fg=white, bg=black, bold=True),
        "accent": Style(fg=white, bg=black, bold=True),
        "status": text,
        "warning": Style(fg=white, bg=black, bold=True),
        "error": Style(fg=white, bg=black, bold=True),
        "focused": Style(fg=black, bg=white, bold=True),
        "hover": Style(fg=black, bg=white),
        "pressed": Style(fg=black, bg=white, bold=True),
        "selected": Style(fg=black, bg=white, bold=True),
        "disabled": Style(fg=gray, bg=black),
        "key_white": Style(fg=white, bg=black),
        "key_black": Style(fg=gray, bg=black),
        "key_pressed": Style(fg=black, bg=white, bold=True),
        "meter_low": Style(fg=gray, bg=black),
        "meter_mid": text,
        "meter_high": Style(fg=white, bg=black, bold=True),
    }
    density = (" ", ".", ":", "-", "=", "+", "*", "#", "%", "@")
    ascii_density = (" ", ".", ":", "+", "#")
    return Skin(
        id="mono",
        name="MONO",
        instrument="any",
        fps=24,
        palette=palette,
        styles=styles,
        glyphs={"density": density, "frame": "ascii"},
        ramps={"mono": (black, "#555555", gray, white)},
        art={"logo": ("TRIO / MONO",)},
        fallbacks={
            "ascii": {
                "glyphs": {"density": ascii_density, "frame": "ascii"},
            }
        },
    )


_MONO_SKIN = _mono_skin()


def mono_skin() -> Skin:
    """Return the immutable guaranteed-safe, ASCII-art mono skin."""
    return _MONO_SKIN


def _source_bytes(source: object) -> tuple[bytes | None, str]:
    label = "<skin>"
    if isinstance(source, Path):
        label = str(source)
        with source.expanduser().open("rb") as stream:
            return stream.read(MAX_SKIN_BYTES + 1), label
    if isinstance(source, os.PathLike):
        path = Path(source).expanduser()
        label = str(path)
        with path.open("rb") as stream:
            return stream.read(MAX_SKIN_BYTES + 1), label
    if isinstance(source, (bytes, bytearray, memoryview)):
        source_size = source.nbytes if isinstance(source, memoryview) else len(source)
        if source_size > MAX_SKIN_BYTES:
            return b"\x00" * (MAX_SKIN_BYTES + 1), label
        return bytes(source), label
    if isinstance(source, str):
        label = "<skin text>"
        if len(source) > MAX_SKIN_BYTES:
            return b"\x00" * (MAX_SKIN_BYTES + 1), label
        if "\n" not in source and "\r" not in source:
            try:
                path = Path(source).expanduser()
                if path.is_file():
                    label = str(path)
                    with path.open("rb") as stream:
                        return stream.read(MAX_SKIN_BYTES + 1), label
            except (OSError, ValueError):
                pass
        return source.encode("utf-8"), label
    raise TypeError("skin source must be TOML text, bytes, or a path")


def _container_depth_exceeded(value: object, *, max_depth: int = MAX_NESTING) -> bool:
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        if not isinstance(current, (dict, list, tuple)):
            continue
        if depth > max_depth:
            return True
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        else:
            stack.extend((item, depth + 1) for item in current)
    return False


def _valid_name(value: object) -> bool:
    return isinstance(value, str) and _NAME_RE.fullmatch(value) is not None


def _warn(warnings: list[str], message: str) -> None:
    warnings.append(message)


def _resolve_color(value: object, palette: Mapping[str, str]) -> str | None:
    if _is_hex_color(value):
        return value.lower()
    if isinstance(value, str):
        return palette.get(value)
    return None


def _single_cell_glyph(value: object, *, ascii_only: bool = False) -> bool:
    if not isinstance(value, str) or not value or not all(character.isprintable() for character in value):
        return False
    if ascii_only and any(ord(character) > 0x7F for character in value):
        return False
    return wcswidth(value) == 1


def _parse_glyph_entry(
    name: str,
    value: object,
    warnings: list[str],
    *,
    ascii_only: bool = False,
) -> _Glyph | None:
    if name == "frame":
        if isinstance(value, str) and value in _FRAME_STYLES and (not ascii_only or value == "ascii"):
            return value
        allowed = "ascii" if ascii_only else ", ".join(sorted(_FRAME_STYLES))
        _warn(warnings, f"glyphs.{name} must be {allowed}; using ascii")
        return "ascii"
    if isinstance(value, str):
        if _single_cell_glyph(value, ascii_only=ascii_only):
            return value
        _warn(warnings, f"glyphs.{name} must be a printable single-cell glyph; ignored")
        return None
    if isinstance(value, list):
        if not 2 <= len(value) <= MAX_GLYPHS or any(
            not _single_cell_glyph(glyph, ascii_only=ascii_only) for glyph in value
        ):
            _warn(warnings, f"glyphs.{name} must contain 2..{MAX_GLYPHS} printable single-cell glyphs; ignored")
            return None
        return tuple(value)
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, glyph in value.items():
            if key not in _GLYPH_TABLE_ATTRIBUTES:
                _warn(warnings, f"unknown glyphs.{name} attribute {key!r} ignored")
                continue
            if key == "symbols":
                if (
                    not isinstance(glyph, list)
                    or not 2 <= len(glyph) <= MAX_GLYPHS
                    or any(not _single_cell_glyph(item, ascii_only=ascii_only) for item in glyph)
                ):
                    _warn(warnings, f"glyphs.{name}.symbols must contain 2..{MAX_GLYPHS} single-cell glyphs")
                    continue
                result[key] = tuple(glyph)
            elif _single_cell_glyph(glyph, ascii_only=ascii_only):
                result[key] = glyph
            else:
                _warn(warnings, f"glyphs.{name}.{key} must be a printable single-cell glyph")
        return result or None
    _warn(warnings, f"glyphs.{name} must be a string, glyph array, or table; ignored")
    return None


def _parse_art_block(name: str, value: object, warnings: list[str]) -> tuple[str, ...] | None:
    if isinstance(value, str):
        if any(character != "\n" and not character.isprintable() for character in value):
            _warn(warnings, f"art.{name} contains a control or ANSI character; block rejected")
            return None
        rows = value.split("\n")
        if rows and rows[-1] == "":
            rows.pop()
    elif isinstance(value, dict):
        rows_value = value.get("rows")
        if not isinstance(rows_value, list) or any(not isinstance(row, str) for row in rows_value):
            _warn(warnings, f"art.{name} table requires an array of string rows; block rejected")
            return None
        rows = rows_value
    else:
        _warn(warnings, f"art.{name} must be a string block or rows table; block rejected")
        return None
    if len(rows) > MAX_ART_LINES:
        _warn(warnings, f"art.{name} exceeds {MAX_ART_LINES} lines; block rejected")
        return None
    for row in rows:
        if any(not character.isprintable() for character in row):
            _warn(warnings, f"art.{name} contains a control or ANSI character; block rejected")
            return None
        if wcswidth(row) > MAX_ART_COLUMNS or any(wcswidth(character) != 1 for character in row):
            _warn(warnings, f"art.{name} exceeds {MAX_ART_COLUMNS} columns or uses a non-single-cell glyph; block rejected")
            return None
    return tuple(rows)


def _bad_source(message: str) -> tuple[Skin, list[str]]:
    return mono_skin(), [message]


def _load_skin(path_or_text: object) -> tuple[Skin, list[str]]:
    """Load and normalize one TOML skin without raising for malformed input.

    Unusable sources return the guaranteed mono skin and warnings. Invalid individual
    sections are skipped or fall back to the `text` role when the rest is usable.
    """
    try:
        raw_bytes, label = _source_bytes(path_or_text)
        if raw_bytes is None:
            return _bad_source(f"{label}: empty source")
        if len(raw_bytes) > MAX_SKIN_BYTES:
            return _bad_source(f"{label}: source exceeds {MAX_SKIN_BYTES} bytes; using mono")
        text = raw_bytes.decode("utf-8")
        document = tomllib.loads(text)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, RecursionError, TypeError, ValueError) as error:
        return _bad_source(f"skin source is unusable ({error}); using mono")
    except Exception as error:  # Guard callers from parser/runtime edge cases on hostile objects.
        return _bad_source(f"skin source is unusable ({type(error).__name__}); using mono")

    if not isinstance(document, dict):
        return _bad_source("skin document must be a TOML table; using mono")
    warnings: list[str] = []
    unusable_sections: set[str] = set()
    for key, value in document.items():
        if key not in _KNOWN_TOP_LEVEL:
            _warn(warnings, f"unknown top-level key {key!r} ignored")
        if _container_depth_exceeded(value):
            unusable_sections.add(key)
            _warn(warnings, f"{key} nesting exceeds {MAX_NESTING}; section ignored")

    schema = document.get("schema")
    if not isinstance(schema, str) or schema not in ("md-editor-theme/1.0", SKIN_SCHEMA):
        return mono_skin(), warnings + [f"unsupported schema {schema!r}; using mono"]
    skin_id = document.get("id")
    name = document.get("name")
    if not isinstance(skin_id, str) or not _SKIN_ID_RE.fullmatch(skin_id):
        return mono_skin(), warnings + ["id must match ^[a-z0-9][a-z0-9-]{0,31}$; using mono"]
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 128
        or any(not character.isprintable() for character in name)
    ):
        return mono_skin(), warnings + ["name must be a printable non-empty string of at most 128 characters; using mono"]

    instrument = document.get("instrument", "any")
    if not isinstance(instrument, str) or not (
        instrument == "any" or _INSTRUMENT_RE.fullmatch(instrument)
    ):
        _warn(warnings, "instrument must be 'any' or a lowercase instrument id; using any")
        instrument = "any"
    fps = document.get("fps", 24)
    if isinstance(fps, bool) or not isinstance(fps, int) or not 1 <= fps <= 60:
        _warn(warnings, "fps must be an integer in the range 1..60; using 24")
        fps = 24

    palette: dict[str, str] = {}
    palette_value = document.get("palette", {})
    if "palette" not in unusable_sections:
        if not isinstance(palette_value, dict):
            _warn(warnings, "palette must be a table; section ignored")
        else:
            for key, color in palette_value.items():
                if not _valid_name(key):
                    _warn(warnings, f"palette key {key!r} is invalid; entry ignored")
                elif not _is_hex_color(color):
                    _warn(warnings, f"palette.{key} must be #rrggbb; entry ignored")
                else:
                    palette[key] = color.lower()

    styles_value = document.get("styles", {})
    if "styles" in unusable_sections:
        styles_value = {}
    elif not isinstance(styles_value, dict):
        _warn(warnings, "styles must be a table; section ignored")
        styles_value = {}
    else:
        styles_value = dict(styles_value)
    if schema == "md-editor-theme/1.0":
        for old_name, new_name in _ROLE_ALIASES.items():
            if old_name in styles_value:
                if new_name not in styles_value:
                    styles_value[new_name] = styles_value[old_name]
                styles_value.pop(old_name)

    default_text = mono_skin().style("text")

    def parse_style(role: str, value: object, base: Style) -> Style:
        if not isinstance(value, dict):
            _warn(warnings, f"styles.{role} must be a table; using text style")
            return base
        for key in value:
            if key not in _STYLE_ATTRIBUTES:
                _warn(warnings, f"unknown styles.{role} attribute {key!r} ignored")
        colors: dict[str, str | None] = {"fg": base.fg, "bg": base.bg}
        for key in ("fg", "bg"):
            if key in value:
                resolved = _resolve_color(value[key], palette)
                if resolved is None:
                    _warn(warnings, f"styles.{role}.{key} is not a known #rrggbb color or palette name; using text color")
                else:
                    colors[key] = resolved
        attributes: dict[str, bool] = {}
        for key in ("bold", "italic", "underline", "reverse"):
            setting = value.get(key, getattr(base, key))
            if not isinstance(setting, bool):
                _warn(warnings, f"styles.{role}.{key} must be boolean; using text style")
                setting = getattr(base, key)
            attributes[key] = setting
        return Style(fg=colors["fg"], bg=colors["bg"], **attributes)

    text_value = styles_value.get("text")
    if text_value is None:
        _warn(warnings, "missing styles.text; using guaranteed mono text style")
        text_style = default_text
    else:
        text_style = parse_style("text", text_value, default_text)
    styles: dict[str, Style] = {"text": text_style}
    for role in REQUIRED_ROLES:
        if role == "text":
            continue
        if role not in styles_value:
            _warn(warnings, f"missing role {role!r}; using text style")
            styles[role] = text_style
        else:
            styles[role] = parse_style(role, styles_value[role], text_style)
    for role, value in styles_value.items():
        normalized_role = _ROLE_ALIASES.get(role, role) if isinstance(role, str) else role
        if (
            not isinstance(normalized_role, str)
            or not _valid_name(normalized_role)
            or normalized_role in styles
        ):
            continue
        styles[normalized_role] = parse_style(normalized_role, value, text_style)

    glyphs: dict[str, _Glyph] = {}
    glyph_value = document.get("glyphs", {})
    if "glyphs" not in unusable_sections:
        if not isinstance(glyph_value, dict):
            _warn(warnings, "glyphs must be a table; section ignored")
        else:
            for key, value in glyph_value.items():
                if not _valid_name(key):
                    _warn(warnings, f"glyph set name {key!r} is invalid; entry ignored")
                    continue
                parsed = _parse_glyph_entry(key, value, warnings)
                if parsed is not None:
                    glyphs[key] = parsed

    ramps: dict[str, tuple[str, ...]] = {}
    ramps_value = document.get("ramps", {})
    if "ramps" not in unusable_sections:
        if not isinstance(ramps_value, dict):
            _warn(warnings, "ramps must be a table; section ignored")
        else:
            for key, value in ramps_value.items():
                if not _valid_name(key):
                    _warn(warnings, f"ramp name {key!r} is invalid; entry ignored")
                    continue
                stops = value
                if isinstance(value, dict):
                    stops = value.get("colours", value.get("colors"))
                    for attr in value:
                        if attr not in {"colours", "colors", "steps"}:
                            _warn(warnings, f"unknown ramps.{key} attribute {attr!r} ignored")
                    steps = value.get("steps", 16)
                    if isinstance(steps, bool) or not isinstance(steps, int) or not 2 <= steps <= 256:
                        _warn(warnings, f"ramps.{key}.steps must be an integer in the range 2..256; ignored")
                if not isinstance(stops, list) or not 2 <= len(stops) <= MAX_RAMP_STOPS:
                    _warn(warnings, f"ramps.{key} must contain 2..{MAX_RAMP_STOPS} color stops; entry ignored")
                    continue
                resolved_stops = tuple(_resolve_color(stop, palette) for stop in stops)
                if any(stop is None for stop in resolved_stops):
                    _warn(warnings, f"ramps.{key} contains an invalid color; entry ignored")
                    continue
                ramps[key] = tuple(stop for stop in resolved_stops if stop is not None)

    art: dict[str, tuple[str, ...]] = {}
    art_value = document.get("art", {})
    if "art" not in unusable_sections:
        if not isinstance(art_value, dict):
            _warn(warnings, "art must be a table; section ignored")
        else:
            for key, value in art_value.items():
                if not _valid_name(key):
                    _warn(warnings, f"art block name {key!r} is invalid; entry ignored")
                    continue
                parsed = _parse_art_block(key, value, warnings)
                if parsed is not None:
                    art[key] = parsed

    fallbacks: dict[str, object] = {}
    fallback_value = document.get("fallbacks", {})
    if "fallbacks" not in unusable_sections:
        if not isinstance(fallback_value, dict):
            _warn(warnings, "fallbacks must be a table; section ignored")
        else:
            for key, value in fallback_value.items():
                if key != "ascii":
                    _warn(warnings, f"unknown fallback {key!r} ignored")
                    continue
                if not isinstance(value, dict):
                    _warn(warnings, "fallbacks.ascii must be a table; section ignored")
                    continue
                ascii_values: dict[str, object] = {}
                raw_glyphs = value.get("glyphs", {})
                if not isinstance(raw_glyphs, dict):
                    _warn(warnings, "fallbacks.ascii.glyphs must be a table; section ignored")
                else:
                    parsed_glyphs: dict[str, _Glyph] = {}
                    for glyph_name, glyph_value in raw_glyphs.items():
                        if not _valid_name(glyph_name):
                            _warn(warnings, f"fallback ASCII glyph name {glyph_name!r} is invalid; ignored")
                            continue
                        glyph = _parse_glyph_entry(glyph_name, glyph_value, warnings, ascii_only=True)
                        if glyph is not None:
                            parsed_glyphs[glyph_name] = glyph
                    ascii_values["glyphs"] = parsed_glyphs
                for attr in value:
                    if attr != "glyphs":
                        _warn(warnings, f"unknown fallbacks.ascii attribute {attr!r} ignored")
                fallbacks["ascii"] = ascii_values

    return (
        Skin(
            id=skin_id,
            name=name,
            instrument=instrument,
            fps=fps,
            palette=palette,
            styles=styles,
            glyphs=glyphs,
            ramps=ramps,
            art=art,
            fallbacks=fallbacks,
            schema=SKIN_SCHEMA,
        ),
        warnings,
    )


def load_skin(path_or_text: object) -> tuple[Skin, list[str]]:
    """Load a skin, converting any parser/normalizer failure into mono plus a warning."""
    try:
        return _load_skin(path_or_text)
    except Exception as error:
        return _bad_source(f"skin source could not be normalized ({type(error).__name__}); using mono")


class SkinLibrary:
    """Load factory and user skins, with user overrides and wraparound cycling."""

    @classmethod
    def for_instrument(
        cls,
        instrument: str,
        *,
        data_dir: str | os.PathLike[str] | None = None,
        factory_dir: str | os.PathLike[str] | None = None,
        skin_id: str | None = None,
        mono: bool = False,
        no_color: bool | None = None,
        environ: Mapping[str, str] | None = None,
        include_user: bool = True,
    ) -> SkinLibrary:
        """Create a library using the selected instrument's standard user-data directory."""
        user_dir = get_user_data_dir(instrument, data_dir) / "skins" if include_user else None
        return cls(
            instrument,
            factory_dir=factory_dir,
            user_dir=user_dir,
            skin_id=skin_id,
            mono=mono,
            no_color=no_color,
            environ=environ,
            include_user=include_user,
        )

    def __init__(
        self,
        instrument: str | None = None,
        *,
        factory_dir: str | os.PathLike[str] | None = None,
        user_dir: str | os.PathLike[str] | None = None,
        skin_id: str | None = None,
        mono: bool = False,
        no_color: bool | None = None,
        environ: Mapping[str, str] | None = None,
        include_user: bool = True,
    ) -> None:
        if instrument is not None and (
            not isinstance(instrument, str)
            or instrument != "any" and _INSTRUMENT_RE.fullmatch(instrument) is None
        ):
            raise ValueError("instrument must be None, 'any', or a lowercase instrument id")
        if not isinstance(mono, bool):
            raise ValueError("mono must be a boolean")
        if no_color is not None and not isinstance(no_color, bool):
            raise ValueError("no_color must be a boolean or None")
        if not isinstance(include_user, bool):
            raise ValueError("include_user must be a boolean")
        self.instrument = instrument
        self._warnings: list[str] = []
        self._skins: dict[str, Skin] = {"mono": mono_skin()}
        default_factory = Path(__file__).resolve().parent / "data" / "skins"
        self.factory_dir = Path(factory_dir).expanduser() if factory_dir is not None else default_factory
        if user_dir is not None:
            self.user_dir = Path(user_dir).expanduser()
        elif include_user and instrument not in (None, "any"):
            self.user_dir = get_user_data_dir(instrument, None) / "skins"
        else:
            self.user_dir = None
        self._load_directory(self.factory_dir, is_user=False)
        if self.user_dir is not None:
            self._load_directory(self.user_dir, is_user=True)

        environment = os.environ if environ is None else environ
        environment_requests_mono = "NO_COLOR" in environment or no_color is True
        self._forced_mono = mono or environment_requests_mono
        self._ids = ("mono", *sorted(key for key in self._skins if key != "mono"))
        self._current_id = "mono"
        if not self._forced_mono:
            if skin_id is None:
                self._current_id = self._ids[0]
            else:
                self.select(skin_id)

    def _matches_instrument(self, skin: Skin) -> bool:
        return self.instrument in (None, "any") or skin.instrument in ("any", self.instrument)

    def _load_directory(self, directory: Path, *, is_user: bool) -> None:
        try:
            if not directory.exists():
                return
            paths = sorted(directory.glob("*.toml"), key=lambda path: path.name.casefold())
        except OSError as error:
            self._warnings.append(f"cannot list skin directory {directory}: {error}")
            return
        for path in paths:
            skin, warnings = load_skin(path)
            self._warnings.extend(f"{path}: {warning}" for warning in warnings)
            if skin is mono_skin():
                continue
            if skin.id == "mono":
                if path.stem != "mono":
                    self._warnings.append(f"{path}: mono is reserved for the guaranteed built-in skin")
                elif is_user:
                    self._warnings.append(f"{path}: user skins cannot override the guaranteed built-in mono skin")
                continue
            if not self._matches_instrument(skin):
                self._warnings.append(f"{path}: skin {skin.id!r} does not match instrument; ignored")
                continue
            if is_user:
                self._skins[skin.id] = skin
            elif skin.id in self._skins:
                self._warnings.append(f"{path}: duplicate factory skin id {skin.id!r}; first skin kept")
            else:
                self._skins[skin.id] = skin

    @property
    def ids(self) -> tuple[str, ...]:
        return self._ids

    @property
    def current_id(self) -> str:
        return self._current_id

    @property
    def current(self) -> Skin:
        return self._skins[self._current_id]

    @property
    def forced_mono(self) -> bool:
        return self._forced_mono

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(self._warnings)

    def select(self, skin_id: str) -> Skin:
        """Select an installed skin; unknown names fall back to the built-in mono skin."""
        if not isinstance(skin_id, str):
            skin_id = ""
        if self._forced_mono:
            self._current_id = "mono"
            return self.current
        if skin_id not in self._skins:
            self._warnings.append(f"unknown skin {skin_id!r}; using mono")
            self._current_id = "mono"
            return self.current
        self._current_id = skin_id
        return self.current

    def cycle(self, direction: int = 1) -> Skin:
        """Cycle through available IDs in either direction, wrapping at each end."""
        if isinstance(direction, bool) or not isinstance(direction, int):
            raise ValueError("direction must be an integer")
        if self._forced_mono:
            self._current_id = "mono"
            return self.current
        index = self._ids.index(self._current_id)
        self._current_id = self._ids[(index + direction) % len(self._ids)]
        return self.current


__all__ = [
    "MAX_ART_COLUMNS",
    "MAX_ART_LINES",
    "MAX_GLYPHS",
    "MAX_NESTING",
    "MAX_RAMP_STOPS",
    "MAX_SKIN_BYTES",
    "REQUIRED_ROLES",
    "SKIN_SCHEMA",
    "Skin",
    "SkinLibrary",
    "Style",
    "load_skin",
    "mono_skin",
]
