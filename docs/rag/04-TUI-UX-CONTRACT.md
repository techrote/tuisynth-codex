---
corpus: tuisynth
programme: trio
document_id: TRIO-UX
status: authority
---
# TUI and UX contract

## Philosophy (inherited and tightened from the recovered synths' "mdbm" notes)

1. **Mouse first, keyboard everything.** Each mouse action has a keyboard twin listed in the
   footer tips for the current context and in the F1 help overlay.
2. **Semantic colour only.** Code asks for roles (`accent`, `selected`, ...); skins supply hues.
   No information is conveyed by colour alone: state also changes glyphs or labels.
3. **Art is data.** Logos, frames and visualizer glyph ramps come from the skin; the layout
   code places them. A skin can change the look, never the behaviour.
4. **Never crash the frame.** A render exception draws an error panel (message + `F1`/`Ctrl+Q`
   hints) and logs to the user data directory; input keeps working.

## Rendering model (TRIO-007)

- One full-screen prompt_toolkit `Application` with `mouse_support=True` and a single
  `FormattedTextControl` repainting a `Canvas` (character grid with per-cell style role).
- `Canvas` primitives: `put`, `fill`, `hline`, `vline`, `box` (rounded/square/heavy/ascii),
  `text_center`, `blit_art` (multi-line art block, clipped), and `hit(x, y, w, h, tag, payload)`.
- Width handling uses `wcwidth`; double-width glyphs are rejected from art/glyph ramps at
  skin load so geometry stays one glyph = one cell.
- Frame rate: invalidate at most 30 fps while animating, 4 fps idle; repaint only when state
  or telemetry changed (dirty flag).
- Minimum terminal 100x30 for the full layout. Between 80x24 and 100x30 each instrument
  provides a compact layout. Below 80x24 show a centred "enlarge terminal" panel.
  Resizing re-lays out without restart.
- `--ascii` (or a skin fallback) restricts all drawing to 7-bit ASCII glyphs.

## Mouse model (TRIO-007)

prompt_toolkit delivers SGR mouse events. The kit adds:

- **Hit testing** by the last rendered hit map (list of rectangles, top-most wins).
- **Capture**: a mouse-down on a widget captures subsequent move/up events until mouse-up,
  even if the pointer leaves the widget (required for faders, painters, strums and the XY map).
- **Wheel**: fine adjust (+-1 step; with Ctrl coarse +-10 steps when the terminal reports it).
- **Right-click**: reset a control to its default (widgets) or widget-specific action
  (documented per widget).
- **Hover**: highlight with role `hover` when the terminal reports motion.
- `Shift`+drag is left to the terminal for text selection (Windows Terminal behaviour).

## Widget set (TRIO-007)

`Fader` (horizontal/vertical, label + formatted value), `Knob` (ASCII arc with 7 positions,
drag vertically to turn), `Toggle`, `Choice` (click cycles, wheel steps), `XYPad`,
`Meter` (stereo peak/RMS), `Button`, `TextField` (preset names), `ListBox` (library),
`Tabs`. Every widget: focusable via `Tab`/`Shift+Tab`, adjustable with arrows
(`Left/Right` or `Down/Up` = 1 step, `PageUp/PageDown` = 10 steps, `Home/End` = min/max),
`Delete` resets to default, `Enter` activates. Widgets bind to `ParamRegistry` keys and call
an `on_change(key, value)` callback; the app shell (TRIO-008) turns that into `ParamSet`
events. Widgets never touch DSP objects and do not import `trio_kit.engine`.

## App shell (TRIO-008)

Shared by all instruments, customised by layout:

| Key | Action |
|---|---|
| `F1` | help overlay (all keys + mouse actions for the current screen) |
| `F2`..`F5` | instrument screens / panels / drawers (instrument-defined) |
| `F6` / `Shift+F6` | next / previous skin (live) |
| `F7` | MIDI picker (ports, channel, CC-learn bindings) |
| `F8` | preset library (load, save, save-as, rename, delete user preset) |
| `F9` | panic |
| `Ctrl+L` | arm MIDI CC learn on the focused control |
| `Ctrl+P` | command palette (fuzzy list of every command; the recovery route) |
| `Ctrl+Z` / `Ctrl+Y` | undo / redo parameter changes (50-step history) |
| `Esc` | close overlay / clear focus |
| `Ctrl+Q` | quit (releases all notes, stops audio, closes MIDI, restores the terminal) |

Header line: instrument logo/name, preset name (with `*` when modified), skin, MIDI port,
voices in use, CPU %, limiter activity. Footer line: context tips. Letter and digit keys are
reserved for notes (see TRIO-INPUT); shell commands use F-keys and Ctrl chords only.

## Shared command-line flags (TRIO-008)

`--skin ID`, `--preset ID`, `--midi INDEX|NAME`, `--midi-channel 0..16`, `--no-audio`,
`--device ID|NAME`, `--sample-rate 44100|48000`, `--ascii`, `--mono`, `--data-dir PATH`,
`--list-skins`, `--list-presets`, `--list-midi`, `--list-devices`, `--version`,
`--selftest` (load every factory preset and skin, render 2 s offline, assert limiter and
finiteness, exit 0/1 without opening a terminal UI or device) and
`--render OUT.wav --notes C4,E4,G4 --seconds 4 [--preset ID] [--seed N]`
(offline PCM16 stereo WAV, no terminal UI) and
`--snapshot COLSxROWS [--screen NAME] [--skin ID]` (print one frozen frame of the UI as plain
text using the headless driver; used for documentation and golden tests).

## Headless test driver (TRIO-007)

`trio_kit.tui.testing.HeadlessApp` runs an app with prompt_toolkit `create_pipe_input()` and
`DummyOutput` at a chosen size, offers `send_keys("...")`, `click(x, y, button)`,
`drag(path)`, `release(x, y)`, `wheel(x, y, direction)` (all emitted as real SGR byte
sequences), `screen_text()` (the rendered canvas as plain text) and `events()` (engine events
captured from a fake engine). Golden screen snapshots live in `tests/snapshots/*.txt` and are
updated only with `--update-snapshots`.
