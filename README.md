# TRIO terminal synthesizers

TRIO is a set of three co-installable terminal synthesizers with distinct sound and interaction designs:

- **AURORA** makes evolving spectral pads and choirs.
- **LOOM** makes plucked and strummed strings.
- **DRIFT** makes breath, wind, and vowel clouds.

Shared audio and terminal infrastructure lives in `trio-kit`. The product and engineering contracts are indexed in [`docs/rag/INDEX.md`](docs/rag/INDEX.md); the phased implementation plan is in [`docs/programme/IMPLEMENTATION-PROGRAMME.md`](docs/programme/IMPLEMENTATION-PROGRAMME.md).

## Development setup

Use Python 3.11 or newer. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps --editable kit --editable aurora --editable loom --editable drift
python tools/check.py --package all
```

On POSIX shells, activate with `source .venv/bin/activate`. The optional `audio` and `midi` extras install device backends; the synth packages themselves import and install without audio or MIDI hardware.

The shared check entry point accepts `--package kit|aurora|loom|drift|all`, `--packaging` for clean wheel installation and CLI smoke checks, and `--update-snapshots` for snapshot-producing tests.

Each instrument currently provides a versioned CLI foundation (`aurora --version`, `loom --version`, `drift --version`).
