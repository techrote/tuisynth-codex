# TRIO-008 prepass

## Reconciliation

- Issue #8 remains open without owner comments. Its dependencies #3, #5 and #7 are merged, and `main` CI passed at `0c21721d2b8c30c15ac3502c5f39dddf479198cc`.
- No duplicate/open PR exists. Branch `trio-008-shell` begins at the current `origin/main` revision.
- The kit already provides a bounded event queue and block-boundary `ParamSet` application, device-free `NullBackend`, lazy sounddevice/MIDI, timed `KeyboardPiano`, `MidiInput`, preset/skin libraries, `CanvasApp`, mouse capture and a real-SGR `HeadlessApp`.
- Widgets stay engine-independent. The shell owns engine events, parameter history, persistence, lifecycle and view state; the piano widget emits events through a callback.

## Integration decisions

- Piano geometry is computed once from each visible key's pitch and half-open cell rectangle. White-key regions are registered first and black-key regions afterward, matching the topmost drawn glyph. Mouse velocity is linear over the clicked key's own visible depth. Captured move/up events recalculate the pitch from their current cell, so glissando and release outside the keyboard use the same cell geometry as drawing.
- A shared instrument specification supplies its identity, engine factory, optional layout callback, and packaged factory assets. The shell composes this spec with the existing libraries and optional backends; it does not import any instrument package.
- Preset parameter changes enter the audio engine at its next internal block boundary. Instrument extras are included in the same engine-side preset request. Undo and redo are bounded UI histories of validated parameter values.
- CLI utilities use the same instrument spec and remain callable without opening an application or hardware device. The included sine instrument is a kit demo fixture, not an AURORA/LOOM/DRIFT dependency.
- MIDI, audio, and terminal cleanup are ordered so tracked note releases and panic happen before the audio backend closes, then MIDI closes, then prompt_toolkit returns terminal ownership to the caller.

## Qualification risks

- prompt_toolkit capture behavior must be verified by SGR sequences at every visible white and black key cell, including release outside bounds.
- Device and output failures must remain visible while keeping the null backend usable.
- CLI WAV output must be deterministic, PCM16 stereo, finite, and bounded without opening a terminal or device.
- Headless snapshots must not depend on wall-clock state, terminal size, or skin discovery order.
