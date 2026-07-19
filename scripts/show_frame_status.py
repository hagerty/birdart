#!/usr/bin/env python3

"""Report the artwork currently selected on a Samsung Frame."""

import argparse
import json
import sys
from pathlib import Path

from samsungtvws import SamsungTVWS


def extract_content_id(current: dict) -> str | None:
    content_id = current.get("content_id")
    if not content_id and isinstance(current.get("data"), dict):
        content_id = current["data"].get("content_id")
    return str(content_id) if content_id else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Report current Frame artwork.")
    parser.add_argument("--config", type=Path, default=Path("data_input/frame.json"))
    parser.add_argument("--host")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    host = args.host or config.get("host")
    if not host:
        parser.error("Frame host is missing")
    tv = SamsungTVWS(host, timeout=15)
    try:
        art = tv.art()
        current = art.get_current()
        content_id = extract_content_id(current)
        matching = [item for item in art.available() if item.get("content_id") == content_id]
        print(
            json.dumps(
                {"supported": art.supported(), "current": current, "content": matching},
                indent=2,
            )
        )
    finally:
        tv.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
