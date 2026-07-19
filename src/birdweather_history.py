#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from birdart_io import atomic_write_json

GRAPHQL_URL = "https://app.birdweather.com/graphql"


def history_is_complete(
    api_metadata: dict[str, Any],
) -> bool:
    return api_metadata.get("pagination_complete") is True

QUERY = """
query RecentDetections(
  $stationIds: [ID!],
  $first: Int!,
  $after: String,
  $confidenceGte: Float,
  $period: InputDuration
) {
  detections(
    stationIds: $stationIds,
    first: $first,
    after: $after,
    confidenceGte: $confidenceGte,
    period: $period
  ) {
    totalCount
    speciesCount
    nodes {
      id
      timestamp
      confidence
      certainty
      score
      species {
        id
        commonName
        scientificName
        imageUrl
        thumbnailUrl
      }
      soundscape {
        url
      }
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch BirdWeather detections over a selected time range, "
            "summarize species counts, and save JSON output."
        )
    )

    parser.add_argument(
        "--station",
        help="Override the station ID from --station-file.",
    )

    parser.add_argument(
        "--station-file",
        type=Path,
        default=Path("data_input/station.json"),
        help="Station configuration JSON. Default: data_input/station.json",
    )

    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days of history to query. Default: 7",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=20000,
        help="Maximum number of detections to retrieve. Default: 20000",
    )

    parser.add_argument(
        "--page-size",
        type=int,
        default=250,
        help="Number of detections per API request. Default: 250",
    )

    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.70,
        help="Minimum confidence from 0 to 1. Default: 0.70",
    )

    parser.add_argument(
        "--timezone",
        default="America/New_York",
        help="Timezone used by BirdWeather period queries.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("."),
        help="Directory for JSON output files. Default: current directory",
    )

    return parser.parse_args()


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_timestamp(value: str | None) -> str:
    if not value:
        return "unknown"

    return parse_timestamp(value).strftime(
        "%b %-d, %Y %-I:%M:%S %p"
    )


def format_confidence(value: Any) -> str:
    if value is None:
        return "n/a"

    number = float(value)

    if number <= 1:
        return f"{number:.0%}"

    return f"{number:.0f}%"


def fetch_page(
    station_id: str,
    first: int,
    after: str | None,
    min_confidence: float,
    days: int,
    timezone: str,
) -> dict[str, Any]:
    variables = {
        "stationIds": [station_id],
        "first": first,
        "after": after,
        "confidenceGte": min_confidence,
        "period": {
            "count": days,
            "unit": "day",
            "timezone": timezone,
        },
    }

    response = requests.post(
        GRAPHQL_URL,
        json={
            "query": QUERY,
            "variables": variables,
        },
        timeout=60,
    )

    response.raise_for_status()

    payload = response.json()

    if payload.get("errors"):
        raise RuntimeError(
            json.dumps(payload["errors"], indent=2)
        )

    data = payload.get("data") or {}
    detections = data.get("detections")

    if detections is None:
        raise RuntimeError(
            "BirdWeather response did not include detections."
        )

    return detections


def fetch_detections(
    station_id: str,
    limit: int,
    page_size: int,
    min_confidence: float,
    days: int,
    timezone: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    detections: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    cursor: str | None = None
    first_page_metadata: dict[str, Any] = {}
    pagination_complete = False

    while len(detections) < limit:
        requested_count = min(
            page_size,
            limit - len(detections),
        )

        page = fetch_page(
            station_id=station_id,
            first=requested_count,
            after=cursor,
            min_confidence=min_confidence,
            days=days,
            timezone=timezone,
        )

        if not first_page_metadata:
            first_page_metadata = {
                "api_total_count": page.get("totalCount"),
                "api_species_count": page.get("speciesCount"),
            }

        nodes = page.get("nodes") or []

        added_count = 0

        for node in nodes:
            detection_id = str(node.get("id") or "")

            if detection_id and detection_id in seen_ids:
                continue

            if detection_id:
                seen_ids.add(detection_id)

            detections.append(node)
            added_count += 1

            if len(detections) >= limit:
                break

        print(
            f"Fetched {len(nodes)} records; "
            f"added {added_count}; "
            f"{len(detections)} total",
            flush=True,
        )

        page_info = page.get("pageInfo") or {}
        has_next_page = bool(page_info.get("hasNextPage"))
        next_cursor = page_info.get("endCursor")

        if not nodes:
            pagination_complete = True
            break

        if not has_next_page:
            pagination_complete = True
            break

        if not next_cursor:
            print(
                "BirdWeather indicated another page but did not "
                "return an end cursor.",
                file=sys.stderr,
            )
            break

        if next_cursor == cursor:
            print(
                "Pagination cursor did not advance; stopping to "
                "avoid an infinite loop.",
                file=sys.stderr,
            )
            break

        cursor = next_cursor

    first_page_metadata["pagination_complete"] = pagination_complete
    first_page_metadata["retrieval_limit_reached"] = (
        len(detections) >= limit and not pagination_complete
    )
    detections.sort(
        key=lambda item: parse_timestamp(
            item["timestamp"]
        ),
        reverse=True,
    )

    return detections, first_page_metadata


def build_species_summary(
    detections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "common_name": None,
            "scientific_name": None,
            "species_id": None,
            "detection_count": 0,
            "latest_detection": None,
            "earliest_detection": None,
            "best_confidence": None,
            "average_confidence": None,
            "image_url": None,
            "thumbnail_url": None,
            "latest_audio_url": None,
            "_confidence_total": 0.0,
            "_confidence_count": 0,
        }
    )

    for detection in detections:
        species = detection.get("species") or {}
        common_name = (
            species.get("commonName")
            or "Unknown species"
        )

        item = summary[common_name]

        item["common_name"] = common_name
        item["scientific_name"] = species.get(
            "scientificName"
        )
        item["species_id"] = species.get("id")
        item["detection_count"] += 1

        timestamp_text = detection.get("timestamp")

        if timestamp_text:
            timestamp = parse_timestamp(timestamp_text)

            if (
                item["latest_detection"] is None
                or timestamp
                > parse_timestamp(
                    item["latest_detection"]
                )
            ):
                item["latest_detection"] = timestamp_text

                soundscape = (
                    detection.get("soundscape") or {}
                )

                item["latest_audio_url"] = (
                    soundscape.get("url")
                )

            if (
                item["earliest_detection"] is None
                or timestamp
                < parse_timestamp(
                    item["earliest_detection"]
                )
            ):
                item["earliest_detection"] = timestamp_text

        confidence = detection.get("confidence")

        if confidence is not None:
            confidence_number = float(confidence)

            item["_confidence_total"] += (
                confidence_number
            )
            item["_confidence_count"] += 1

            if (
                item["best_confidence"] is None
                or confidence_number
                > item["best_confidence"]
            ):
                item["best_confidence"] = (
                    confidence_number
                )

        if species.get("imageUrl"):
            item["image_url"] = species["imageUrl"]

        if species.get("thumbnailUrl"):
            item["thumbnail_url"] = (
                species["thumbnailUrl"]
            )

    results: list[dict[str, Any]] = []

    for item in summary.values():
        confidence_count = item.pop(
            "_confidence_count"
        )
        confidence_total = item.pop(
            "_confidence_total"
        )

        if confidence_count:
            item["average_confidence"] = (
                confidence_total / confidence_count
            )

        results.append(item)

    results.sort(
        key=lambda item: (
            -item["detection_count"],
            item["common_name"],
        )
    )

    return results


def print_summary(
    station_id: str,
    days: int,
    min_confidence: float,
    detections: list[dict[str, Any]],
    species_summary: list[dict[str, Any]],
    api_metadata: dict[str, Any],
) -> None:
    print()
    print(f"Station: {station_id}")
    print(f"Requested period: last {days} day(s)")
    print(
        "Minimum confidence: "
        f"{format_confidence(min_confidence)}"
    )
    print(
        f"Retrieved detections: {len(detections)}"
    )
    print(
        f"Unique species: {len(species_summary)}"
    )

    if api_metadata.get("api_total_count") is not None:
        print(
            "API total detections in range: "
            f"{api_metadata['api_total_count']}"
        )

    if api_metadata.get("api_species_count") is not None:
        print(
            "API species count in range: "
            f"{api_metadata['api_species_count']}"
        )

    if detections:
        newest = detections[0].get("timestamp")
        oldest = detections[-1].get("timestamp")

        print(f"Newest: {format_timestamp(newest)}")
        print(f"Oldest: {format_timestamp(oldest)}")

    print()
    print("SPECIES COUNTS")
    print("-" * 110)

    for item in species_summary:
        latest = format_timestamp(
            item["latest_detection"]
        )

        print(
            f"{item['common_name']:<30} "
            f"{item['detection_count']:>7} detections  "
            f"latest {latest:<27} "
            f"best "
            f"{format_confidence(item['best_confidence']):>5}  "
            f"avg "
            f"{format_confidence(item['average_confidence']):>5}"
        )


def save_json(
    output_dir: Path,
    station_id: str,
    days: int,
    timezone: str,
    min_confidence: float,
    detections: list[dict[str, Any]],
    species_summary: list[dict[str, Any]],
    api_metadata: dict[str, Any],
) -> bool:
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    raw_path = output_dir / (
        f"station_{station_id}_{days}d_detections.json"
    )

    summary_path = output_dir / (
        f"station_{station_id}_{days}d_species_summary.json"
    )

    newest = (
        detections[0].get("timestamp")
        if detections
        else None
    )

    oldest = (
        detections[-1].get("timestamp")
        if detections
        else None
    )

    history_complete = history_is_complete(api_metadata)
    metadata = {
        "station_id": station_id,
        "generated_at": (
            datetime.now()
            .astimezone()
            .isoformat()
        ),
        "requested_days": days,
        "timezone": timezone,
        "minimum_confidence": min_confidence,
        "retrieved_detection_count": len(detections),
        "unique_species_count": len(species_summary),
        "newest_detection": newest,
        "oldest_detection": oldest,
        "history_complete": history_complete,
        **api_metadata,
    }

    raw_payload = {
        "metadata": metadata,
        "detections": detections,
    }

    summary_payload = {
        "metadata": metadata,
        "species": species_summary,
    }

    atomic_write_json(raw_path, raw_payload)
    atomic_write_json(summary_path, summary_payload)

    if not history_complete:
        print(
            "WARNING: BirdWeather pagination did not complete; this file "
            "must not be used for rarity calculations. Increase --limit or "
            "inspect the pagination warning above.",
            file=sys.stderr,
        )

    print()
    print(
        f"Saved raw detections: "
        f"{raw_path.resolve()}"
    )
    print(
        f"Saved species summary: "
        f"{summary_path.resolve()}"
    )
    return history_complete


def validate_args(
    args: argparse.Namespace,
) -> None:
    if args.days < 1:
        raise ValueError(
            "--days must be at least 1"
        )

    if args.limit < 1:
        raise ValueError(
            "--limit must be at least 1"
        )

    if args.page_size < 1:
        raise ValueError(
            "--page-size must be at least 1"
        )

    if args.page_size > 1000:
        raise ValueError(
            "--page-size should not exceed 1000"
        )

    if not 0 <= args.min_confidence <= 1:
        raise ValueError(
            "--min-confidence must be between 0 and 1"
        )


def resolve_station_id(args: argparse.Namespace) -> str:
    if args.station:
        return str(args.station)

    try:
        with args.station_file.open(encoding="utf-8") as file:
            payload = json.load(file)
        station_id = payload["station"]["id"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(
            f"Could not read station.id from {args.station_file}: {exc}"
        ) from exc

    if station_id is None or not str(station_id).strip():
        raise ValueError(f"station.id is empty in {args.station_file}")
    return str(station_id)


def main() -> int:
    args = parse_args()

    try:
        validate_args(args)
        station_id = resolve_station_id(args)

        detections, api_metadata = fetch_detections(
            station_id=station_id,
            limit=args.limit,
            page_size=args.page_size,
            min_confidence=args.min_confidence,
            days=args.days,
            timezone=args.timezone,
        )

        species_summary = build_species_summary(
            detections
        )

        print_summary(
            station_id=station_id,
            days=args.days,
            min_confidence=args.min_confidence,
            detections=detections,
            species_summary=species_summary,
            api_metadata=api_metadata,
        )

        complete = save_json(
            output_dir=args.output_dir,
            station_id=station_id,
            days=args.days,
            timezone=args.timezone,
            min_confidence=args.min_confidence,
            detections=detections,
            species_summary=species_summary,
            api_metadata=api_metadata,
        )
        if not complete:
            return 3

    except requests.Timeout:
        print(
            "BirdWeather request timed out.",
            file=sys.stderr,
        )
        return 1

    except requests.RequestException as exc:
        print(
            f"BirdWeather request failed: {exc}",
            file=sys.stderr,
        )
        return 1

    except Exception as exc:
        print(
            f"Error: {exc}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
