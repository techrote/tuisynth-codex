from __future__ import annotations

from pathlib import Path

import pytest

from trio_kit.skins import REQUIRED_ROLES, Skin, SkinLibrary, Style, load_skin, mono_skin


def skin_toml(
    *,
    skin_id: str = "test-skin",
    name: str = "Test Skin",
    instrument: str = "any",
    accent: str = "#14a37f",
    schema: str = "md-editor-theme/1.1",
    extras: str = "",
) -> str:
    roles = "\n".join(
        f'{role} = {{ fg = "accent", bg = "bg" }}'
        for role in REQUIRED_ROLES
    )
    return f'''schema = "{schema}"
id = "{skin_id}"
name = "{name}"
instrument = "{instrument}"
fps = 24

[palette]
bg = "#03121a"
accent = "{accent}"
white = "#ffffff"

[styles]
{roles}

[glyphs]
density = [" ", ".", ":", "+", "#"]
frame = "ascii"

[ramps]
signal = ["bg", "accent", "white"]

[art]
logo = "SAFE SKIN"

[fallbacks.ascii]
glyphs = {{ density = [" ", ".", "+", "#"], frame = "ascii" }}
{extras}'''


def write_skin(directory: Path, *, skin_id: str, accent: str, instrument: str = "any") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{skin_id}.toml"
    path.write_text(
        skin_toml(skin_id=skin_id, accent=accent, instrument=instrument),
        encoding="utf-8",
    )
    return path


def test_mono_skin_is_complete_ascii_safe_and_packaged_asset_matches() -> None:
    skin = mono_skin()
    assert set(REQUIRED_ROLES) <= set(skin.styles)
    assert skin.style("missing-role") == skin.style("text")
    assert skin.glyph("frame") == "ascii"
    assert all(ord(char) < 128 for row in skin.art_block("logo") for char in row)
    assert all(
        ord(char) < 128
        for value in skin.glyphs.values()
        for glyph in (value if isinstance(value, tuple) else (value,))
        if isinstance(glyph, str)
        for char in glyph
    )
    assert all(ord(char) < 128 for value in skin.ascii_glyphs.values() for char in value)

    asset = Path(__file__).parents[1] / "src" / "trio_kit" / "data" / "skins" / "mono.toml"
    loaded, warnings = load_skin(asset)
    assert loaded.id == "mono"
    assert warnings == []
    assert loaded.styles == skin.styles
    assert loaded.art == skin.art


def test_complete_skin_resolves_roles_colors_ramps_glyphs_art_and_ascii_fallback() -> None:
    skin, warnings = load_skin(skin_toml())

    assert skin.id == "test-skin"
    assert skin.schema == "md-editor-theme/1.1"
    assert skin.style("accent") == Style(fg="#14a37f", bg="#03121a")
    assert skin.style("unknown") == skin.style("text")
    assert skin.ramp("signal") == ("#03121a", "#14a37f", "#ffffff")
    assert skin.glyph("density") == " "
    assert skin.glyph("density", on=True) == "#"
    assert skin.glyph("frame") == "ascii"
    assert skin.art_block("logo") == ("SAFE SKIN",)
    assert skin.ascii_glyphs["density"] == (" ", ".", "+", "#")
    assert warnings == []


def test_legacy_schema_normalizes_role_aliases_and_nested_ramps_glyphs_and_art() -> None:
    source = '''schema = "md-editor-theme/1.0"
id = "legacy"
name = "Legacy"

[palette]
bg = "#000000"
fg = "#ffffff"
accent = "#33aaee"

[styles]
text = { fg = "fg", bg = "bg" }
status_ok = { fg = "accent" }
status_warn = { fg = "#ffaa00" }
status_err = { fg = "#ff0000" }
sel = { fg = "fg", bg = "accent" }
focus = { fg = "accent", bold = true }
press = { reverse = true }

[ramps.signal]
colours = ["bg", "accent", "fg"]
steps = 16

[glyphs.divider]
symbols = ["-", "="]
on = "#"
off = "-"

[art.logo]
rows = ["LEGACY", "  ART"]
style = "title"
'''
    skin, warnings = load_skin(source)

    assert skin.schema == "md-editor-theme/1.1"
    assert skin.style("status").fg == "#33aaee"
    assert skin.style("warning").fg == "#ffaa00"
    assert skin.style("error").fg == "#ff0000"
    assert skin.style("selected").bg == "#33aaee"
    assert skin.style("focused").bold
    assert skin.style("pressed").reverse
    assert skin.ramp("signal") == ("#000000", "#33aaee", "#ffffff")
    assert skin.glyph("divider") == "-"
    assert skin.glyph("divider", on=True) == "#"
    assert skin.art_block("logo") == ("LEGACY", "  ART")
    assert warnings
    assert all("missing role" in warning for warning in warnings)


@pytest.mark.parametrize(
    "source",
    (
        pytest.param("", id="empty"),
        pytest.param("not = [valid TOML", id="parse-error"),
        pytest.param(b"\xff\xfe\x00\x01", id="binary"),
        pytest.param('schema = ["md-editor-theme/1.1"]\nid = "bad-schema"\nname = "Bad"', id="nonstring-schema"),
        pytest.param('schema = "md-editor-theme/1.1"\nid = []\nname = "Bad"', id="nonstring-id"),
        pytest.param('schema = "md-editor-theme/1.1"\nid = "ok"\nname = 42', id="nonstring-name"),
        pytest.param('schema = "md-editor-theme/9.9"\nid = "bad-schema"\nname = "Bad"', id="unknown-schema"),
        pytest.param('schema = "md-editor-theme/1.1"\nid = "Bad_ID"\nname = "Bad"', id="bad-id"),
        pytest.param('schema = "md-editor-theme/1.1"\nid = "ok"\nname = "Bad"\n\n[palette]\nbg = []\n\n[styles]\ntext = "bad"\n\n[glyphs]\ndensity = 3\n\n[ramps]\nx = "bad"\n\n[art]\nlogo = false\n\n[fallbacks]\nascii = []', id="wrong-types"),
        pytest.param('schema = "md-editor-theme/1.1"\nid = "deep"\nname = "Deep"\n\n[unknown.a.b.c.d.e]\nx = 1', id="deep-nesting"),
    ),
)
def test_hostile_skin_sources_never_raise_and_return_usable_fallback_or_skin(source: object) -> None:
    skin, warnings = load_skin(source)

    assert isinstance(skin, Skin)
    assert skin.style("text") == mono_skin().style("text")
    assert warnings


def test_oversize_skin_bytes_return_mono_with_warning() -> None:
    skin, warnings = load_skin(b"x" * (128 * 1024 + 1))
    assert skin is mono_skin()
    assert any("exceeds 131072 bytes" in warning for warning in warnings)


def test_deep_and_wrong_type_sections_are_ignored_without_losing_valid_skin() -> None:
    source = skin_toml(extras="\n[extra.a.b.c.d.e]\nvalue = 1\n")
    # The extra top-level section is unknown; it is reported and ignored.
    skin, warnings = load_skin(source)
    assert skin.id == "test-skin"
    assert any("unknown top-level key" in warning for warning in warnings)

    wrong_types = '''schema = "md-editor-theme/1.1"
id = "partial"
name = "Partial"
palette = false
styles = []
glyphs = 1
ramps = false
art = []
fallbacks = "invalid"
'''
    partial, warnings = load_skin(wrong_types)
    assert partial.id == "partial"
    assert partial.style("text") == mono_skin().style("text")
    assert any("palette must be a table" in warning for warning in warnings)


def test_missing_roles_and_bad_colors_warn_and_fall_back_to_text_style() -> None:
    source = '''schema = "md-editor-theme/1.1"
id = "partial"
name = "Partial"

[palette]
accent = "invalid"

[styles]
text = { fg = "#abcdef", bg = "#010203" }
accent = { fg = "missing", bold = "yes", strike = true }
'''
    skin, warnings = load_skin(source)
    assert skin.style("accent") == skin.style("text")
    assert skin.style("text").fg == "#abcdef"
    assert any("palette.accent must be #rrggbb" in warning for warning in warnings)
    assert any("unknown styles.accent attribute 'strike'" in warning for warning in warnings)
    assert any("missing role 'warning'" in warning for warning in warnings)


def test_art_glyph_and_ramp_limits_reject_only_the_bad_blocks() -> None:
    too_many_lines = "\\n".join("x" for _ in range(41))
    too_wide = "x" * 161
    source = skin_toml()
    source = source.replace(
        'density = [" ", ".", ":", "+", "#"]',
        'density = [" ", ".", ":", "+", "#"]\nwide = ["a", "界"]\ntoo_many = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o", "p", "q"]',
    )
    source = source.replace(
        'signal = ["bg", "accent", "white"]',
        'signal = ["bg", "accent", "white"]\ntoo_many = ["#000000", "#111111", "#222222", "#333333", "#444444", "#555555", "#666666", "#777777", "#888888", "#999999", "#aaaaaa", "#bbbbbb", "#cccccc", "#dddddd", "#eeeeee", "#ffffff", "#010101"]\nbad_color = ["#000000", "not-a-color"]',
    )
    source = source.replace(
        'logo = "SAFE SKIN"',
        f'logo = "SAFE SKIN"\nansi = "\\u001b[31mred"\nwide = "界"\nmany_lines = "{too_many_lines}"\nwide_line = "{too_wide}"',
    )
    skin, warnings = load_skin(source)

    assert skin.id == "test-skin"
    assert skin.art_block("ansi") == ()
    assert skin.art_block("wide") == ()
    assert skin.art_block("many_lines") == ()
    assert skin.art_block("wide_line") == ()
    assert "wide" not in skin.glyphs
    assert "too_many" not in skin.glyphs
    assert "too_many" not in skin.ramps
    assert "bad_color" not in skin.ramps
    assert any("ANSI character" in warning for warning in warnings)
    assert any("single-cell glyph" in warning for warning in warnings)
    assert any("2..16 color stops" in warning for warning in warnings)


def test_skin_library_uses_user_precedence_filters_instrument_and_cycles(tmp_path: Path) -> None:
    factory = tmp_path / "factory"
    user = tmp_path / "user"
    write_skin(factory, skin_id="shared", accent="#111111")
    write_skin(factory, skin_id="aurora-only", accent="#222222", instrument="aurora")
    write_skin(factory, skin_id="loom-only", accent="#333333", instrument="loom")
    write_skin(user, skin_id="shared", accent="#abcdef")
    write_skin(user, skin_id="mono", accent="#ff00ff")

    library = SkinLibrary(
        "aurora",
        factory_dir=factory,
        user_dir=user,
        environ={},
    )

    assert library.ids == ("mono", "aurora-only", "shared")
    assert library.current_id == "mono"
    assert library.cycle(1).id == "aurora-only"
    assert library.cycle(1).id == "shared"
    assert library.current.palette["accent"] == "#abcdef"
    assert library.cycle(1).id == "mono"
    assert library.cycle(-1).id == "shared"
    assert library.select("unknown").id == "mono"
    assert any("unknown skin" in warning for warning in library.warnings)
    assert any("cannot override" in warning for warning in library.warnings)


def test_mono_flag_and_no_color_environment_pin_library_to_safe_mono(tmp_path: Path) -> None:
    factory = tmp_path / "factory"
    write_skin(factory, skin_id="custom", accent="#abcdef")

    by_flag = SkinLibrary(factory_dir=factory, skin_id="custom", mono=True, environ={})
    assert by_flag.current_id == "mono"
    assert by_flag.select("custom").id == "mono"
    assert by_flag.cycle().id == "mono"

    by_environment = SkinLibrary(
        factory_dir=factory,
        skin_id="custom",
        no_color=False,
        environ={"NO_COLOR": ""},
    )
    assert by_environment.forced_mono
    assert by_environment.current_id == "mono"
    assert by_environment.select("custom").id == "mono"


def test_library_factory_method_uses_instrument_user_data_and_invalid_files_warn(tmp_path: Path) -> None:
    user_skins = tmp_path / "aurora" / "skins"
    write_skin(user_skins, skin_id="user-only", accent="#abcdef")
    (user_skins / "broken.toml").write_text("schema = [", encoding="utf-8")

    library = SkinLibrary.for_instrument("aurora", data_dir=tmp_path, environ={})
    assert library.user_dir == user_skins
    assert "user-only" in library.ids
    assert "mono" in library.ids
    assert any("broken.toml" in warning for warning in library.warnings)
    assert not any("reserved" in warning for warning in library.warnings)


def test_skin_and_style_models_are_immutable_and_validate_public_values() -> None:
    skin = mono_skin()
    with pytest.raises(TypeError):
        skin.palette["new"] = "#123456"  # type: ignore[index]
    with pytest.raises(ValueError, match="#rrggbb"):
        Style(fg="red")
    with pytest.raises(ValueError, match="boolean"):
        Style(bold=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="skin id"):
        Skin(
            id="invalid_id",
            name="Invalid",
            instrument="any",
            fps=24,
            palette={},
            styles={"text": Style()},
            glyphs={},
            ramps={},
            art={},
            fallbacks={},
        )
