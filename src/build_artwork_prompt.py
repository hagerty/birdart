#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from birdart_io import atomic_write_json, atomic_write_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve the reusable artwork prompt from current query JSON."
    )
    parser.add_argument(
        "--station-file",
        type=Path,
        default=Path("data_input/station.json"),
        help="Station configuration JSON. Default: data_input/station.json",
    )
    parser.add_argument("--timezone", default="America/New_York")
    parser.add_argument("--data-dir", type=Path, default=Path("data_output"))
    parser.add_argument(
        "--template",
        type=Path,
        default=Path("data_input/prompt_image_generation.txt"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data_output/prompt_image_generation_resolved.txt"),
    )
    parser.add_argument(
        "--history-days",
        type=int,
        default=90,
        help="Available-history query used for station-local rarity. Default: 90",
    )
    parser.add_argument(
        "--feature-history",
        type=Path,
        default=Path("data_output/featured_history.json"),
        help="Successful artwork occurrence ledger.",
    )
    parser.add_argument(
        "--selection-output",
        type=Path,
        default=Path("data_output/prompt_selection.json"),
        help="Selection manifest to record after a successful upload.",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def read_json_if_present(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return read_json(path)


def local_time(timestamp: str, timezone: ZoneInfo) -> str:
    parsed = parse_datetime(timestamp)
    return parsed.astimezone(timezone).strftime("%-I:%M %p")


def parse_datetime(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def choose_standout(
    eligible: list[dict[str, Any]], occurrence_counts: dict[str, Any]
) -> dict[str, Any]:
    return min(
        eligible,
        key=lambda item: (
            int(occurrence_counts.get(item["common_name"], 0)),
            item["detection_count"],
            item["common_name"],
        ),
    )


def species_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["common_name"]: item for item in payload["species"]}


def main() -> int:
    args = parse_args()
    timezone = ZoneInfo(args.timezone)
    station_config = read_json(args.station_file)
    try:
        station_id = str(station_config["station"]["id"])
    except (KeyError, TypeError) as exc:
        raise RuntimeError(
            f"Could not read station.id from {args.station_file}"
        ) from exc
    one_day_raw = read_json(
        args.data_dir / f"station_{station_id}_1d_detections.json"
    )
    one_day_summary = read_json(
        args.data_dir / f"station_{station_id}_1d_species_summary.json"
    )
    history_summary = read_json(
        args.data_dir
        / f"station_{station_id}_{args.history_days}d_species_summary.json"
    )

    detections = one_day_raw["detections"]
    today = datetime.now(timezone).date()
    detections_today = [
        item
        for item in detections
        if datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
        .astimezone(timezone)
        .date()
        == today
    ]
    if not detections_today:
        raise RuntimeError("The one-day query contains no detections.")
    latest_detection = max(
        detections_today,
        key=lambda item: parse_datetime(item["timestamp"]),
    )
    latest_name = latest_detection["species"]["commonName"]
    daily_by_name = species_map(one_day_summary)
    latest = daily_by_name[latest_name]

    history_metadata = history_summary.get("metadata") or {}
    if history_metadata.get("history_complete") is not True:
        raise RuntimeError(
            "The history query is incomplete; refusing to calculate rarity. "
            "Re-run birdweather_history.py and inspect its API totals."
        )

    # Rarity is station-local. A confidence floor is used only for selecting a
    # standout; confidence itself is deliberately omitted from the artwork.
    detected_today = {
        item["species"]["commonName"] for item in detections_today
    }
    unusual = [
        item
        for item in history_summary["species"]
        if item["common_name"] in detected_today
        and item["detection_count"] <= 5
        and float(item.get("best_confidence") or 0) >= 0.85
    ]
    eligible = [
        item
        for item in history_summary["species"]
        if item["common_name"] in detected_today
        and float(item.get("best_confidence") or 0) >= 0.85
    ]
    if not eligible:
        raise RuntimeError("No today species passed the standout confidence floor.")
    feature_history = read_json_if_present(args.feature_history)
    occurrence_counts = feature_history.get("occurrence_counts") or {}
    standout = choose_standout(eligible, occurrence_counts)

    recent_by_species: list[dict[str, Any]] = []
    seen = {latest_name, standout["common_name"]}
    for detection in sorted(
        detections_today,
        key=lambda item: parse_datetime(item["timestamp"]),
        reverse=True,
    ):
        name = detection["species"]["commonName"]
        if name in seen:
            continue
        seen.add(name)
        recent_by_species.append(detection)
        if len(recent_by_species) == 5:
            break
    visitor_lines = "\n".join(
        "    * " + item["species"]["commonName"]
        for item in recent_by_species
    )
    hawks = [
        item
        for item in history_summary["species"]
        if "hawk" in item["common_name"].casefold()
    ]
    if hawks:
        overhead_hawk = max(
            hawks,
            key=lambda item: parse_datetime(item["latest_detection"]),
        )
        same_as_latest = overhead_hawk["common_name"] == latest_name
        overhead_direction = (
            f"* Overhead hawk: Paint one {overhead_hawk['common_name']} gliding "
            "naturally through the open sky above the fountain, wings fully "
            "extended and smaller in scale than the featured birds. Add a subtle "
            f"handwritten label “{overhead_hawk['common_name']}” near its flight path. "
            + (
                "This is also the Latest Visitor: use the same flying hawk as its "
                "secondary illustration and do not depict a second individual."
                if same_as_latest
                else "Do not duplicate this hawk elsewhere in the composition."
            )
        )
    else:
        overhead_direction = (
            "* Overhead hawk: None appears in the available station history; "
            "do not invent or depict a hawk."
        )
    replacements = {
        "{{TODAY_DATE}}": datetime.now(timezone).strftime("%B %-d, %Y"),
        "{{TIMEZONE}}": args.timezone,
        "{{SPECIES_COUNT}}": str(len(detected_today)),
        "{{UNUSUAL_COUNT}}": str(len(unusual)),
        "{{LATEST_SPECIES}}": latest_name,
        "{{LATEST_TIME}}": local_time(latest["latest_detection"], timezone),
        "{{STANDOUT_SPECIES}}": standout["common_name"],
        "{{STANDOUT_HISTORY}}": (
            f"Only {standout['detection_count']} "
            + ("detection" if standout["detection_count"] == 1 else "detections")
            + " in available station history"
        ),
        "{{STANDOUT_TIME}}": local_time(standout["latest_detection"], timezone),
        "{{RECENT_VISITORS}}": visitor_lines,
        "{{OVERHEAD_HAWK_DIRECTION}}": overhead_direction,
    }

    prompt = args.template.read_text(encoding="utf-8")
    for placeholder, value in replacements.items():
        prompt = prompt.replace(placeholder, value)
    unresolved = [token for token in replacements if token in prompt]
    if unresolved or "{{" in prompt:
        raise RuntimeError("Unresolved prompt placeholders remain.")

    atomic_write_text(args.output, prompt)
    featured_species = [standout["common_name"], latest_name]
    featured_species.extend(
        item["species"]["commonName"] for item in recent_by_species
    )
    if hawks:
        featured_species.append(overhead_hawk["common_name"])
    selection = {
        "selection_id": f"{station_id}:{uuid.uuid4()}",
        "station_id": station_id,
        "created_at": datetime.now(timezone).isoformat(),
        "standout": standout["common_name"],
        "standout_occurrence_before": int(
            occurrence_counts.get(standout["common_name"], 0)
        ),
        "latest_visitor": latest_name,
        "recent_visitors": [
            item["species"]["commonName"] for item in recent_by_species
        ],
        "overhead_hawk": overhead_hawk["common_name"] if hawks else None,
        "featured_species": list(dict.fromkeys(featured_species)),
    }
    atomic_write_json(args.selection_output, selection)
    print(args.output.resolve())
    print(args.selection_output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
