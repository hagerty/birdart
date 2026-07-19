from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from birdweather_history import history_is_complete


class CompletenessTests(unittest.TestCase):
    def test_exhausted_pagination_is_complete(self) -> None:
        metadata = {
            "api_total_count": 10,
            "api_species_count": 3,
            "pagination_complete": True,
        }
        self.assertTrue(history_is_complete(metadata))

    def test_api_totals_do_not_override_pagination_state(self) -> None:
        # BirdWeather totals can include detections below confidenceGte, so they
        # are informational and must not be compared with filtered nodes.
        complete = {"api_total_count": 100, "pagination_complete": True}
        incomplete = {"api_total_count": 1, "pagination_complete": False}
        self.assertTrue(history_is_complete(complete))
        self.assertFalse(history_is_complete(incomplete))


if __name__ == "__main__":
    unittest.main()
