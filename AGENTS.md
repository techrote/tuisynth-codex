# Autonomous TRIO execution contract

This is one independent provider-owned attempt of the complete TRIO programme. Read `ATTEMPT.md`, then the active issue and its **Read first** documents.

## Authority
1. Current `main` code/tests.
2. Active GitHub issue and later owner comments.
3. This file.
4. Referenced `docs/rag/` contracts.
5. `docs/programme/IMPLEMENTATION-PROGRAMME.md`.

If code and a contract conflict, reconcile explicitly and update the relevant RAG document in the same PR when the contract legitimately changes.

## Independence and delegation
- Never inspect/copy/query the sibling implementation repository, its issues, PRs, branches, artifacts, reviews or releases.
- Public technical references and historical `techrote/tuisynth` material may be used only as background where locally referenced.
- Provider-native subagents/model tiers are allowed for research/prepass, implementation, debugging, testing and review.
- Record every materially contributing model/tool in `docs/PROVENANCE.md` and the PR.
- Prefer review by a different Codex tier/configuration. If unavailable, do a fresh highest-effort self-review and record that.

## Per-issue lifecycle
1. Reconcile `main`, issue/comments, dependency PRs and open duplicate work; read every **Read first** document.
2. Dependencies are work this same attempt owns. Finish them; never bypass the graph.
3. Perform useful prepasses and record durable findings in the issue or `docs/programme/prepasses/`.
4. Branch `trio-0NN-<slug>` from current `main`; prefix commits `TRIO-0NN:`.
5. Implement complete scope + meaningful tests. Never weaken/delete/skip/xfail tests merely for green.
6. Run relevant local/device-free checks, push, and open `[TRIO-0NN] <title>` PR with `Closes #N`.
7. PR body: summary, exact tests, contract changes, limitations, provenance, manual/hardware checks not exercised.
8. Monitor every required check on the exact PR head; fix deterministic/root-cause failures. Reruns are for infrastructure flakiness, not hiding defects.
9. Review full diff against issue, RAG, regression lessons and platform/packaging effects. Resolve blocking findings.
10. Update with `main`; required checks must be green for the exact reviewed head.
11. Squash-merge unless live policy says otherwise; verify `main` push CI. If merge makes main red, reopen/repair immediately under the same stable ID.
12. Close only after merged software acceptance. Never claim physical acceptance from CI.

## Interrupted work
Before ending incomplete work, post this issue checkpoint:
```text
STATUS: in-progress | blocked | ready-for-review
ISSUE: TRIO-0NN
HEAD: <sha>
PHASE: reconcile | prepass | implementation | qualification | review | repair
NEXT: <single concrete action>
BLOCKERS: <none or exact blocker>
LAST GREEN: <checks + revision>
OPEN FINDINGS:
- ...
PROVENANCE SINCE LAST CHECKPOINT:
- <model/tool role>
```
Resume only after reconciling live state.

## General rules
Python >=3.11. Tests/CI require no real audio/MIDI devices, secrets, paid services or network. Optional hardware dependencies fail to usable device-free behavior. Do not commit venvs, caches, generated audio/builds, credentials or machine state. Instruments do not import each other. Shared behavior belongs in `trio_kit`; identity stays instrument-specific. Do not add a licence without owner choice. Physical acceptance stays in `docs/ACCEPTANCE.md`.

## Completion
All 17 issues are mandatory, including TRIO-015/016. Programme completion requires merged green PRs, release software qualification and explicit separation of unperformed physical acceptance.
