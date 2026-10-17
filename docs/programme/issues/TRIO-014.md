# [TRIO-014] DRIFT app: weather map and grain particles

This issue is the autonomous execution prompt for **TRIO-014**. `AGENTS.md` is incorporated by reference and mandatory, including reconciliation, branching, checkpoints, provenance, PR review, exact-head CI, merge, and post-merge verification.

## Depends on
TRIO-008 and TRIO-013 merged/green.

## Read first
1. `AGENTS.md`
2. `ATTEMPT.md`
3. `docs/programme/IMPLEMENTATION-PROGRAMME.md`
4. `docs/rag/12-AUTONOMOUS-WORKFLOW.md`
5. `docs/rag/13-BENCHMARK-PROVENANCE.md`
6. `docs/programme/issues/TRIO-014.md`
7. `docs/rag/08-DRIFT-SPEC.md (Field, UI, UI tests)`
8. `docs/rag/00-CHARTER.md`
9. `docs/rag/04-TUI-UX-CONTRACT.md`
10. `docs/rag/05-SKINS-CONTRACT.md`

## Objective
Deliver playable DRIFT as a full-screen weather field whose cursor steers synthesis and whose foreground particles represent real active grains.

## Required implementation
- WeatherMap seeded deterministic isobars + telemetry grain particles; x/y storm cursor; labels A/E/I/O/U and storm/calm.
- Captured left-drag maps path to field.x/y; hold activates gust until release; right-click recentres; wheel density; complete keyboard twin.
- Grain and Air drawers are pop-over HUDs with one open at a time; Esc closes; compact piano/meters stay visible.
- Full-screen map + F3/F4 drawers/F5 library; compact 80x24 layout.
- Four skins: squall, desert-haze, monsoon, mono with DRIFT-specific logo/isobar/grain/cursor art and ramps.
- Preserve DRIFT field/drawer identity; do not adopt AURORA tabs/LOOM string surface.

## Required tests and acceptance
- Real-SGR drag emits field values matching path and y orientation; hold/release gust; right recenter; wheel density; keyboard equivalents.
- Drawn particle count matches telemetry when cells permit; amplitude glyph mapping; isobars deterministic in snapshot mode.
- Drawer mutual exclusion/Esc and controls.
- Headless full/compact app, all skins warning-free, golden snapshots with/without drawer.
- drift --selftest/--render; CI green.

## Out of scope
Sequencer/modulation/post-FX.

## Delivery
Complete end-to-end. Open PR `[TRIO-014] DRIFT app: weather map and grain particles` with `Closes #<this issue>`; include exact tests, RAG changes, limitations and role-based provenance. Use a provider-internal independent review tier/configuration where available. Merge only when the exact reviewed head is current and all required automated checks are green; verify `main` CI. If interrupted, post the `AGENTS.md` checkpoint.
