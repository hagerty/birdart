from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from build_artwork_prompt import choose_standout, parse_datetime


class StandoutTests(unittest.TestCase):
    def test_lowest_occurrence_tier_wins_before_rarity(self) -> None:
        birds = [
            {"common_name": "Rare", "detection_count": 1},
            {"common_name": "Common", "detection_count": 100},
        ]
        selected = choose_standout(birds, {"Rare": 1, "Common": 0})
        self.assertEqual(selected["common_name"], "Common")

    def test_rarity_breaks_tie_within_occurrence_tier(self) -> None:
        birds = [
            {"common_name": "Common", "detection_count": 100},
            {"common_name": "Rare", "detection_count": 1},
        ]
        selected = choose_standout(birds, {"Rare": 2, "Common": 2})
        self.assertEqual(selected["common_name"], "Rare")

    def test_timestamps_compare_by_instant_not_text(self) -> None:
        earlier = "2026-11-01T01:45:00-04:00"
        later = "2026-11-01T01:15:00-05:00"
        self.assertLess(parse_datetime(earlier), parse_datetime(later))


if __name__ == "__main__":
    unittest.main()
