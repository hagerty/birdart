#!/usr/bin/env python3

"""Prepare an artwork file for a 4K Samsung Frame and publish it."""

from __future__ import annotations

import argparse
import json
import logging
import socket
import sys
import time
from pathlib import Path

from PIL import Image, ImageColor, ImageOps
from samsungtvws import SamsungTVWS

from birdart_io import atomic_write_text

LOG = logging.getLogger("frame-publish")
FRAME_SIZE = (3840, 2160)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fit artwork to 4K, upload it to a Samsung Frame, and display it."
    )
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--host", help="Frame TV IP address; omit with --prepare-only")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("data_input/frame.json"),
        help="Frame configuration JSON. Default: data_input/frame.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Prepared JPEG path (default: images_output/<name>_frame_4k.jpg)",
    )
    parser.add_argument(
        "--fit",
        choices=("contain", "cover", "stretch"),
        default="contain",
        help="Aspect-ratio policy; contain is safest for generated text",
    )
    parser.add_argument("--background", default="#eee4cf")
    parser.add_argument("--quality", type=int, default=95)
    parser.add_argument("--matte", help="Override the matte from --config")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--content-id-output",
        type=Path,
        default=Path("data_output/last_content_id.txt"),
        help="Write the verified Samsung content ID here.",
    )
    return parser.parse_args()


def prepare_image(
    source: Path,
    output: Path,
    fit: str,
    background: str,
    quality: int,
) -> None:
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")

        if fit == "cover":
            prepared = ImageOps.fit(
                image, FRAME_SIZE, method=Image.Resampling.LANCZOS
            )
        elif fit == "stretch":
            prepared = image.resize(FRAME_SIZE, Image.Resampling.LANCZOS)
        else:
            prepared = Image.new("RGB", FRAME_SIZE, ImageColor.getrgb(background))
            contained = ImageOps.contain(
                image, FRAME_SIZE, method=Image.Resampling.LANCZOS
            )
            offset = (
                (FRAME_SIZE[0] - contained.width) // 2,
                (FRAME_SIZE[1] - contained.height) // 2,
            )
            prepared.paste(contained, offset)

        output.parent.mkdir(parents=True, exist_ok=True)
        prepared.save(output, "JPEG", quality=quality, subsampling=0, optimize=True)


def extract_content_id(response: object) -> str:
    if isinstance(response, dict):
        response = response.get("content_id") or (
            response.get("data", {}).get("content_id")
            if isinstance(response.get("data"), dict)
            else None
        )
    if response is None or not str(response).strip():
        raise RuntimeError("The Frame did not return a valid content ID.")
    return str(response)


def close_quietly(tv: SamsungTVWS) -> None:
    try:
        tv.close()
    except Exception:
        LOG.warning("Frame connection close failed", exc_info=True)


def upload(host: str, image: Path, matte: str) -> str:
    LOG.info("Connecting to Frame at %s", host)
    tv = SamsungTVWS(host, timeout=20)
    try:
        art = tv.art()
        LOG.info("Checking Art Mode support")
        if not art.supported():
            raise RuntimeError("The television did not report Frame Art Mode support.")
        LOG.info("Uploading %s", image)
        content_id = extract_content_id(
            art.upload(str(image), matte=matte, portrait_matte=matte)
        )
        LOG.info("Upload completed (content ID: %s)", content_id)
        return content_id
    finally:
        close_quietly(tv)


def select_and_verify(host: str, content_id: str) -> None:
    tv = SamsungTVWS(host, timeout=20)
    try:
        art = tv.art()
        art.select_image(content_id, show=True)
        current_id = extract_content_id(art.get_current())
        if current_id != content_id:
            raise RuntimeError(
                f"Frame selected {current_id}, expected {content_id}."
            )
        LOG.info("New artwork selected and verified")
    finally:
        close_quietly(tv)


def resolve_frame_config(args: argparse.Namespace) -> dict:
    payload: dict = {}
    if args.config.is_file():
        with args.config.open(encoding="utf-8") as file:
            payload = json.load(file)
    payload["host"] = args.host or payload.get("host")
    payload["matte"] = args.matte or payload.get("matte") or "none"
    return payload


def wake_frame(mac: str, host: str, configured_broadcast: str | None = None) -> None:
    compact = mac.replace(":", "").replace("-", "")
    if len(compact) != 12:
        raise ValueError(f"Invalid Frame MAC address: {mac}")
    magic_packet = bytes.fromhex("FF" * 6 + compact * 16)
    octets = host.split(".")
    destinations = {"255.255.255.255"}
    if configured_broadcast:
        destinations.add(configured_broadcast)
    if len(octets) == 4:
        destinations.add(".".join(octets[:3] + ["255"]))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for destination in destinations:
            sock.sendto(magic_packet, (destination, 9))


def main() -> int:
    args = parse_args()
    try:
        frame_config = resolve_frame_config(args)
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        LOG.error("Could not read Frame configuration: %s", exc)
        return 2
    source = args.image.expanduser().resolve()
    if not source.is_file():
        LOG.error("Image does not exist: %s", source)
        return 2
    if not 1 <= args.quality <= 100:
        LOG.error("--quality must be between 1 and 100")
        return 2
    host = frame_config.get("host")
    matte = frame_config.get("matte", "none")
    if not args.prepare_only and not host:
        LOG.error("Frame host is missing from --host and %s", args.config)
        return 2

    output = args.output
    if output is None:
        output = Path("images_output") / f"{source.stem}_frame_4k.jpg"
    output = output.expanduser().resolve()

    try:
        prepare_image(source, output, args.fit, args.background, args.quality)
        LOG.info("Prepared 3840x2160 artwork: %s", output)
        if args.prepare_only:
            return 0
        if frame_config.get("wake_before_upload") and frame_config.get("mac"):
            LOG.info("Sending Wake-on-LAN packet to Frame")
            wake_frame(
                str(frame_config["mac"]),
                str(host),
                frame_config.get("broadcast_address"),
            )
            time.sleep(max(0, int(frame_config.get("wake_wait_seconds", 12))))

        attempts = max(1, int(frame_config.get("connection_attempts", 1)))
        retry_delay = max(0, int(frame_config.get("retry_delay_seconds", 20)))
        content_id = upload(str(host), output, str(matte))
        for attempt in range(1, attempts + 1):
            try:
                select_and_verify(str(host), content_id)
                break
            except Exception:
                if attempt == attempts:
                    raise
                LOG.warning(
                    "Frame attempt %d/%d failed; retrying in %d seconds",
                    attempt,
                    attempts,
                    retry_delay,
                    exc_info=True,
                )
                time.sleep(retry_delay)
        LOG.info("Artwork is now displayed (content ID: %s)", content_id)
        atomic_write_text(args.content_id_output, content_id + "\n")
        return 0
    except Exception:
        LOG.exception("Frame publishing failed")
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
