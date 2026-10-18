# TRIO-005 implementation prepass

## Live-state reconciliation

- Issue #5 is open without owner comments or duplicate pull requests.
- Its dependency TRIO-003 is merged and green. Current `main` is `3c982f3`, including
  TRIO-004, whose post-merge four-lane CI is green.
- The implementation branch starts from that verified `main` revision.

## Contract reconciliation

- `docs/rag/03-INPUT-CONTRACT.md` specifies exact key rows, gate timing, octave and velocity
  ranges, MIDI channel filtering, and a two-second reconnect poll. Issue #5 explicitly excludes
  the on-screen keyboard and shell MIDI picker UI while still requiring selectable ports and
  reconnection. This issue will expose selection/reconnection through the input API; the picker
  UI remains for later shell work.
- The event contract requires each producer to retain note-id ownership across octave changes.
  Keyboard and MIDI adapters therefore retain note IDs for each active key and MIDI
  `(channel, note)` pair; they share a process-wide default allocator and also accept an injected
  `NoteIds` allocator when an application needs an isolated engine scope.
- The pure MIDI parser produces channel-aware note commands. `MidiNoteMap` translates them into
  engine `NoteOn`/`NoteOff` events and releases an older instance before reusing the same MIDI
  `(channel, note)` key.
- Optional RtMidi code imports `rtmidi` only when connecting. CI uses a fake backend and never
  opens physical devices. The official API documents `get_ports()`, `MidiIn.set_callback()`,
  callback message/delta-time tuples, `ignore_types()`, and `close_port()`:
  https://spotlightkid.github.io/python-rtmidi/rtmidi.html
- CC learn persists a versioned binding map through a same-directory flushed temporary file and
  atomic replace. Invalid or corrupt files load as an empty map with a warning.

## Qualification plan

- Inject times into `KeyboardPiano` and cover both exact pitch rows, auto-repeat, timeout,
  latch, action limits, panic, and original note-id release after octave changes.
- Test raw MIDI byte parsing without a device, including zero-velocity note-off, both bend
  extremes and center, channel filters, controller mappings, real-time/SysEx ignore, and malformed
  message counts.
- Exercise repeated same-note ownership and sustain/panic mapping, then fake backend selection,
  callbacks, missing dependency, disappearance, reconnection, and cleanup.
- Exercise CC learn arming, first-CC binding, persistence, clearing, and corrupt-map recovery.

## Review findings

- Keyboard and MIDI producers use one process-wide `NoteIds` allocator by default; callers can
  inject an allocator to scope IDs to a particular engine.
- Realtime bytes, including System Reset (`0xFF`), are ignored even when interleaved with a
  channel message. CC learn refuses a 513th distinct binding because the reader caps valid maps
  at 512 entries.
- Port disconnection or switching releases only the MIDI adapter's note IDs and clears its
  sustain state when needed; this avoids issuing a global panic that would cut off keyboard notes.
- Disconnecting or switching the MIDI port releases only note ids owned by that input and turns
  sustain off if that input had enabled it; global `Panic` remains for explicit panic controls.
