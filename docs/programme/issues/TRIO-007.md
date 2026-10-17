# [TRIO-007] Kit TUI canvas, mouse, widgets and headless SGR driver

This GitHub issue is the autonomous execution prompt for **TRIO-007**. `AGENTS.md` is incorporated by reference and is mandatory, including reconciliation, branching, checkpoints, provenance, PR review, exact-head CI, merge, and post-merge verification.

## Depends on
TRIO-002 and TRIO-006 merged/green.

## Read first
1. `AGENTS.md`
2. `ATTEMPT.md`
3. `docs/programme/IMPLEMENTATION-PROGRAMME.md`
4. `docs/rag/12-AUTONOMOUS-WORKFLOW.md`
5. `docs/rag/13-BENCHMARK-PROVENANCE.md`
6. `docs/programme/issues/TRIO-007.md`
7. `docs/rag/04-TUI-UX-CONTRACT.md (Philosophy, Rendering, Mouse, Widgets, Headless driver)`
8. `docs/rag/05-SKINS-CONTRACT.md (roles/colour depth)`
9. `docs/rag/11-LESSONS-FROM-RECOVERY.md`

## Objective
Implement the terminal drawing/interaction substrate with exact hit maps, capture/drag, keyboard-equivalent widgets and headless real-SGR input testing.

## Required implementation
- Cell Canvas with clipping, single-cell width safety, drawing primitives, semantic roles, plain-text snapshots and hit rectangles.
- HitMap topmost-wins; MouseRouter with capture continuing outside widget until release, wheel/right-click/hover; document coordinate conventions.
- FocusRing and reusable Fader/Knob/Toggle/Choice/XYPad/Meter/Button/TextField/ListBox/Tabs widgets. Param widgets call change callbacks and never import engine/DSP.
- prompt_toolkit full-screen CanvasApp, throttled invalidation, render-error panel that keeps input/quit alive.
- HeadlessApp using pipe input/DummyOutput; inject actual SGR bytes, keys, drag/release/wheel and expose frame/event evidence.

## Required tests and acceptance
- Canvas primitives/clipping/text/double-width handling.
- Hit map every cell + overlap.
- Real SGR clicks across button grid proving 1-based/0-based mapping; capture/release outside; wheel/right reset.
- Keyboard twins and tab order for all controls; mouse monotonic mapping.
- Render exception produces error panel but quit still works.
- Deterministic widget-demo snapshots at 100x30 and 80x24/mono.
- CI green.

## Out of scope
On-screen piano/app shell/instrument layouts.

## Delivery
Complete the issue end-to-end. Open a PR titled `[TRIO-007] Kit TUI canvas, mouse, widgets and headless SGR driver` with `Closes #<this issue>`; include exact test evidence, RAG/contract changes, limitations and role-based provenance. Use a provider-internal independent review tier/configuration where available. Merge only when the exact reviewed head is current and every required automated check is green; verify `main` CI after merge. If interrupted, post the `AGENTS.md` checkpoint before ending.
