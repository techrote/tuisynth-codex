# TRIO implementation programme

Objective: provider in `ATTEMPT.md` completes all phases end-to-end through issue -> implementation/tests -> PR -> CI repair -> provider-internal review -> merge -> main verification.

```text
001 foundation+CI
 ├─002 params/presets─003 engine─005 input────────────┐
 ├─004 DSP────────────────────────────────────────────┤
 └─006 skins─007 TUI─008 shell/piano─────────────────┤
 003+004 ->009 AURORA engine ->010 AURORA app        │
          ->011 LOOM engine   ->012 LOOM app          │
          ->013 DRIFT engine  ->014 DRIFT app         │
 010+012+014 ->015 sequencer/arp ->016 modulation/FX ->017 release
```

| ID | Outcome |
|---|---|
|001|co-installable skeleton, check tool, hosted CI|
|002|strict params/morph/presets|
|003|events/voices/engine/master/backends|
|004|shared DSP|
|005|computer keyboard + MIDI|
|006|hardened skins/art|
|007|canvas/hitmap/widgets/real-SGR driver|
|008|shell, on-screen piano, CLI/render/selftest/snapshot|
|009/010|AURORA engine/app|
|011/012|LOOM engine/app|
|013/014|DRIFT engine/app|
|015|sample-accurate sequencer/arpeggiator|
|016|mod sources/matrix/post-FX rack|
|017|clean wheels, launchers, docs, checksums/release/acceptance handoff|

Safe subagent parallelism after dependencies: 002/004/006 after 001; three engines after 003+004. Merges always reconcile current main.

Per issue done: dependencies merged/green; full behavior + tests; prior tests green; RAG changes documented; provenance recorded; exact reviewed PR head required checks green; merged; main push CI green; no inferred physical claims.

Programme done: all 17 merged/closed, four-lane software qualification and installed-wheel selftests green, release/checksums produced, no known blocking software defects, manual acceptance explicitly separate.
