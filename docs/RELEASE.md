# Build, verify and reproduce the 0.1.0 candidate

## Authority and source identity

This campaign is **Draft/HOLD**. The tooling and workflow build review artifacts; they have no publication or tagging step. The owner must explicitly approve any later merge/tag/release. Issue #17 remains open during this campaign.

Build from a clean Git checkout and choose the exact committed revision. Use a new empty output directory; the tool refuses to overwrite an existing nonempty one. In-checkout output must be Git-ignored (for example `dist/release`), or use an external directory. The release tool exports tracked files from that revision to fresh temporary directories rather than building from whatever happens to be in the working tree. This excludes uncommitted source, local environments, caches and generated output. Its `SOURCE.json` records the commit, tree, per-source SHA-256, source epoch, Python/build-tool versions and dependency-wheel hashes. The commit in that record must match the candidate handoff being evaluated.

## Prepare dependencies, then qualify offline

Use a supported Python and a writable checkout. The tool has a separate acquisition operation so builds/tests do not silently fetch packages:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pip install --no-deps --no-build-isolation --editable kit --editable aurora --editable loom --editable drift
.\.venv\Scripts\python tools/release.py --prepare-wheelhouse .trio-ci/wheelhouse
.\.venv\Scripts\python tools/release.py --revision HEAD --wheelhouse .trio-ci/wheelhouse --output dist/release
.\.venv\Scripts\python tools/release.py --verify dist/release
```

On POSIX use `.venv/bin/python`. The acquisition command accepts `--extras audio,midi` when a wheelhouse with the optional hardware backends is wanted. Use the same target Python executable for acquisition and qualification. On Python 3.14, MIDI acquisition builds a native wheel under the controlled procedure described below. The core release build/selftests remain device-free. Hosted launcher qualification additionally installs the explicit audio/MIDI extras to test their installation and reuse; it does not open physical devices or establish hardware acceptance. `requirements-release.txt` pins runtime and build dependencies; `requirements-dev.txt` adds the qualification test runner. A wheelhouse must match the target interpreter, OS and architecture. Acquisition is the only network phase; build/install qualification uses `--no-index`.

### Controlled native MIDI acquisition

`requirements-optional.txt` constrains the explicit audio/MIDI backends and their
extra dependencies during acquisition and launcher setup. These constraints do
not install optional packages in a core-only environment, and prevent a newer
wheel in a reused cache from changing the qualified native dependency version.

The [upstream python-rtmidi 1.5.8 wheel list](https://pypi.org/project/python-rtmidi/1.5.8/#files) ends at CPython 3.12. The helper's Python 3.13+ MIDI path verifies the pinned upstream source-distribution SHA-256, regenerates C++ from the unchanged Cython `.pyx` using the pinned Cython version, and compiles a wheel with pinned Meson/build dependencies. This is an acquisition-time dependency build; the subsequent release and launcher gates consume its completed wheel offline. It is not a claim that arbitrary plain-pip source installation on Python 3.14 works.

Ubuntu builders require `build-essential`, `pkg-config`, `libasound2-dev` and the selected interpreter's development headers. Windows builders require MSVC C++ tools plus a Windows SDK; Meson `--vsenv` selects the installed Visual Studio environment. See [the installation guide](INSTALL.md#python-314-midi-wheelhouse) and upstream's [native build requirements](https://spotlightkid.github.io/python-rtmidi/installation.html). Python 3.11 owner evaluation can use the upstream prebuilt MIDI wheel without installing those compilers.

Keep `RTMIDI-PROVENANCE.json` and any `RTMIDI-BUILD.log` with the wheelhouse; `SOURCE.json` embeds the acquisition provenance. The source build pins Cython 3.3.1, meson-python 0.22.1, Meson 1.12.1, Ninja 1.13.2 and pyproject-metadata 0.12.1 in `requirements-midi-build.txt`. Its metadata identifies the upstream source SHA-256, generated C++ hashes, builder versions/settings, wheel hash and device-free API proof. Linux source wheels enable ALSA and disable JACK; Windows source wheels enable WinMM. The controlled regeneration preserves the upstream `.pyx` source and records the source/toolchain transformation. The release's reproducibility claim covers the four TRIO wheels and source/candidate archives; it does not claim bit-identical compiler output for third-party native wheels across machines or platforms.

The release command builds the four packages twice from separate clean source exports under a frozen source epoch and compares the resulting artifact bytes. It verifies wheel metadata and expected code/assets, creates a fresh venv, installs all four wheels together, runs dependency checks and installed commands outside the checkout, then emits its evidence. The root `tools/check.py --package all --packaging` entry point integrates package qualification with the existing test suites. Consult `--help` for the exact accepted options.

## Artifact inventory

| Artifact | Contents and use |
|---|---|
| Four `trio_*.whl` files | Co-installable 0.1.0 distributions: shared kit, AURORA, LOOM and DRIFT; Python code, skins, presets and typing markers. |
| Source ZIP with revision prefix | Deterministic export of tracked source for the chosen Git revision. |
| Candidate ZIP with revision prefix | Source, documentation, POSIX/Windows launchers and four TRIO wheels under `wheels/`; extract to evaluate. |
| `SHA256SUMS` | SHA-256 values for the produced artifacts and evidence files. |
| `SOURCE.json` | Exact source and toolchain/dependency provenance; use this to identify what was built. |
| `QUALIFICATION.json` | Installed-command results and software qualification evidence for that build. |
| `REPRODUCIBILITY.json` | Matching hashes from the independent wheel/source/candidate builds and the explicitly recorded reproducibility scope. |
| Separate `trio-wheelhouse-<OS>-py3.14-<SHA>` CI artifact | Complete matching dependency wheels, `WHEELHOUSE.json`, native MIDI provenance and compiler log; enables offline Python 3.14 setup without a local compiler. |

No third-party native dependency set, interpreter, credentials, user data or real audio recording is implicitly bundled. Offline setup of a candidate still needs a matching complete wheelhouse. The ordinary launcher can acquire core/audio dependencies online, and MIDI dependencies on the prebuilt-wheel Python 3.11 evaluation path. Python 3.13+ first-run MIDI setup requires the prepared matching wheelhouse.

## Verify the candidate before evaluating

`python tools/release.py --verify PATH` checks manifest completeness and the listed file digests. A manual PowerShell hash check is also possible in the release-output directory:

```powershell
$ErrorActionPreference = 'Stop'
Get-Content .\SHA256SUMS | ForEach-Object {
    if ($_ -notmatch '^([a-f0-9]{64})  (.+)$') { throw "Invalid manifest line: $_" }
    $expected = $Matches[1]; $file = $Matches[2]
    if ($file -match '(^[\\/]|(^|[\\/])\.\.([\\/]|$)|:)') { throw "Unsafe manifest path: $file" }
    $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw "SHA-256 mismatch: $file" }
}
'All listed SHA-256 values match.'
```

Checksums detect changed bytes, not author identity. Obtain the candidate and its manifest from the exact CI run linked in the PR handoff and compare `SOURCE.json` to that reviewed commit. Do not combine artifacts or evidence from different revisions into one claim of qualification.

## Reproducibility boundary

Use the same source revision, pinned build tools and source epoch to reproduce the TRIO wheels and archives. Repeat-build equality is checked within the release operation, not assumed from a deterministic filename. Dependency provenance records downloaded wheel hashes because upstream native wheels vary by platform and Python version. Environment-specific installed-command evidence may differ across lanes; the tool does not claim identical Windows/Linux third-party binaries or identical qualification timestamps.

The CI matrix retains all four lanes: Ubuntu/Python 3.11 and 3.14, Windows/Python 3.11 and 3.14. It exercises the established suites, clean-installed selftests, genuine launcher setup/reuse, manifest verification and reproducible release construction. The final handoff links exact-source CI outcomes; read that evidence before calling a candidate software-qualified. Manual [acceptance](ACCEPTANCE.md) remains separate.

## Rollback

Quit all running instruments and retain per-instrument user data. Reopen an earlier known artifact or source revision using a separate fresh `TRIO_VENV` rather than mixing versions in a reused environment. The candidate has no migration step that requires altering an older checkout. Keep saved presets/maps backed up before experimenting with custom asset edits. No tag deletion, release deletion or PR merge is needed to discard an unpublished candidate.
