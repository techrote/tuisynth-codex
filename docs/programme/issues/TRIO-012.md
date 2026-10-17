# [TRIO-012] LOOM app: strum surface and vibrating strings

This issue is the autonomous execution prompt for **TRIO-012**. `AGENTS.md` is incorporated by reference and mandatory, including reconciliation, branching, checkpoints, provenance, PR review, exact-head CI, merge, and post-merge verification.

## Depends on
TRIO-008 and TRIO-011 merged/green.

## Read first
1. `AGENTS.md`
2. `ATTEMPT.md`
3. `docs/programme/IMPLEMENTATION-PROGRAMME.md`
4. `docs/rag/12-AUTONOMOUS-WORKFLOW.md`
5. `docs/rag/13-BENCHMARK-PROVENANCE.md`
6. `docs/programme/issues/TRIO-012.md`
7. `docs/rag/07-LOOM-SPEC.md (Strum surface, UI, UI tests)`
8. `docs/rag/00-CHARTER.md`
9. `docs/rag/04-TUI-UX-CONTRACT.md`
10. `docs/rag/05-SKINS-CONTRACT.md`

## Objective
Deliver playable LOOM as one instrument surface with animated strummable/bowable strings, sympathetic display, docked controls, short piano and distinct skins.

## Required implementation
- StringSurface visualizes telemetry displacement, string labels and bow markers; captured mouse path triggers every crossed string in order with velocity from crossing speed; bow mode on/off; right-click mute; complete keyboard twin.
- SympatheticColumn animates 12 resonators.
- One-surface layout with EXCITE/STRING/BODY/SYMPATHY/PLAY docked panels, short piano/chord label, F2/F3/F4/F5 focus/overlay behavior, compact 80x24 mode.
- In chord mode piano input changes strum tuning rather than directly sounding notes; direct mode plays notes.
- Four skins: rosewood, brass, indigo-loom, mono with string ramps and LOOM-specific art.
- Integrate shared shell/CLI without introducing AURORA tabs or DRIFT weather drawers.

## Required tests and acceptance
- Real-SGR drag across multiple string rows emits exactly one ordered event per crossing; faster drag => greater velocity. Bow capture/release and right-mute.
- Chord-vs-direct piano behavior and tuning labels.
- Animation magnitude follows telemetry and freezes in snapshots.
- Headless layout/focus/panel behavior; all skins warning-free.
- Golden 100x30 and compact 80x24 snapshots for every skin.
- loom --selftest/--render; CI green.

## Out of scope
Sequencer/modulation/post-FX.

## Delivery
Complete end-to-end. Open PR `[TRIO-012] LOOM app: strum surface and vibrating strings` with `Closes #<this issue>`; include exact tests, RAG changes, limitations and role-based provenance. Use a provider-internal independent review tier/configuration where available. Merge only when the exact reviewed head is current and all required automated checks are green; verify `main` CI. If interrupted, post the `AGENTS.md` checkpoint.
