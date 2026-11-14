# Keyboard and mouse reference

Generated sections are checked against runtime key-dispatch branches, exercised interaction regressions, the keyboard note map and existing instrument UI tests. Instrument-specific gestures are in [AURORA](../aurora/README.md), [LOOM](../loom/README.md) and [DRIFT](../drift/README.md). This is a software reference; physical terminal input compatibility remains an [owner acceptance test](ACCEPTANCE.md).

<!-- generated:controls:start -->

## Shared controls

Controls apply when no overlay or focused instrument control consumes the key. Click a control or use Tab/Shift+Tab to focus it. Escape clears focus. Ctrl+Q quits from every view, including overlays. Space belongs to transport outside MOD, even when the piano or LOOM strings are focused.

| Key or keys | Action |
| --- | --- |
| `F1` | Open help; arrows/PageUp/PageDown/Home/End or wheel scroll; Escape closes it. |
| `F2–F5` | Open the instrument areas listed in its guide. |
| `Shift+F3` | Open/focus the step sequencer. |
| `Shift+F4` | Open/focus modulation and the effects rack. |
| `F6 / Shift+F6` | Cycle skins forward / backward. |
| `F7` | Open MIDI input picker; arrows/wheel select, Enter or click connects. |
| `F8` | Open preset actions; arrows/wheel select, Enter or click loads, S saves as, R renames and D deletes a user preset. |
| `F9` | Panic: release sounding notes and clear held/latch state. |
| `Ctrl+P` | Open command palette; type a filter, arrows/wheel select, Enter or click runs. |
| `Ctrl+L` | Arm MIDI CC learn for the focused parameter (or first parameter when no parameter is focused); Escape cancels. |
| `Ctrl+Z / Ctrl+Y` | Undo / redo individual parameter edits recorded by the shell; this is not full-session undo. |
| `Escape` | Close an overlay, return from sequencer/MOD, or clear control focus. |
| `Space` | Start/stop the sequencer transport; in MOD, toggle the selected effect bypass. Overlays consume Space as their own input. |

Shared F7/F8 and command-palette rows support click-to-activate and wheel selection. Skin-preview rows support hover-to-preview, click/Enter to keep and Escape to restore. Keyboard selection stays visible while long lists scroll. Tab remains inside a modal overlay; F9 panic and Ctrl+Q quit remain available.

## Computer keyboard notes

Terminals do not send ordinary key-release events. A note closes after 450 ms without repeat; repeat extends its gate. Apostrophe toggles latch, where pressing the note key again releases it. `-` / `=` shift the computer-keyboard octave (−3…+3); `[` / `]` select velocity from 0.25, 0.4, 0.55, 0.7, 0.85, 1.0 (default 0.7). The table shows octave offset zero.

| Key | Note | MIDI number |
| --- | --- | --- |
| `z` | C3 | 48 |
| `s` | C#3 | 49 |
| `x` | D3 | 50 |
| `d` | D#3 | 51 |
| `c` | E3 | 52 |
| `v` | F3 | 53 |
| `g` | F#3 | 54 |
| `b` | G3 | 55 |
| `h` | G#3 | 56 |
| `n` | A3 | 57 |
| `j` | A#3 | 58 |
| `m` | B3 | 59 |
| `q` | C4 | 60 |
| `2` | C#4 | 61 |
| `w` | D4 | 62 |
| `3` | D#4 | 63 |
| `e` | E4 | 64 |
| `r` | F4 | 65 |
| `5` | F#4 | 66 |
| `t` | G4 | 67 |
| `6` | G#4 | 68 |
| `y` | A4 | 69 |
| `7` | A#4 | 70 |
| `u` | B4 | 71 |
| `i` | C5 | 72 |
| `9` | C#5 | 73 |
| `o` | D5 | 74 |
| `0` | D#5 | 75 |
| `p` | E5 | 76 |

## On-screen piano

| Key or keys | Action |
| --- | --- |
| `Left / Right` | Move the focused on-screen piano cursor. |
| `Up / Down` | Change on-screen piano octave. |
| `Enter` | Play the cursor note with a timed gate. |

| Mouse gesture | Action |
| --- | --- |
| Left press | Play with velocity set by click depth (0.35 at top, 1.0 at bottom). |
| Drag across keys | Glissando with the original velocity; release anywhere ends the captured note. |
| Right-click | Toggle a per-key latch. |
| Wheel | Shift the displayed piano octave. |

## Standard parameter controls

| Key or keys | Action |
| --- | --- |
| `Left/Down / Right/Up` | Decrease / increase by one control step. |
| `PageDown / PageUp` | Decrease / increase by ten control steps. |
| `Home / End` | Set minimum / maximum. |
| `Delete` | Restore the default. |

Click/drag changes a value, wheel adjusts it, and right-click resets it. Control-specific panels may use the different navigation documented in the instrument guide. Shift+drag belongs to terminal text selection. Ctrl+wheel is coarse only when the terminal reports the modifier.

## Sequencer and arpeggiator

Open with Shift+F3; Escape restores the preceding instrument area. These keys apply while its grid is focused. Letter commands take priority over computer-note keys in this focus. Step note, gate, pattern length and extra lanes are preset data; the v0.1 grid edits step enable, velocity and probability, tempo/swing, and arpeggiator choices.

| Key or keys | Action |
| --- | --- |
| `Left / Right` | Select previous / next step. |
| `Up / Down` | Select previous / next lane when multiple lanes exist. |
| `Enter` | Toggle the selected step. |
| `PageUp / PageDown` | Raise / lower selected-step velocity by 0.05. |
| `Space` | Start / stop transport. |
| `[ or - / ] or =` | Lower / raise tempo by 1 BPM (40–240). |
| `, / .` | Lower / raise swing by 0.02 (0–0.6). |
| `A` | Toggle arpeggiator. |
| `M` | Cycle up, down, updown, random, as-played arpeggio order. |
| `O` | Cycle arpeggio octave count 1–4. |
| `R` | Cycle arpeggio rate. |
| `L` | Toggle arpeggio latch. |

| Mouse gesture | Action |
| --- | --- |
| Click a step | Toggle it. |
| Drag a pressed step vertically | Set its velocity. |
| Right-click a step | Cycle probability through 0.25, 0.5, 0.75, 1.0. |
| Wheel over grid | Adjust tempo by 1 BPM per event. |

## Modulation and effects

Open with Shift+F4; Escape returns. Eight slots route valid sources to parameters or effect controls. Voice sources only list destinations that support voice modulation. The rack contains tremolo/autopan, ring-mod, phaser, tape, chorus, delay and reverb; each has mix/bypass and can be reordered. LFO/ModEnv waveform, rate and envelope settings are stored in preset extras; the v0.1 matrix UI edits routing and amounts.

| Key or keys | Action |
| --- | --- |
| `V` | Switch matrix / rack focus. |
| `Left / Right` | Select matrix slot, or effect unit with rack focus. |
| `Up / Down / R or Enter` | Previous / next source (R and Enter advance). |
| `T` | Cycle valid destinations for the selected source. |
| `+ or = / - or _` | Raise / lower route amount by 0.05 (−1…1). |
| `PageUp / PageDown` | Raise / lower route amount by 0.1. |
| `Delete / Backspace` | Clear selected route. |
| `B / Space` | Toggle selected effect bypass. |
| `[ / ]` | Move selected effect earlier / later in the rack. |
| `, or < / . or >` | Lower / raise selected effect mix by 0.05 (0…1). |

| Mouse gesture | Action |
| --- | --- |
| Click matrix source/slot cell | Choose source for that route. |
| Click destination detail row | Cycle a valid destination. |
| Drag amount row or wheel over matrix | Change bipolar route amount. |
| Right-click route | Clear it. |
| Click pedal / right-click pedal | Select the effect / toggle its bypass. |
| Drag pedal body | Move it within rack order. |
| Drag pedal mix row or wheel over pedal | Set wet mix. |

<!-- generated:controls:end -->
