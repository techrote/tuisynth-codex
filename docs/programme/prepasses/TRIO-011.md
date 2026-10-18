# TRIO-011 prepass — LOOM waveguide engine

## Reconciliation

- Issue #11 is open, has no owner comments, and has no competing open PR.
- Required dependencies TRIO-003 and TRIO-004 are merged to `main`; TRIO-010's merge commit `1bdefe0f154dc6584fc9a7bc2b58c4857d88aa92` has a successful post-merge CI matrix.
- Scope is LOOM engine/DSP/presets and shared-engine changes only where needed for the specified dynamic pluck/bow polyphony. LOOM screens and skins remain TRIO-012.
- Main has been reconciled and the issue branch is `trio-011-loom-waveguide`.

## Design findings

- The shared `VoiceManager` has a fixed capacity. It can support LOOM's mode-dependent 8-pluck/4-bow limit with a bounded optional `instrument.voice_limit(params)` hook; shrinking the limit moves removed slots to existing short fade tails, while expansion reuses the original preallocated capacity. Auxiliary string events also need the current note-voice count and engine seed, so the shared engine publishes both through optional instrument callbacks.
- `Engine` already calls optional `on_block_boundary(snapshot)` before sample-offset events and processes `InstrumentEvent` at the correct split point through `on_event(name, payload)`. LOOM can therefore schedule bounded surface voices and strums without changing event ordering or blocking the audio callback.
- Waveguide state will use a fixed circular history sized for MIDI 24 at the active sample rate. Every vector chunk is at most the smallest feedback delay M, so all delay taps read prior chunk history; this preserves the per-sample recurrence exactly and avoids unbounded arrays.
- Note-on voices own seeded excitation generators. The instrument owns only bounded surface-event voices, the one-way 12-string sympathetic bank, modal body filters, and shared reverb. Sympathetic output is never routed back to the main strings.
- The issue/RAG specify an optional string-crossing event, but not its payload. TRIO-011 will define and test `pluck`/`bow` as `(pitch, velocity[, string_index])`, `mute` as `(string_index)` and `strum` as `(direction, rows_per_second, held_pitch...)`; direction +1 means low-to-high, -1 means high-to-low. The format will be recorded in RAG for TRIO-012.
- Body resonances are artistic modal approximations, not physical instrument measurements; type tables and scaling will say so explicitly.
- A literal random one-loop pluck realization can suppress its fundamental and fail the issue's required raw FFT pitch estimate. The implementation retains seeded white noise and the specified LP/comb path, with a unit-amplitude seeded-phase fundamental floor before that path; the matching LOOM RAG contract is updated in this PR.
- The waveguide accepts MIDI 24-100 while held strum pitches can span MIDI 0-127. Chord-follow sympathetic pitches are folded by octaves into the playable range, and the pitch test now checks every semitone from 24 through 100.
- Surface-event voices need the same seed and active polyphony budget as keyboard voices. Instrument string-activity telemetry is pruned against the weak live-voice registry so short-faded or discarded voices cannot leave stale pitch entries.

## Acceptance plan

- Compare chunked waveguide samples against a test-only scalar recurrence; measure pitch and T60 over the specified notes; exercise retarget and long-decay stability.
- Test deterministic pluck/bow excitation, sympathetic tuning/no-return/quiet retuning, modal body scaling, strum ordering and velocity, event voice bounds, dynamic voice-limit transitions and all eight factory presets.
- Run the complete device-free all-package checks and clean-wheel packaging checks, then the exact-head GitHub matrix.
- No physical audio/MIDI hardware is needed for software acceptance and no physical acceptance will be claimed.

## Qualification results

- `tools/check.py --package all --packaging` passed all 398 device-free tests (kit 338, AURORA 38, LOOM 21, DRIFT 1), built all four wheels, installed them into an isolated environment, and passed metadata/import/resource/CLI smoke checks.
- The LOOM tuning regression iterates every semitone from MIDI 24 through 100 and remains within the specified ±5 cents. The 20-second maximum-decay/brightness/coupling performance gate passed.
- No physical audio or MIDI hardware was exercised.

## Provenance

Codex desktop (GPT-6, configuration unknown), PowerShell/Git/GitHub CLI, repository Python/NumPy/SciPy toolchain. Fresh highest-effort self-review will be used if another review tier is unavailable.
