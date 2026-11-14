# TRIO-017 v0.1.0 release-candidate qualification

This is the engineering handoff for the unpublished v0.1.0 candidate. The PR stays
**Draft/HOLD** and issue [#17](https://github.com/techrote/tuisynth-codex/issues/17)
stays open. Merge, tagging and public publication require explicit owner approval.
Physical acceptance is solely recorded in [ACCEPTANCE.md](ACCEPTANCE.md).

## Follow-up independent review correction

The 14 November independent review of commit `40584a81a42b86ea4cfd87e2277b16036c373bcb`
identified one P3 shared-Button capture defect: synthetic in-bounds mouse-up
could activate a button while a modal or screen transition cancelled its
gesture. The follow-up audit identified the same release-without-press risk
in shared ListBox, used by AURORA's library screen. The widget cancellation
hook now distinguishes deliberate cancellation from a normal click: Buttons
and ListBoxes disarm without activation, while sustained gesture widgets retain
their release. Real SGR regressions cover visible, hidden and replaced
capture owners, late physical mouse-up, and subsequent valid clicks. The exact corrected commit/CI is recorded in PR #35.
This change does not claim any additional hardware acceptance.

## Exact source and evidence

The final PR handoff names the reviewed full commit SHA and links its four CI jobs.
Each CI artifact name carries that same SHA. `SOURCE.json` records the full commit,
tree, source file hashes and modes, pinned build requirements and downloaded
dependency-wheel hashes. `QUALIFICATION.json` records installed-command results;
`REPRODUCIBILITY.json` records the two-build comparison. A separate launcher report
records its source identity, copied inputs, exact candidate ZIP, installed package
versions, repeat-launch evidence and source/wheel results.

Compare those identities before evaluating a candidate. A green result from a
previous source revision does not qualify a later commit. Checksums establish
byte integrity, not publisher identity. The source of trust is the reviewed PR
and its linked GitHub Actions run.

Starting source was main `357215781ba0b82694e62dd4d7ba1c3697ac3159`, with all four
lanes green in [run 39115306829](https://github.com/techrote/tuisynth-codex/actions/runs/39115306829).
The fresh local baseline passed 551 established tests: kit 407, AURORA 41, LOOM 48,
DRIFT 55. No accepted tests were removed, skipped or weakened to admit the candidate.

## Complete change inventory

| Area | Files | Result |
|---|---|---|
| Platform/dependency qualification | `.github/workflows/ci.yml`, `.gitattributes`, `.gitignore`, `requirements-dev.txt`, `requirements-release.txt`, `requirements-midi-build.txt`, `requirements-optional.txt` | Exact PR-head checkout; all four original OS/Python lanes retained and expanded; pinned build/runtime/transitive/native-build requirements and optional constraints; explicit dependency acquisition followed by offline qualification; candidate/evidence uploads with read-only repository permissions. |
| Packaging/release | `tools/release.py`, `tools/check.py` | Clean exact-Git source exports, independent wheel builds, source/data/metadata/entry-point/RECORD verification, isolated installation, all four selftests, snapshots/renders, deterministic source/candidate ZIPs, SHA-256 and source/qualification/reproducibility records. |
| Launch/install | `launch.sh`, `launch.cmd`, `tools/launch.py`, `tools/check_launchers.py` | Supported Python selection, owned local venv setup/reuse/repair, explicit optional audio/MIDI packages, source or wheel installation, safe failed setup/retry, argument/exit-code forwarding and actual extracted-candidate checks. |
| Shared UI/input | `kit/src/trio_kit/shell.py`, `kit/src/trio_kit/tui/app.py`, `kit/src/trio_kit/tui/widgets.py`, `loom/src/trio_loom/ui.py`, `drift/src/trio_drift/ui.py` | Correct cancelled CC learn, selected-control identity, clickable/scrolled shared lists, modal focus, panic availability and release of captured gestures before modal/screen transitions. No synthesis algorithm or factory sound changes. |
| Persistence repair | `kit/src/trio_kit/preset.py`, `kit/src/trio_kit/input/cc_learn.py` | MIDI maps no longer break preset discovery; reserved-path protection prevents map deletion or overwrite, while valid historical colliding presets remain recoverable through rename. |
| New regressions/reference generation | `kit/tests/test_release.py`, `kit/tests/test_launchers.py`, `kit/tests/test_documentation.py`, `kit/tests/test_release_ui.py`, `kit/tests/test_release_presets.py`, `kit/tests/test_tui_app.py`, `tools/documentation.py` | Real installer/wrapper commands and terminal key/SGR events; tamper, drift, error/recovery, selection and persistence regressions; generated documentation checks. |
| User/release guides | `README.md`, `aurora/README.md`, `loom/README.md`, `drift/README.md`, `CHANGELOG.md`, `docs/INSTALL.md`, `docs/CONTROLS.md`, `docs/CLI.md`, `docs/RELEASE.md`, `docs/RELEASE-NOTES-0.1.0.md`, `docs/ACCEPTANCE.md`, this document | Verified controls/assets/configuration, frozen existing layouts, 17-issue release history, practical installation/evaluation/rollback, with physical checks explicitly unperformed. |
| Engineering/provenance | `docs/PROVENANCE.md`, `docs/programme/IMPLEMENTATION-PROGRAMME.md`, `docs/programme/prepasses/TRIO-017.md`, `docs/rag/02-AUDIO-ENGINE-CONTRACT.md`, `docs/rag/04-TUI-UX-CONTRACT.md`, `docs/rag/10-TESTING-CI-RELEASE.md` | Reconciled prior completion, current campaign authority, release contracts, discovered defect repairs and primary/assisting/review contributions. |

All four distribution names, imports, version 0.1.0, runtime dependency ranges and
package-data declarations were already correct. The new verifier checks them
against actual built wheels rather than changing metadata without a defect.

## Software gates and reproduction

Every Ubuntu/Windows × Python 3.11/3.14 lane performs these gates:

1. Install pinned development dependencies and the four editable packages.
2. Acquire the matching runtime/build and optional backend wheels explicitly.
   When the pinned RtMidi release has no compatible upstream wheel, verify its
   published source hash and regenerate its generated C++ with pinned Cython,
   then build a wheel with pinned Meson tooling and the host compiler. Preserve
   the authored upstream sources and record the compiler log, source hashes,
   changed generated file, resulting wheel and device-free API probe.
3. Run all established and new package regressions, including generated references.
4. Export the exact committed source twice and build all four wheels in fresh
   pinned environments. Compare bytes and verify complete package contents.
5. Install wheels together in a new environment outside the checkout, verify
   isolated imports/resources and dependencies, run `trio-demo`, `aurora`, `loom`
   and `drift` selftests, inspect their factory assets/snapshots and write non-silent
   stereo WAVs without devices.
6. Exercise genuine source and exact extracted-candidate launchers: first setup,
   all four installed selftests, reuse, argument forwarding, optional backend
   installation and subsequent reuse. The candidate ZIP's actual wrapper bytes are
   exercised, including Windows line-ending handling. Load the optional modules
   and verify the compiled MIDI host API without opening streams or ports.
   Linux CI supplies a private PulseAudio host with a null sink for PortAudio
   initialization; this is a virtual software dependency check, not an audio
   output or listening result.
7. Verify final SHA-256 manifests and upload review artifacts/evidence.
   Python 3.14 additionally uploads its complete matching dependency wheelhouse
   so owner installation can use the qualified native MIDI wheel without a
   local compiler.

The local developer entry point remains:

```text
python tools/check.py --package all
python tools/release.py --prepare-wheelhouse .trio-ci/wheelhouse --extras audio,midi
python tools/check.py --package all --packaging --wheelhouse .trio-ci/wheelhouse
python tools/release.py --revision HEAD --wheelhouse .trio-ci/wheelhouse --output dist/release
python tools/check_launchers.py --wheelhouse .trio-ci/wheelhouse --wheels dist/release --extras audio,midi --report .trio-ci/launcher-qualification.json
python tools/release.py --verify dist/release
```

Use a clean committed checkout and an unused empty output directory. Package
qualification runs offline after acquisition. Source selection and output guards
prevent a mutable checkout or stale build directory being represented as a
qualified committed release. See [RELEASE.md](RELEASE.md) for artifact details.

Reproducibility is checked for two independent exports/builds under the same
OS, interpreter, pinned toolchain and source timestamp. The candidate archive
comparison reuses the same qualification record, whose platform-specific content
is evidence rather than a portable binary. No claim is made that native third-party
wheels or all evidence bytes are identical across platforms/interpreter versions.

## Independent audit and repaired defects

Provider-native packaging, launcher and documentation agents assisted the primary
GPT-6 Pro engagement. A separately configured provider-native reviewer audited
the assembled changes. Roles and configuration visibility are recorded in
[PROVENANCE.md](PROVENANCE.md); no sibling attempt was queried or inspected.

The audit repaired concrete reproduced defects before handoff:

- Escape/overlay replacement/shutdown left a MIDI learn target armed.
- Shared modal lists ignored mouse selections, long keyboard selections could
  disappear below the viewport, and Tab could reach hidden controls.
- A held pointer capture could keep retargeting a piano or changing a weather
  field after a modal or screen transition; dropping capture alone lost releases.
- Composite DRIFT/LOOM controls could teach a CC to the first registry parameter
  instead of the parameter the player selected.
- Saving a controller map made preset discovery parse it as a sound preset;
  colliding preset names could overwrite or delete controller data.
- Inherited pip requirement/constraint options contaminated otherwise isolated
  package qualification.
- The default Python selector needed actual execution coverage, beyond explicit
  `TRIO_PYTHON` tests; fallback aliases also exposed a venv interpreter-path defect.
- Draft documentation misstated DRIFT user-save behavior, some context-dependent
  shortcuts, the actual user preset directory and checksum verification scope.
- Initial CI exposed the absence of Python 3.14 binaries for the published
  python-rtmidi release. Controlled acquisition now regenerates its obsolete
  generated C++ and builds a real ALSA/WinMM backend; first-run instructions and
  safe launcher failures require a matching prepared wheelhouse for that path.
- An oversized corruption-test parameter was also used as its pytest node ID,
  exceeding Windows' environment-variable limit before the test ran. Short
  explicit IDs preserve the entire 65,537-byte test payload and all assertions.
- Optional constraints prevent a stale wheelhouse's newer backend from replacing
  the exact version whose native provenance was recorded. Base installations
  still omit every optional backend.

Focused reproducers precede or accompany these repairs. The final handoff names
the exact reviewed source and final full CI results; preliminary mutable-worktree
experiments are not used as final qualification evidence.

## Owner evaluation and rollback

The candidate is software, not a bundled Python runtime. Install a supported
64-bit Python, obtain the exact reviewed candidate, verify its SHA-256, extract
it and use the single-paste Windows procedure in [ACCEPTANCE.md](ACCEPTANCE.md).
It opens the instruments sequentially, creates isolated owner data and provides
device-free selftests/renders before practical audio/MIDI/interaction checks.

The remaining physical checks are real output/listening, USB MIDI, actual Windows
Terminal gestures and ten continuous minutes of stability/CPU observation per
instrument. Core fallback and fake-device tests do not satisfy those checks.
Python 3.11 supports straightforward online MIDI setup with the published backend
wheel. Python 3.13+ MIDI setup uses a matching prepared wheelhouse; the qualified
Python 3.14 CI artifacts include one for each operating system. Building that
wheelhouse locally needs the documented native prerequisites. Native dependency
compiler output is recorded and hashed, not claimed reproducible across hosts.
The normal timed computer-keyboard gate, explicit preset saving, advanced settings
stored in preset data and lack of standalone/PyPI distribution remain documented
v0.1 scope, not unreported defects. No licence is added without owner choice.

To roll back, quit all instruments, preserve the evaluation/user-data directory,
and reopen the prior artifact/revision with a separate fresh environment. The
candidate directory and its owned `.trio-venv` are disposable; existing user data
is not. No public release, tag or merge needs undoing in this campaign.
