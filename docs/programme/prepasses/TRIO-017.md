# TRIO-017 release qualification prepass

Date: 2026-11-14. Starting source: `357215781ba0b82694e62dd4d7ba1c3697ac3159`.
The live issue #17 and its comment were reconciled with main. There was no duplicate
open PR. Dependency repair PR #34 is merged; main workflow
[`39115306829`](https://github.com/techrote/tuisynth-codex/actions/runs/39115306829)
passed Ubuntu/Windows on Python 3.11/3.14. A fresh local baseline passed all 551
established tests: kit 407, AURORA 41, LOOM 48 and DRIFT 55 (Linux, Python 3.12.14).

## Owner campaign boundary

The 14 November owner mission supersedes autonomous merge/publication instructions
for this campaign. Deliver one Draft PR on HOLD. Do not merge, tag, publish a
GitHub/PyPI release, or close #17. Software qualification and physical acceptance
are separate. No sibling implementation repository or material was inspected.

## Implementation decisions

- Keep the four distribution/import identities, existing runtime dependency ranges,
  instrument separation and all accepted regression tests. Pin the qualified build
  and runtime toolchain in `requirements-release.txt`.
- Acquire dependency wheels explicitly, then run builds, clean installations and
  qualification offline. Build twice from independent exports of the exact committed
  Git blobs, fixing timestamps through `SOURCE_DATE_EPOCH`.
- Verify every packaged source/resource byte, metadata, entry point and wheel RECORD;
  install into a new virtual environment and exercise all four real commands outside
  the checkout, including every factory preset/skin self-test.
- Generate source/candidate ZIPs, four wheels, SHA256SUMS and machine-readable source
  and qualification records. The workflow has read-only repository permission and no
  publication step. All four CI lanes perform packaging and launcher qualification.
- Use small shell/cmd selectors with one shared Python launcher. First-run setup,
  installation identity, optional backends, recovery and repeated launches receive
  real subprocess tests. The candidate includes source, launchers and built wheels.
- Derive user controls, CLI flags, assets and frozen frames from the implementation.
  Keep manual device, listening, physical terminal and sustained CPU checks unfilled.

## Release audit defects

Inspecting real bindings exposed MIDI learn remaining armed after Escape, modal Tab
focus reaching background controls, ignored mouse clicks in shared list overlays,
and keyboard selections disappearing below the visible list. Repairs are scoped to
the shared shell/input layer and covered by real terminal-key/SGR regressions. No
synthesis algorithm or factory sound is changed.

## Parallel roles

Provider-native agents handle packaging/release, launchers, and documentation/control
verification. The primary agent owns integration, CI, release-audit repairs and the
final qualification campaign. A separate reviewer audits the assembled source.
Exact model/configuration and review findings are recorded in `docs/PROVENANCE.md`
and the PR; unexposed identifiers are not inferred.
