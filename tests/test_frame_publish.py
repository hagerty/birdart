from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import frame_publish


class FramePublishTests(unittest.TestCase):
    def test_extract_content_id_rejects_empty_upload(self) -> None:
        with self.assertRaises(RuntimeError):
            frame_publish.extract_content_id(None)

    def test_extract_content_id_supports_nested_status_response(self) -> None:
        self.assertEqual(
            frame_publish.extract_content_id({"data": {"content_id": "MY_F1"}}),
            "MY_F1",
        )

    def test_selection_retries_do_not_repeat_upload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.png"
            image.write_bytes(b"image")
            arguments = [
                "frame_publish.py",
                "--image",
                str(image),
                "--host",
                "192.0.2.1",
            ]
            config = {
                "host": "192.0.2.1",
                "matte": "none",
                "connection_attempts": 2,
                "retry_delay_seconds": 0,
            }
            with (
                patch.object(sys, "argv", arguments),
                patch.object(frame_publish, "resolve_frame_config", return_value=config),
                patch.object(frame_publish, "prepare_image"),
                patch.object(frame_publish, "upload", return_value="MY_F1") as upload,
                patch.object(
                    frame_publish,
                    "select_and_verify",
                    side_effect=[RuntimeError("temporary"), None],
                ) as select,
            ):
                self.assertEqual(frame_publish.main(), 0)
            upload.assert_called_once()
            self.assertEqual(select.call_count, 2)


if __name__ == "__main__":
    unittest.main()
