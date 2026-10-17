---
corpus: tuisynth
programme: trio
document_id: TRIO-SKINS
status: authority
---
# Skins, colourways and ASCII art contract (TRIO-006)

## Format

TOML, compatible with the subset of `md-editor-theme/1.1` used by the recovered synths
(historical examples exist in public `techrote/tuisynth/cpusynth/themes/` as optional background; the local format below is authoritative), plus
TRIO extension tables. Legacy `md-editor-theme/1.0` files are accepted with the same
normalisation the recovered synths applied.

```toml
schema = "md-editor-theme/1.1"
id = "borealis"                      # ^[a-z0-9][a-z0-9-]{0,31}$
name = "BOREALIS"
instrument = "aurora"                # or "any"
fps = 24

[palette]                            # names -> "#rrggbb"
bg = "#03121a"
fg = "#cfe9e4"

[styles]                             # role -> {fg, bg, bold, italic, underline, reverse}
text = { fg = "fg", bg = "bg" }

[glyphs]                             # named glyph sets used by layouts and visualizers
density = [" ", ".", ":", "-", "=", "+", "*", "#", "%", "@"]
frame = "round"                      # round | square | heavy | double | ascii

[ramps]                              # named colour gradients (2-16 palette names or hex)
aurora = ["bg", "#0b3d3a", "#14a37f", "#7cf5c4", "#b388ff"]

[art]                                # named multi-line ASCII art blocks
logo = """
 _  _   _ ___  ___  ___    _
"""

[fallbacks.ascii]                    # used with --ascii or narrow terminals
glyphs = { density = [" ", ".", ":", "+", "#"], frame = "ascii" }
```

## Required roles

`background`, `text`, `muted`, `border`, `title`, `heading`, `accent`, `status`, `warning`,
`error`, `focused`, `hover`, `pressed`, `selected`, `disabled`, plus `key_white`,
`key_black`, `key_pressed`, `meter_low`, `meter_mid`, `meter_high`. Missing roles fall back
to `text` (and are listed in load warnings).

## Validation (never crash)

`load_skin(path_or_text) -> (Skin, warnings)` never raises for bad content; it returns the
`mono` fallback plus warnings when the file is unusable. Rules:

- File size <= 128 KiB; TOML parse errors -> fallback + warning.
- Colours must be `#rrggbb` or a palette name; anything else -> warning, role uses `text`.
- Unknown top-level keys or style attributes -> warning, ignored.
- Art blocks: <= 40 lines x 160 columns, printable characters only; control characters and
  ESC/ANSI sequences cause the block to be rejected; double-width glyphs rejected.
- Glyph ramps: 2-16 single-cell printable glyphs.
- Nesting depth > 4 or non-table where a table is required -> warning, section ignored.
- Hostile cases are tested: deep nesting, huge strings, wrong types everywhere, ANSI
  injection, unknown schema versions, empty file, binary bytes.

## Colour depth

Truecolour by default. `NO_COLOR` environment variable or `--mono` forces the `mono` skin.
When prompt_toolkit reports a 256- or 16-colour terminal, colours are quantised by
prompt_toolkit's own colour-depth handling; skins must still be legible in `mono`.

## Live switching

`F6`/`Shift+F6` cycle skins; the library overlay previews a skin on hover and commits on
click/Enter, `Esc` reverts. The active skin is remembered in session state.

## Per-instrument factory colourways (art direction)

| Instrument | Skin | Mood | Key colours |
|---|---|---|---|
| AURORA | `borealis` | arctic night sky | navy `#03121a`, teal, green `#14a37f`, mint, violet |
| AURORA | `solar-wind` | magnetosphere storm | deep plum, magenta, gold, coral |
| AURORA | `polar-night` | ice and starlight | black-blue, ice blue, white, silver |
| LOOM | `rosewood` | warm luthier's bench | dark wood brown, amber, cream, brass |
| LOOM | `brass` | concert hall | charcoal, gold, copper, ivory |
| LOOM | `indigo-loom` | textile workshop | indigo, cream, rust thread, teal |
| DRIFT | `squall` | north-sea weather radar | slate, cyan, white caps, warning orange |
| DRIFT | `desert-haze` | heat shimmer | sand, peach, dusty rose, sky |
| DRIFT | `monsoon` | rainforest storm | deep green, teal, lightning yellow |
| all | `mono` | guaranteed-safe fallback | black, white, grey only; ASCII-safe glyphs |

Each instrument's skins also define its own `[art]` logo and visualizer `[glyphs]`/`[ramps]`
so the look stays instrument-specific.
