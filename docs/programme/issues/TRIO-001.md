# [TRIO-001] Workspace foundation, packaging skeleton and hosted CI

This GitHub issue is the autonomous execution prompt for **TRIO-001**. `AGENTS.md` is incorporated by reference and is mandatory, including reconciliation, branching, checkpoints, provenance, PR review, exact-head CI, merge, and post-merge verification.

## Depends on
None.

## Read first
1. `AGENTS.md`
2. `ATTEMPT.md`
3. `docs/programme/IMPLEMENTATION-PROGRAMME.md`
4. `docs/rag/12-AUTONOMOUS-WORKFLOW.md`
5. `docs/rag/13-BENCHMARK-PROVENANCE.md`
6. `docs/programme/issues/TRIO-001.md`
7. `docs/rag/01-ARCHITECTURE.md`
8. `docs/rag/10-TESTING-CI-RELEASE.md`
9. `docs/rag/11-LESSONS-FROM-RECOVERY.md`

## Objective
Create the executable project foundation before any synth/DSP feature work: four uniquely named co-installable Python distributions, a single test/packaging entry point, and GitHub Actions qualification on Linux and Windows.

## Required implementation
- Create `kit/`, `aurora/`, `loom/`, `drift/` package skeletons for `trio-kit`, `trio-aurora`, `trio-loom`, `trio-drift`; imports `trio_kit`, `trio_aurora`, `trio_loom`, `trio_drift`; CLIs `aurora`, `loom`, `drift`; version 0.1.0.
- Python >=3.11. Development requirements pin the versions used by CI. Runtime kit depends on NumPy/SciPy/prompt_toolkit/wcwidth; audio/MIDI extras remain optional/lazy.
- Add root `tools/check.py`: select package/all, run pytest in subprocesses, optional clean-wheel packaging/install checks, optional snapshot update. Non-zero on any failure.
- Add `.github/workflows/ci.yml` on pull_request + main push with Ubuntu/Windows x Python 3.11/3.14. At least one lane per OS performs clean-wheel install and installed CLI smoke/selftest as soon as selftest exists.
- Add .gitignore rules for venv/cache/build/audio/generated CI data.
- Keep package data declarations ready for future presets/skins and ensure all four editable packages can coexist.

## Required tests and acceptance
- Verify unique distribution/import names and version metadata.
- AST/static test that instrument packages do not import one another.
- Verify workflow contains all four required OS/Python lanes and least-privilege permissions.
- Verify `tools/check.py` propagates pass/fail and package selection correctly.
- Build/install wheel skeletons in a clean environment and run each `--version`.
- PR required checks green on exact reviewed head; main push checks green after merge.

## Out of scope
Actual synth, DSP, MIDI or TUI behavior.

## Delivery
Complete the issue end-to-end. Open a PR titled `[TRIO-001] Workspace foundation, packaging skeleton and hosted CI` with `Closes #<this issue>`; include exact test evidence, RAG/contract changes, limitations and role-based provenance. Use a provider-internal independent review tier/configuration where available. Merge only when the exact reviewed head is current and every required automated check is green; verify `main` CI after merge. If interrupted, post the `AGENTS.md` checkpoint before ending.
