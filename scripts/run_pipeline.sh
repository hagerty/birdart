#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname -- "$SCRIPT_DIR")
cd "$PROJECT_DIR"

.venv/bin/python src/birdweather_history.py --days 1 --output-dir data_output
.venv/bin/python src/birdweather_history.py --days 90 --output-dir data_output
.venv/bin/python src/build_artwork_prompt.py
.venv/bin/python src/generate_artwork.py \
  --reference images_input/fountain.png \
  --reference images_input/sample_update.png \
  --output images_output/generated_artwork.png
.venv/bin/python src/frame_publish.py --image images_output/generated_artwork.png
.venv/bin/python src/record_featured_history.py \
  --content-id "$(tr -d '\n' < data_output/last_content_id.txt)"
