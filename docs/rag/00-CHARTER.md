---
corpus: trio-autonomous
document_id: TRIO-CHARTER
status: authority
---
# TRIO charter
Build three co-installable terminal synths on shared `trio_kit`, deliberately different in synthesis, sound, gesture, visualizer, layout, skins and presets.

| | AURORA | LOOM | DRIFT |
|---|---|---|---|
| CLI | aurora | loom | drift |
| sound | evolving pads/choirs | plucked/strummed/bowed strings | breath/wind/vowel clouds |
| synthesis | spectral PADsynth | waveguides + body + sympathetic bank | granular + formants |
| gesture | paint harmonics | strum/bow strings | steer weather field |
| visualizer | spectrum waterfall | vibrating strings | live grains + isobars |
| screen | tabs | one surface+docked panels | field+drawers |
| keyboard | full-width | short/chord-oriented | compact HUD |

**Difference contract:** shared infrastructure goes in `trio_kit`; instrument identity never does. Reject convergence on the table above.

Shared requirements: mouse-first + keyboard twin for every action; exact mouse-clickable piano note-off/velocity/gliss; computer keys; optional robust USB MIDI + CC learn; artistic semantic skins with mono/ascii fallback; `--no-audio`, `--selftest`, offline WAV and snapshots; finite safe master output; validated atomic presets/user data; mandatory sequencer/arpeggiator and modulation/post-FX; clean wheels, launchers, docs, Linux/Windows CI, manual acceptance checklist.

Non-goals: GUI, VST/CLAP, audio input, sample import, network features, bundled Python executable, multi-timbral MIDI, microtonal files.
