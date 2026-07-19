#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from birdart_io import atomic_write_json, exclusive_lock


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record birds shown in one successfully published artwork."
    )
    parser.add_argument(
        "--selection",
        type=Path,
        default=Path("data_output/prompt_selection.json"),
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=Path("data_output/featured_history.json"),
    )
    parser.add_argument("--content-id", help="Samsung content ID, when known")
    return parser.parse_args()


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def main() -> int:
    args = parse_args()
    selection = read_json(args.selection)
    lock_path = args.history.with_suffix(args.history.suffix + ".lock")
    with exclusive_lock(lock_path):
        history = read_json(args.history) if args.history.is_file() else {}
        processed = set(history.get("processed_selection_ids") or [])
        selection_id = selection["selection_id"]
        if selection_id in processed:
            print(f"Selection already recorded: {selection_id}")
            return 0

        counts = history.get("occurrence_counts") or {}
        species = list(dict.fromkeys(selection["featured_species"]))
        for name in species:
            counts[name] = int(counts.get(name, 0)) + 1

        events = history.get("events") or []
        events.append(
            {
                "selection_id": selection_id,
                "published_at": datetime.now().astimezone().isoformat(),
                "content_id": args.content_id,
                "standout": selection["standout"],
                "featured_species": species,
            }
        )
        events = events[-100:]
        retained_ids = {event["selection_id"] for event in events}
        payload = {
            "occurrence_counts": dict(sorted(counts.items())),
            "processed_selection_ids": sorted(retained_ids),
            "events": events,
        }
        atomic_write_json(args.history, payload)
    print(f"Recorded {len(species)} featured species for {selection_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
