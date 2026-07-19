#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import os
from contextlib import ExitStack
from pathlib import Path

from openai import OpenAI

from birdart_io import atomic_write_bytes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate BirdArt from a resolved prompt and reference images."
    )
    parser.add_argument(
        "--prompt",
        type=Path,
        default=Path("data_output/prompt_image_generation_resolved.txt"),
    )
    parser.add_argument(
        "--reference",
        type=Path,
        action="append",
        help="Reference image; repeat for multiple inputs (default: fountain.png).",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("images_output/generated_artwork.png")
    )
    parser.add_argument("--model", default="gpt-image-2")
    parser.add_argument("--size", default="1536x1024")
    parser.add_argument("--quality", choices=("low", "medium", "high"), default="high")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set.")
    references = args.reference or [Path("images_input/fountain.png")]
    missing = [str(path) for path in [args.prompt, *references] if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required input(s): " + ", ".join(missing))

    prompt = args.prompt.read_text(encoding="utf-8")
    with ExitStack() as stack:
        images = [stack.enter_context(path.open("rb")) for path in references]
        result = OpenAI().images.edit(
            model=args.model,
            image=images,
            prompt=prompt,
            size=args.size,
            quality=args.quality,
        )
    encoded = result.data[0].b64_json if result.data else None
    if not encoded:
        raise RuntimeError("The image API returned no image data.")
    atomic_write_bytes(args.output, base64.b64decode(encoded, validate=True))
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
