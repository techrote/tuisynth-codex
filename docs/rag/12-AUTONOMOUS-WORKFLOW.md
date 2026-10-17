---
corpus: trio-autonomous
document_id: TRIO-WORKFLOW
status: authority
---
# Autonomous workflow
The provider in `ATTEMPT.md` owns every phase. Subagents/model tiers may do prepass, implementation, debugging, review and release audit; sibling attempt may not be used.

Dependencies are same-attempt work, not external blockers. Issue comments are durable checkpoints; substantial prepasses may live under `docs/programme/prepasses/`.

Before merge review the complete diff against issue acceptance, **Read first** docs, existing tests, difference contract, regression lessons and packaging/platform effects. Prefer a different provider-native tier/config for review and record findings.

Substantive human design/code/debugging help is provenance. Routine repository settings or supplied physical evidence is recorded but distinct.

Do not abandon the programme for ordinary failures. Stop only for genuinely unavailable permission/credential, physical-only evidence, explicit owner decision or irreconcilable contract conflict; otherwise checkpoint and continue later.
