# [TRIO-002] Kit parameter registry, validation and presets

This GitHub issue is the autonomous execution prompt for **TRIO-002**. `AGENTS.md` is incorporated by reference and is mandatory, including reconciliation, branching, checkpoints, provenance, PR review, exact-head CI, merge, and post-merge verification.

## Depends on
TRIO-001 merged/green.

## Read first
1. `AGENTS.md`
2. `ATTEMPT.md`
3. `docs/programme/IMPLEMENTATION-PROGRAMME.md`
4. `docs/rag/12-AUTONOMOUS-WORKFLOW.md`
5. `docs/rag/13-BENCHMARK-PROVENANCE.md`
6. `docs/programme/issues/TRIO-002.md`
7. `docs/rag/02-AUDIO-ENGINE-CONTRACT.md (Parameters, Presets)`
8. `docs/rag/01-ARCHITECTURE.md (user data)`
9. `docs/rag/11-LESSONS-FROM-RECOVERY.md`

## Objective
Implement the shared strictly validated parameter registry, morphing and schema-versioned preset/user-data system.

## Required implementation
- Implement `ParamSpec`/`ParamRegistry` behavior exactly from TRIO-ENGINE: continuous/discrete/choice, linear/log/exp mapping, formatting, clamping with warnings, strict rejection of bool/string/None/NaN/Inf, defaults and complete validation.
- Morph continuous parameters in their curve domain; discrete/choice switch at t=0.5.
- Implement `trio-preset/1` parse/serialize, instrument id validation, extras validator hook, factory/user library precedence, save/rename/delete semantics and atomic user-data writes.
- Structural garbage must surface `ParamError`/`PresetError`, never incidental TypeError/AttributeError.

## Required tests and acceptance
- Invalid ParamSpec construction and hostile values.
- Morph boundaries t={0,.25,.49,.5,.75,1}; linear/log/exp round-trips; formatting rules.
- Valid preset fills defaults; unknown keys warn; wrong synth/bad id reject.
- Hostile preset corpus: wrong root/field types, deep/oversize structures, invalid numeric values, corrupt encoding/data.
- Atomic save/reload, overwrite refusal, factory deletion refusal, user shadow/list order.
- Full project checks and clean package tests green.

## Out of scope
Engine/events/DSP/UI or instrument parameter registries.

## Delivery
Complete the issue end-to-end. Open a PR titled `[TRIO-002] Kit parameter registry, validation and presets` with `Closes #<this issue>`; include exact test evidence, RAG/contract changes, limitations and role-based provenance. Use a provider-internal independent review tier/configuration where available. Merge only when the exact reviewed head is current and every required automated check is green; verify `main` CI after merge. If interrupted, post the `AGENTS.md` checkpoint before ending.
