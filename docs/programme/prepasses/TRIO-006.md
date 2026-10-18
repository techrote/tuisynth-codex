# TRIO-006 implementation prepass

## Live-state reconciliation

- Issue #6 is open without owner comments or duplicate open pull requests.
- Its dependency TRIO-001 is merged; current `main` is `6c4d002`, and the push CI for that exact
  revision passed all four required platform/Python lanes.
- The working branch was created from that exact `origin/main` revision.
- The kit has no skin model, parser, factory asset, or skin tests yet. `kit/pyproject.toml`
  already declares a skin data pattern, and the foundation test enforces it.

## Contract reconciliation

- Issue #6 explicitly excludes per-instrument skins, while the RAG names AURORA, LOOM, and DRIFT
  factory colourways. The shared kit issue will deliver the common loader/library and guaranteed
  mono skin only. The named instrument assets belong to TRIO-010, TRIO-012, and TRIO-014; the RAG
  now records this scope split.
- The local RAG is authoritative for normalized skin fields, required semantic roles, and hostile
  input bounds. Public historical `techrote/tuisynth` sources are optional background only. The
  recovered loader accepted schema 1.0 and mapped old role names `status_ok`, `status_warn`,
  `status_err`, `sel`, `focus`, and `press` to the shared roles. The new loader will normalize
  those aliases and the legacy nested ramp/glyph/art representation without adopting unrelated
  historical tables.
- Invalid source documents must return a usable mono skin plus warnings. Invalid individual
  sections should be omitted or use documented text fallback when the rest of the skin is usable.
- User skin IDs override same-ID factory skins; the `mono` ID is reserved to keep the fallback
  guaranteed safe. `NO_COLOR` and explicit mono mode pin the library to `mono`.

## Qualification plan

- Validate complete current-schema and legacy-schema TOML fixtures, role resolution, ramps, glyphs,
  art and ASCII fallback behavior.
- Test parse/binary/size/depth/schema/type/id/color failures and art control/ANSI/double-width/
  size limits, confirming no malformed source raises.
- Test factory/user precedence, instrument filtering, unknown selection fallback, bidirectional
  cycling, and `NO_COLOR`/mono pinning.
- Run the full four-package device-free suite and clean-wheel/install/CLI smoke qualification.
