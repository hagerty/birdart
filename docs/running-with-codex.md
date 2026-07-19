# Running BirdArt with Codex

Codex can operate BirdArt interactively or as a recurring automation. Keep all
private configuration and reference images in the ignored runtime paths; do not
paste station IDs, API keys, IP addresses, or MAC addresses into prompts that
you intend to share.

## Initial setup

1. Clone the repository and open its folder as a local Codex project.
2. Ask Codex to create the virtual environment and install
   `requirements-lock.txt`.
3. Copy the two committed example configurations to their private runtime names:

   ```text
   data_input/station.example.json -> data_input/station.json
   data_input/frame.example.json   -> data_input/frame.json
   ```

4. Fill in the private station and Frame values locally. Place the environmental
   and style references in `images_input/fountain.png` and
   `images_input/sample_update.png`.
5. Ask Codex to run the privacy checks from the main README before any commit.

Codex may request approval for internet access to BirdWeather or OpenAI and for
local-network access to the Frame. Review the exact command and destination
before approving it. Never commit an API key; if using the API-backed generator,
provide `OPENAI_API_KEY` through the process environment or a secret manager.

## Interactive run

The following prompt gives Codex an explicit, verifiable workflow:

```text
Run the BirdArt workflow from this repository.

1. Query the station for 1 day and 90 days.
2. Stop if either query fails or history pagination is incomplete.
3. Build today's resolved artwork prompt.
4. Generate one landscape artwork using the resolved prompt, fountain.png, and
   sample_update.png. Preserve the fountain setting and field-journal style.
5. Show me the generated image and wait for my approval before publishing.
6. After approval, prepare it for the Frame, upload it exactly once, select it,
   and verify the current Samsung content ID.
7. Record featured history only after verification succeeds.
8. Report the generated path, content ID, and verification result.
```

Codex's built-in image generation can be used for the interactive generation
step. Alternatively, ask it to run `src/generate_artwork.py`, which uses the
OpenAI Image API and requires `OPENAI_API_KEY`.

To diagnose the TV without changing its artwork, ask Codex to run:

```text
Run scripts/show_frame_status.py and summarize the current Frame selection.
Do not upload, select, or delete anything.
```

For a temporary reversible preview:

```text
Run scripts/preview_on_frame.py with my generated image for 60 seconds. Verify
that the original artwork is restored afterward and report both content IDs.
```

## Recurring Codex automation

In the Codex app, ask for a recurring automation in plain language:

```text
Create a BirdArt automation for this project at 6:00 AM, 9:00 AM, 5:00 PM,
and 9:00 PM in my local timezone. Run the full verified workflow. Notify me when
an image is created and separately when the Frame confirms the new content ID.
If generation succeeds but publishing fails, do not record featured history.
```

Confirm the automation shows the intended project folder, timezone, and four
daily run times. The machine must be awake, connected to the internet, and on
the Frame's local network. Codex automation configuration is user- and
machine-specific, so it is intentionally not committed to this repository.

## Safe operating rules

- Inspect generated text and bird depictions before publishing an interactive
  run.
- Never record the selection manifest when upload or verification fails.
- Never retry the upload after receiving a Samsung content ID; retry only
  selection and verification.
- Treat `data_output/` and `images_output/` as disposable local runtime data.
- Run `python -m unittest discover -s tests -v` after changing selection,
  history, or Frame behavior.
