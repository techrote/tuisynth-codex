# [TRIO-006] Kit skins, colourways and ASCII-art assets

This GitHub issue is the autonomous execution prompt for **TRIO-006**. `AGENTS.md` is incorporated by reference and is mandatory, including reconciliation, branching, checkpoints, provenance, PR review, exact-head CI, merge, and post-merge verification.

## Depends on
TRIO-001 merged/green.

## Read first
1. `AGENTS.md`
2. `ATTEMPT.md`
3. `docs/programme/IMPLEMENTATION-PROGRAMME.md`
4. `docs/rag/12-AUTONOMOUS-WORKFLOW.md`
5. `docs/rag/13-BENCHMARK-PROVENANCE.md`
6. `docs/programme/issues/TRIO-006.md`
7. `docs/rag/05-SKINS-CONTRACT.md`
8. `docs/rag/04-TUI-UX-CONTRACT.md (Philosophy)`
9. `docs/rag/11-LESSONS-FROM-RECOVERY.md`

## Objective
Build the hardened semantic skin/art system that cannot crash the application on hostile content.

## Required implementation
Implement Style/Skin model, TOML loader with schema normalization, required semantic roles, palette/ramp/glyph/art validation, built-in guaranteed mono skin, skin library with factory/user precedence and live-cycle ids, NO_COLOR/mono handling. Enforce documented size/nesting/control/ANSI/double-width/glyph/art bounds. Bad content returns usable fallback + warnings, not arbitrary exceptions.

## Required tests and acceptance
- Complete valid skin resolves roles/ramps/art.
- Hostile corpus covering parse errors, binary/oversize/deep/wrong types, bad colors/schema, ANSI/control art, double-width glyphs, art/ramp bounds, bad ids and nonstring values.
- Library precedence, unknown fallback, cycling both directions.
- NO_COLOR forces ASCII-safe mono.
- Full CI green.

## Out of scope
Canvas rendering and per-instrument skins.

## Delivery
Complete the issue end-to-end. Open a PR titled `[TRIO-006] Kit skins, colourways and ASCII-art assets` with `Closes #<this issue>`; include exact test evidence, RAG/contract changes, limitations and role-based provenance. Use a provider-internal independent review tier/configuration where available. Merge only when the exact reviewed head is current and every required automated check is green; verify `main` CI after merge. If interrupted, post the `AGENTS.md` checkpoint before ending.
