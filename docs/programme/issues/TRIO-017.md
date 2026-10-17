# [TRIO-017] Packaging, launchers, documentation and v0.1 software release qualification

This issue is the autonomous execution prompt for **TRIO-017**. `AGENTS.md` is incorporated by reference and mandatory, including reconciliation, branching, checkpoints, provenance, PR review, exact-head CI, merge, and post-merge verification.

## Depends on
TRIO-016 merged/green (therefore all TRIO-001..016 complete).

## Read first
1. `AGENTS.md`
2. `ATTEMPT.md`
3. `docs/programme/IMPLEMENTATION-PROGRAMME.md`
4. `docs/rag/12-AUTONOMOUS-WORKFLOW.md`
5. `docs/rag/13-BENCHMARK-PROVENANCE.md`
6. `docs/programme/issues/TRIO-017.md`
7. `docs/rag/10-TESTING-CI-RELEASE.md`
8. `docs/rag/00-CHARTER.md`
9. `docs/rag/13-BENCHMARK-PROVENANCE.md`
10. `docs/ACCEPTANCE.md`
11. `docs/programme/IMPLEMENTATION-PROGRAMME.md`

## Objective
Turn the complete implementation into an installable, documented, reproducibly qualified v0.1 software release without pretending unperformed hardware/listening checks passed.

## Required implementation
- Finalize package data and clean-wheel tests: four wheels install together in fresh env; each CLI --selftest works outside source tree.
- POSIX and Windows launchers create/reuse a local venv on first run, install the four source/wheel packages plus optional audio/MIDI extras, pass through arguments and do not redo setup unnecessarily. Add launcher docs and syntax/smoke tests on both OS families.
- User docs: root overview, one README per instrument, install/launch/troubleshooting, exact keyboard/mouse tables generated or tested against real bindings, factory skins/presets, frozen text snapshots/screenshots.
- `docs/ACCEPTANCE.md` remains a human checklist for actual audio device, USB MIDI, Windows Terminal gestures, 10-minute stability/CPU/listening; do not auto-fill pass.
- CHANGELOG 0.1.0 lists all 17 completed issues.
- Release tool/workflow builds from the release revision/tag, clean-installs, runs all selftests, emits four wheels + SHA256SUMS, and creates/publishes a GitHub release if repository permissions allow.
- Perform a final provider-internal release audit of scope, difference contract, tests, provenance and known limitations.

## Required tests and acceptance
- Packaging metadata/versions/dependency pins/package data.
- Generated README key/mouse tables match implementation.
- POSIX shell syntax + launch smoke on Linux; .cmd launch smoke on Windows.
- Full four-lane GitHub CI with packaging/selftest green for exact release commit.
- Release tool output checksums reproducible for produced artifacts; installed selftests green.
- Verify provenance covers every issue/role that materially contributed and no binaries/credentials/generated local state were committed.
- Release notes state software-qualified; physical acceptance status comes only from docs/ACCEPTANCE.md.

## Out of scope
Bundled standalone Python executable, PyPI publication, or claiming manual hardware/listening results without evidence.

## Delivery
Complete end-to-end. Open PR `[TRIO-017] Packaging, launchers, documentation and v0.1 software release qualification` with `Closes #<this issue>`; include exact tests, RAG changes, limitations and role-based provenance. Use a provider-internal independent review tier/configuration where available. Merge only when the exact reviewed head is current and all required automated checks are green; verify `main` CI. If interrupted, post the `AGENTS.md` checkpoint.
