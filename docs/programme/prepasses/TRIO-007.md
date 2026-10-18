# TRIO-007 prepass

## Reconciliation

- Issue #7 is open, has no owner comments, and depends on #2 and #6. Both dependencies are merged and green on current `main` (`d1bdae53262d4627db0e170bdc2db7a139d905ca`). No open duplicate PR exists.
- The branch `trio-007-tui` starts from that exact `main` revision.
- `kit` already depends on prompt_toolkit and wcwidth, and `ParamSpec`/`ParamRegistry` provide the normalized parameter mapping needed by reusable controls. There is no existing TUI package.
- The canvas, widget and application layer must not import engine or DSP modules. Tests can use a fake event collector to prove callback output without coupling widgets to `Engine`.

## Implementation decisions

- Canvas coordinates, hit rectangles, `MouseRouter` events, and public `HeadlessApp` helpers use zero-based `(x, y)` cells with half-open rectangles. SGR helpers encode terminal coordinates as `(x + 1, y + 1)`; prompt_toolkit's VT100 mouse binding decodes them to zero-based positions before the canvas handler runs.
- Canvas text is cell-safe: a printable width-one character is drawn as-is, while a non-printable or non-single-cell character is replaced with `?` in text flow and rejected by `put`. Clipping applies to cells and hit rectangles; overlapping hits use draw order, with the newest rectangle on top.
- Capture belongs to the last rendered hit target and continues routing move/up outside its rectangle. Capture clears on mouse-up; right-click and wheel remain target-addressed events.
- Widgets implement keyboard and mouse behavior in pure Python callbacks. `CanvasApp` supplies full-screen prompt_toolkit rendering and preserves global quit handling even when user rendering fails. `HeadlessApp` runs the same app with a pipe input and sized `DummyOutput`, sending literal xterm SGR sequences.
- Golden snapshots are deterministic text files for 100x30 and 80x24 mono. No device, network, or terminal is used by tests.

## Contract reconciliation to carry into TRIO-007

The authority contract's shorthand `events()` wording refers to events observed at the UI callback boundary. The TUI package will not construct engine events; a fake collector in tests may translate callbacks to representative events. This keeps the issue's headless evidence requirement while respecting its explicit engine/DSP import boundary.

## Risks to qualify

- prompt_toolkit's parser must be exercised with actual SGR bytes, not a mocked `MouseEvent`, on both Linux and Windows CI.
- Resizing and non-full-screen rendering must keep canvas geometry and routed hit coordinates aligned.
- A render exception must not replace or disable the global quit binding.
