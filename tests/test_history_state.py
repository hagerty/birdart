from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HistoryStateTests(unittest.TestCase):
    def test_recording_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selection = root / "selection.json"
            history = root / "history.json"
            selection.write_text(
                json.dumps(
                    {
                        "selection_id": "station:unique",
                        "standout": "Robin",
                        "featured_species": ["Robin", "Robin", "Jay"],
                    }
                ),
                encoding="utf-8",
            )
            command = [
                sys.executable,
                str(ROOT / "src" / "record_featured_history.py"),
                "--selection",
                str(selection),
                "--history",
                str(history),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            subprocess.run(command, check=True, capture_output=True, text=True)
            payload = json.loads(history.read_text(encoding="utf-8"))
            self.assertEqual(payload["occurrence_counts"], {"Jay": 1, "Robin": 1})
            self.assertEqual(len(payload["events"]), 1)


if __name__ == "__main__":
    unittest.main()
