"""Compare current factory render WAVs with the frozen TRIO-016 baseline fixture."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs" / "programme" / "fixtures" / "TRIO-016-factory-render-baseline.json"
for package in ("kit", "aurora", "loom", "drift"):
    sys.path.insert(0, str(ROOT / package / "src"))

from trio_aurora.cli import main as aurora_main
from trio_drift.cli import main as drift_main
from trio_loom.cli import main as loom_main


COMMANDS: dict[str, Callable[[Sequence[str]], int]] = {
    "aurora": aurora_main,
    "loom": loom_main,
    "drift": drift_main,
}


def main() -> int:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    render = fixture["render"]
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="trio-factory-baseline-") as temporary:
        workspace = Path(temporary)
        data_dir = workspace / "empty-user-data"
        data_dir.mkdir()
        for instrument, presets in fixture["presets"].items():
            command = COMMANDS[instrument]
            for preset_id, expected in presets.items():
                output = workspace / instrument / f"{preset_id}.wav"
                output.parent.mkdir(parents=True, exist_ok=True)
                result = command([
                    "--render", str(output),
                    "--preset", preset_id,
                    "--notes", ",".join(render["notes"]),
                    "--seconds", str(render["seconds"]),
                    "--sample-rate", str(render["sample_rate"]),
                    "--seed", str(render["seed"]),
                    "--data-dir", str(data_dir),
                ])
                if result != 0 or not output.is_file():
                    failures.append(f"{instrument}/{preset_id}: CLI render failed")
                    continue
                actual = hashlib.sha256(output.read_bytes()).hexdigest()
                if actual != expected:
                    failures.append(f"{instrument}/{preset_id}: expected {expected}, got {actual}")
                    print(f"FAIL {instrument}/{preset_id}")
                else:
                    print(f"PASS {instrument}/{preset_id}")
    if failures:
        print("\nFactory render baseline mismatches:")
        print("\n".join(failures))
        return 1
    count = sum(len(presets) for presets in fixture["presets"].values())
    print(f"All {count} factory WAV checksums match the TRIO-016 baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
