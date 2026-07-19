#!/usr/bin/env python3

"""Temporarily preview artwork on a Frame, then restore its prior selection."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from contextlib import suppress
from pathlib import Path

from samsungtvws import SamsungTVWS
from samsungtvws.exceptions import ConnectionFailure, ResponseError

LOG = logging.getLogger("frame-test")


def extract_content_id(current: object) -> str:
    """
    Samsung firmware versions do not always return identical response shapes.
    The current artwork usually includes content_id directly.
    """
    if not isinstance(current, dict):
        if current is None or not str(current).strip():
            raise RuntimeError("The TV did not return a valid content_id.")
        return str(current)

    content_id = current.get("content_id")

    if not content_id and isinstance(current.get("data"), dict):
        content_id = current["data"].get("content_id")

    if not content_id:
        raise RuntimeError(
            "The TV responded, but no current content_id was found:\n"
            + json.dumps(current, indent=2)
        )

    return str(content_id)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Temporarily display an image on a Samsung Frame, "
            "then restore the previously selected artwork."
        )
    )
    parser.add_argument(
        "--host",
        help="Frame IP address; defaults to data_input/frame.json",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("data_input/frame.json"),
        help="Private Frame configuration JSON",
    )
    parser.add_argument(
        "--image",
        required=True,
        type=Path,
        help="JPEG or PNG image to upload",
    )
    parser.add_argument(
        "--seconds",
        type=int,
        default=60,
        help="How long to show the temporary image; default: 60",
    )
    parser.add_argument(
        "--keep-upload",
        action="store_true",
        help="Keep the temporary image stored on the TV after restoring the old art",
    )
    parser.add_argument(
        "--matte",
        default="none",
        help='Matte ID for the new image; default: "none"',
    )

    args = parser.parse_args()

    config = {}
    if args.config.is_file():
        config = json.loads(args.config.read_text(encoding="utf-8"))
    host = args.host or config.get("host")
    if not host:
        parser.error("Frame host is missing from --host and --config")

    image_path = args.image.expanduser().resolve()

    if not image_path.is_file():
        LOG.error("Image does not exist: %s", image_path)
        return 2

    if args.seconds < 1:
        LOG.error("--seconds must be at least 1")
        return 2

    tv: SamsungTVWS | None = None
    temporary_content_id: str | None = None
    original_content_id: str | None = None
    original_matte_id: str | None = None

    try:
        LOG.info("Connecting to Frame at %s", host)

        tv = SamsungTVWS(
            host,
            timeout=15,
        )

        art = tv.art()

        if not art.supported():
            LOG.error("This television did not report Frame Art Mode support.")
            return 3

        api_version = art.get_api_version()
        LOG.info("Frame Art API version: %s", api_version)

        # Capture the currently displayed artwork.
        current = art.get_current()
        LOG.info("Current-art response:\n%s", json.dumps(current, indent=2))

        original_content_id = extract_content_id(current)
        original_matte_id = current.get("matte_id")

        LOG.info("Original content ID: %s", original_content_id)
        LOG.info("Original matte ID: %s", original_matte_id or "(not reported)")

        # Upload returns the Samsung content ID assigned to the new image.
        LOG.info("Uploading temporary image: %s", image_path)

        temporary_content_id = extract_content_id(
            art.upload(
                str(image_path),
                matte=args.matte,
                portrait_matte=args.matte,
            )
        )

        LOG.info("Temporary content ID: %s", temporary_content_id)

        # Selecting with show=True displays the image without the less reliable
        # explicit set_artmode command used by some firmware versions.
        art.select_image(temporary_content_id, show=True)
        if extract_content_id(art.get_current()) != temporary_content_id:
            raise RuntimeError("The temporary artwork selection was not verified.")

        LOG.info(
            "Temporary artwork is displayed. Waiting %d seconds.",
            args.seconds,
        )
        time.sleep(args.seconds)

    except KeyboardInterrupt:
        LOG.warning("Interrupted. Attempting to restore original artwork.")

    except (ConnectionFailure, ResponseError) as exc:
        LOG.error("Samsung API error: %s", exc)
        return 4

    except Exception:
        LOG.exception("Unexpected failure")
        return 5

    finally:
        if tv is not None:
            try:
                art = tv.art()

                if original_content_id:
                    LOG.info(
                        "Restoring original artwork: %s",
                        original_content_id,
                    )

                    art.select_image(original_content_id, show=True)
                    if extract_content_id(art.get_current()) != original_content_id:
                        raise RuntimeError("The original artwork restoration was not verified.")

                    # Usually selecting the original content restores its
                    # existing matte automatically. This is a fallback.
                    if original_matte_id:
                        try:
                            art.change_matte(
                                original_content_id,
                                original_matte_id,
                            )
                        except Exception as exc:
                            LOG.warning(
                                "Original image was restored, but matte "
                                "restoration returned an error: %s",
                                exc,
                            )

                    LOG.info("Original artwork restored.")

                if temporary_content_id and not args.keep_upload:
                    try:
                        LOG.info(
                            "Deleting temporary upload: %s",
                            temporary_content_id,
                        )
                        deleted = art.delete(temporary_content_id)

                        if deleted:
                            LOG.info("Temporary upload deleted.")
                        else:
                            LOG.warning(
                                "TV did not confirm deletion of the temporary upload."
                            )
                    except Exception as exc:
                        LOG.warning(
                            "Artwork was restored, but the temporary upload "
                            "could not be deleted: %s",
                            exc,
                        )

            except Exception:
                LOG.exception(
                    "Could not restore the original artwork automatically. "
                    "The original content ID was: %s",
                    original_content_id,
                )

            finally:
                with suppress(Exception):
                    tv.close()

    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    sys.exit(main())
