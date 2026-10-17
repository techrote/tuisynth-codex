# [TRIO-010] AURORA app: harmonic painter and aurora waterfall

This issue is the autonomous execution prompt for **TRIO-010**. `AGENTS.md` is incorporated by reference and mandatory, including reconciliation, branching, checkpoints, provenance, PR review, exact-head CI, merge, and post-merge verification.

## Depends on
TRIO-008 and TRIO-009 merged/green.

## Read first
1. `AGENTS.md`
2. `ATTEMPT.md`
3. `docs/programme/IMPLEMENTATION-PROGRAMME.md`
4. `docs/rag/12-AUTONOMOUS-WORKFLOW.md`
5. `docs/rag/13-BENCHMARK-PROVENANCE.md`
6. `docs/programme/issues/TRIO-010.md`
7. `docs/rag/06-AURORA-SPEC.md (UI + UI tests)`
8. `docs/rag/00-CHARTER.md`
9. `docs/rag/04-TUI-UX-CONTRACT.md`
10. `docs/rag/05-SKINS-CONTRACT.md`

## Objective
Deliver a playable, visually distinct AURORA terminal instrument with harmonic painter, live spectral waterfall, full-width piano, factory skins and shared CLI.

## Required implementation
- Implement AURORA layout/screens PLAY, SHAPE, SPACE, LIBRARY, full and compact variants.
- Harmonic painter: 64/32 bars, interpolated drag painting, right-drag erase, wheel fine adjust, keyboard twin including random/even/odd commands; updates engine harmonics extras safely.
- Waterfall driven by AURORA telemetry; silent/idle behavior and deterministic frozen snapshot mode.
- Integrate shared piano/shell/overlays/CLI through an AURORA InstrumentSpec.
- Four skins: borealis, solar-wind, polar-night, mono; instrument-specific logo/density/aurora art; zero load warnings.
- Preserve AURORA-specific tabbed-screen identity; do not reuse LOOM/DRIFT interaction models.

## Required tests and acceptance
- Real-SGR painter drag has no gaps; erase and keyboard twin produce equivalent state.
- Waterfall density monotonic/silent when no voices/deterministic snapshot.
- Headless app F2..F5, piano note on/off, skin switching, Ctrl+Q.
- All skins load warning-free; required roles/art fit.
- Golden PLAY/SHAPE 100x30 plus compact 80x24 for all skins.
- CLI aurora --selftest and --render from package; no worker thread leaks.
- Full matrix CI green.

## Out of scope
Sequencer/modulation/post-FX (TRIO-015/016).

## Delivery
Complete end-to-end. Open PR `[TRIO-010] AURORA app: harmonic painter and aurora waterfall` with `Closes #<this issue>`; include exact tests, RAG changes, limitations and role-based provenance. Use a provider-internal independent review tier/configuration where available. Merge only when the exact reviewed head is current and all required automated checks are green; verify `main` CI. If interrupted, post the `AGENTS.md` checkpoint.
