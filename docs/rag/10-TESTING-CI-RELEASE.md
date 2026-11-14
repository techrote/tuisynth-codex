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

All four lanes run normal checks, clean-wheel packaging, installed `--selftest` for
all four commands, and actual first/repeated source and wheel launcher checks.
Do not remove a platform/version to evade a real failure. Required checks must be
green for the exact reviewed PR head. Pull-request checkout selects the PR head
commit explicitly; evidence is named for that source, not a synthetic merge revision.

Each instrument has a generous offline performance regression gate for pathological loops; real-time headroom remains manual. Snapshots freeze seeds/clocks/telemetry and update only explicitly.

First complete release is 0.1.0. Wheels include presets/skins and are tested outside the checkout. TRIO-017 adds POSIX/Windows launchers, docs, changelog, checksums and release workflow. Automated green = software-qualified, not physically accepted.

## TRIO-017 candidate qualification

`requirements-release.txt` pins the qualified build/runtime environment. Dependency
acquisition is an explicit network-enabled setup step:
`python tools/release.py --prepare-wheelhouse .trio-ci/wheelhouse --extras audio,midi`.
Builds, package checks and launcher qualification then use that wheelhouse offline.
The optional backends are installed for software checks without opening devices;
their physical behavior still requires `docs/ACCEPTANCE.md`.

`python tools/check.py --package all --packaging --wheelhouse .trio-ci/wheelhouse`
preserves the developer entry point and uses the release tool's full payload,
metadata, clean-install and installed-command gates. The candidate command is
`python tools/release.py --revision HEAD --wheelhouse .trio-ci/wheelhouse --output dist/release`.
It requires committed, clean source, exports exact Git blobs twice, fixes the source
timestamp, compares independent clean builds, verifies wheel RECORD/source bytes,
and creates four wheels, source/candidate ZIPs, SHA256SUMS, SOURCE.json and
QUALIFICATION.json. Artifact checksums must verify before handoff.

The `CI` workflow supports an optional `workflow_dispatch` revision and uploads
unpublished review artifacts with read-only repository permissions. No job tags,
merges, creates a GitHub release or publishes to PyPI. For the 14 November 2026 owner
campaign, the resulting PR remains Draft/HOLD and #17 remains open until explicit
owner approval. This overrides the generic autonomous merge/publication steps.
