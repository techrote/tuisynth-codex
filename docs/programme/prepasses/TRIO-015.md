# TRIO-015 prepass: shared sequencer and arpeggiator

## Reconciliation

- TRIO-015 is open, has no owner comments, and has no open duplicate PR.
- Its dependencies TRIO-010, TRIO-012 and TRIO-014 are merged. TRIO-014's post-merge CI run
  `39105918311` passed on merge commit `e220d7d95cedf5fac27751665e9f584db6399e0f`.
- Work branches from that current `main` commit on `trio-015-sequencer-arp`.
- The active issue and all listed Read first contracts were read before implementation. RAG 09 is
  the controlling behavior contract; TRIO-016 remains out of scope for this issue.

## Findings

- `Engine` already splits each fixed 256-frame block at event offsets and applies `Transport`
  events through a shared immutable event queue. The engine is the correct place to schedule
  sequencer/arp output so every input source uses the same note ownership rules.
- `Shell` routes computer-keyboard, piano and MIDI events through one hook. LOOM's chord mode
  intentionally suppresses direct `NoteOn` events while publishing held pitches; its router must
  additionally forward physical events only while the shared arp is enabled so the engine can
  capture input without playing the direct notes.
- AURORA's strict harmonic extras, LOOM's held-state router and DRIFT's empty private-extra schema
  mean shared sequencer preset data must be separated before calling instrument validators and
  instrument setters. The combined extras object must remain the one shell dirty/save/load state.
- The UI contract requires instrument-specific step visuals and captured SGR actions. A shared
  widget can preserve behavior while exposing style variants for spectral pillars, thread knots
  and pressure cells, with per-instrument layout and screen routing left in each instrument.
- prompt_toolkit maps legacy terminal F15 to a modified F3 convention, while its xterm
  `CSI 1;2R` form conflicts with cursor-position responses. The shared key adapter will normalize
  F15 to Shift+F3 and the headless driver will exercise that terminal encoding.

## Implementation and qualification plan

1. Add validated immutable Step/Pattern/Arpeggiator/SequenceConfig models and a block processor
   with anchored integer-frame timing, swing, probability, held-chord triggers, arp ordering,
   deterministic seeds and owned NoteOff releases.
2. Integrate the processor into `Engine`; merge sequencer configuration through shared preset
   validation, the shell extras state and the CLI preset library.
3. Add one reusable SGR step editor with three instrument motifs; integrate Shift+F3, Space,
   Escape, keyboard/mouse controls and instrument-specific screen labels.
4. Test both sample rates over at least 64 steps, tempo/swing changes, edit/stop/panic release,
   arp modes/rates/latch, preset round-trip, UI actions and separate golden snapshots.
5. Run all packages and clean-wheel smoke checks, perform a fresh highest-effort self-review, open
   the issue PR, monitor exact-head CI, squash-merge and verify post-merge `main` CI.

## Provenance

Codex desktop (GPT-6, configuration unknown) performed this prepass with the local repository,
Git, GitHub CLI, PowerShell and the pre-provisioned Python environment. No external sources,
sibling implementation artifacts or hardware were used.

## Implementation, qualification and review outcome

- Added immutable validated pattern/step/transport/arp models and an engine-owned block scheduler
  with anchored frame timing, swing, probability, held-note capture, seeded arp ordering and owned
  release tracking. Live Transport state is reflected in the shared config so stop/restart and
  subsequent edits cannot leave the scheduler and preset view out of sync.
- Integrated shared extras through engine, shell, preset library and CLI plumbing. Added one
  shared editor with spectral, thread and pressure motifs, plus per-instrument Shift+F3 routing,
  Space transport, mouse/keyboard twins, Escape restoration, snapshots and SGR coverage.
- Fresh highest-effort self-review against the issue, all Read first docs, full diff, default
  behavior, regression lessons and packaging boundaries found and fixed three issues: Transport
  events could leave saved `playing` stale; arp seed changes could reset the independent step
  probability stream; and sequencer Escape could leave hidden-widget focus or discard the prior
  instrument screen. No further findings remain. A separate provider review tier was unavailable
  under this run's collaboration policy.
- `tools/check.py --package all --packaging` passed: kit 360, AURORA 39, LOOM 45 and DRIFT 50
  tests (494 total), all four wheels built, installed-wheel import/resource/version/preset/skin/
  CLI checks passed, installed DRIFT selftest passed (8 presets, 4 skins, 16 offline render
  seconds), and offline render wrote 2,400 stereo frames at 48 kHz. After strengthening the UI
  tests for arrow/Enter/PageUp editing, the updated SGR UI suites also passed: AURORA 24, LOOM 21,
  DRIFT 9.
- Optional MIDI clock was omitted because the issue makes it conditional on fake-backend coverage.
  No physical audio, MIDI or terminal hardware was exercised; software CI is not physical
  acceptance.

Codex desktop (GPT-6, configuration unknown) performed implementation, debugging, qualification
and highest-effort self-review using Git/GitHub CLI, PowerShell and Python 3.12. No human design or
code intervention, external sources or sibling implementation artifacts were used.
