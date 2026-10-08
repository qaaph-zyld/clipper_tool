# AGENTS.md — clips-ai-tool

## Inputs

- Video files in `input/` (.mp4, .mov, .avi, .mkv, .webm, .ts)
- `config.json` for default settings
- `.env` for OpenAI API key (optional, only for `--gpt-correct`)

## Process

1. Extract audio via ffmpeg
2. Transcribe with WhisperX (CPU, int8)
3. Optional: GPT-4o-mini transcript correction
4. Score clip candidates (density, hooks, sentiment, keywords, scene cuts)
5. Select non-overlapping top-N clips
6. Crop to 9:16 with face-aware centering
7. Burn ASS captions via two-pass ffmpeg
8. Save clips + metadata to `output/`

## Outputs

- `output/short_NN.mp4` — vertical clips with burned captions
- `output/short_NN.ass` — ASS subtitle files
- `output/short_NN.json` — clip metadata
- Batch mode: `output/<video_stem>/` per video

## Conventions

- Python 3.13+, CPU-only (no GPU assumptions)
- ffmpeg/ffprobe must be in PATH
- WhisperX model loaded per-run (no persistent model cache)
- All logging via Python `logging` module (no bare prints)
- CLI args override config.json overrides defaults
