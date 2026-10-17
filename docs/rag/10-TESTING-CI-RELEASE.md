---
corpus: trio-autonomous
document_id: TRIO-TEST
status: authority
---
# Testing, CI, packaging and release
Layers: pure unit tests; offline DSP assertions; headless TUI tests with real SGR bytes + deterministic snapshots; clean-wheel installation/selftest; manual real audio/MIDI/Windows Terminal/listening acceptance. Automated tests never require devices/network.

TRIO-001 creates `python tools/check.py [--package kit|aurora|loom|drift|all] [--packaging] [--update-snapshots]`.

GitHub Actions is the merge gate on PR and `main`:
- Ubuntu / Python 3.11
- Ubuntu / Python 3.14
- Windows / Python 3.11
- Windows / Python 3.14

All lanes run normal checks; at least one Linux and one Windows lane run clean-wheel packaging + installed `--selftest`. Do not remove a platform/version to evade a real failure. Required checks must be green for the exact reviewed PR head.

Each instrument has a generous offline performance regression gate for pathological loops; real-time headroom remains manual. Snapshots freeze seeds/clocks/telemetry and update only explicitly.

First complete release is 0.1.0. Wheels include presets/skins and are tested outside the checkout. TRIO-017 adds POSIX/Windows launchers, docs, changelog, checksums and release workflow. Automated green = software-qualified, not physically accepted.
