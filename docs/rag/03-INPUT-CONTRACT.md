---
corpus: tuisynth
programme: trio
document_id: TRIO-INPUT
status: authority
---
# Input contract: computer keyboard, on-screen keyboard and USB MIDI

## Computer keyboard (TRIO-005)

Terminals report key presses but **not key releases**. The kit therefore uses timed gates.

Chromatic two-row tracker layout, base note C3 (MIDI 48) at octave offset 0:

| Row | Keys (in pitch order) | Notes |
|---|---|---|
| Lower | `z s x d c v g b h n j m` | C3 .. B3 (`s d g h j` are black keys) |
| Upper | `q 2 w 3 e r 5 t 6 y 7 u i 9 o 0 p` | C4 .. E5 (`2 3 5 6 7 9 0` are black keys) |

| Key | Action |
|---|---|
| `-` / `=` | octave down / up (range -3..+3) |
| `[` / `]` | keyboard velocity down / up (steps 0.25, 0.4, 0.55, 0.7, 0.85, 1.0; default 0.7) |
| `'` | latch toggle: when on, a note key toggles its note on/off instead of timing out |
| `F9` | panic (all notes off) |

- A press sends `NoteOn`; auto-repeat presses of the same key extend the gate. If no repeat
  arrives within `gate_ms` (default 450 ms, configurable 150-2000), a `NoteOff` is sent.
- Note keys are active whenever no text field has focus. The status line shows octave,
  velocity and latch state.
- Implementation: a pure `KeyboardPiano` class with `press(key, now) -> events` and
  `tick(now) -> events`, testable without a terminal. `now` is monotonic seconds; the active
  pitch and note id are captured at the first press, so octave changes affect only new notes.
- Auto-repeat extends the existing timed note's deadline without another NoteOn. While latch is
  enabled, a first press creates an untimed note and another press toggles it off. Turning latch
  off releases any notes created by latch mode. `release_all()` emits NoteOffs; F9 clears local
  note tracking and emits a global `Panic`.

## On-screen keyboard widget (TRIO-008)

- Drawn from box-drawing glyphs; white keys 3 cells wide, black keys 2 cells wide occupying
  the upper part of the key area. The hit map must make every visible cell map to exactly the
  key drawn there (no off-by-one between rendering and hit-testing).
- **Mouse down** on a key: `NoteOn` with velocity from click depth (top row of the key = 0.35,
  bottom row = 1.0, linear in between). **Mouse up** anywhere: `NoteOff` for that press.
- **Drag** across keys: glissando. Leaving a key sends `NoteOff` for it and `NoteOn` for the
  new key (velocity kept from the original press). Instruments that support `retarget` may
  do legato instead when the instrument declares `legato_glide=True`.
- **Right-click** a key toggles latch for that key. **Wheel** over the keyboard shifts its
  octave. Held/latched/MIDI-sounding notes are highlighted using skin roles `pressed` and
  `selected`.
- Keyboard twin: with the widget focused, `Left`/`Right` move a key cursor, `Enter` plays the
  cursor key (timed gate), `Up`/`Down` change octave.
- Headless acceptance: tests inject real SGR mouse sequences (`ESC [ < b ; x ; y M` and `m`)
  through prompt_toolkit pipe input and assert the exact notes and velocities produced. This
  is the contract the recovered PadSynth failed (PAD-001).

## USB MIDI (TRIO-005)

- Optional dependency `python-rtmidi`, imported lazily. If missing or failing, the input service
  reports `MIDI: unavailable` and keyboard/offline operation remains available.
- Pure parser `parse_midi(message: bytes|list[int]) -> list[MidiCommand]`, tested with byte
  sequences, handling: Note On (velocity 0 = Note Off), Note Off, CC 64 sustain (>= 64 on),
  CC 1 mod wheel (0..1), Pitch Bend (14-bit, +-2 semitones default, configurable 1-12),
  CC 120 and CC 123 -> `Panic`, Channel filter (omni default or 1-16), ignoring clock,
  active sensing and SysEx without error. Raw `ControlChange` values accompany semantic CC
  events for learn/mapping. Note messages are channel-aware `MidiNoteOn`/`MidiNoteOff`
  commands until `MidiNoteMap` assigns engine note ids; other commands are engine events.
  Malformed/short messages are ignored and counted by `MidiParser`.
- MIDI note numbers map to `note_id`s inside a `MidiNoteMap` so repeated Note On of the same
  `(channel, note)` pair without Note Off first releases the previous voice (standard MIDI
  behaviour). Keyboard and MIDI adapters share a process-wide default `NoteIds` allocator and
  accept an injected allocator when an application needs an isolated engine scope.
- `MidiInput` accepts a port index or name substring and can change selection through
  `select_port()`. It polls every two seconds and reconnects to the same port name after it
  returns. Disconnecting or changing ports releases only its tracked MIDI note ids and clears
  sustain if that MIDI input had turned it on; this does not panic other note producers. Its
  status reports the connected port or a readable unavailable reason. `FakeMidiBackend` exercises
  delivery and reconnects without hardware.
- **CC learn**: `CcLearnMap.arm(control_id)` arms the next incoming `ControlChange`; `feed`,
  `lookup`, and `clear` support the controller binding flow. Bindings use schema
  `trio-midi-map/1` in `midi-map.json` under per-instrument user data, written atomically. Corrupt
  maps warn and load empty. Shell `Ctrl+L`, `--midi`, and MIDI picker UI are integrated with the
  later shell issue; this issue supplies the pure and backend APIs only.
- Fake backend `FakeMidiPort` for tests and CI; no test opens a real MIDI port.
