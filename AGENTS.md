# AGENTS.md — clips-ai-tool

## Inputs

- Video files in `input/` (.mp4, .mov, .avi, .mkv, .webm, .ts)
- `config.json` for default settings
- `.env` for OpenAI API key (optional, only for `--gpt-correct`)

## Process (legacy `main.py`)

1. Extract audio via ffmpeg
2. Transcribe with WhisperX (CPU, int8)
3. Optional: GPT-4o-mini transcript correction
4. Score clip candidates (density, hooks, sentiment, keywords, scene cuts)
5. Select non-overlapping top-N clips
6. Crop to 9:16 with face-aware centering
7. Burn ASS captions via two-pass ffmpeg
8. Save clips + metadata to `output/`

## Process (Serbian `clipai/` package — `python -m clipai` / run_ui.bat)

1. `transcribe.py` — ffmpeg audio extract → faster-whisper engine registry
   (`--lang sr` routes to `models/sr-v3-ct2`, never whisperx-medium) →
   Cyr→Lat normalize → wav2vec2-juznevesti-sr alignment (stable-ts /
   fw-word-ts fallback chain) → Hunspell+confidence flagging.
   Checkpoints per stage in `output/<job>/checkpoint.json`.
2. `score.py` — Serbian lexicons (`clipai/lexicon/`), same formula as legacy.
3. `smartcut.py`/`splice.py` — VAD-snap cut PROPOSALS (never auto-applied),
   8–15 ms audio crossfades at rejoins.
4. `reframe.py` — YuNet (`clipai/assets/models/*.onnx`) face tracking,
   per-segment crop trajectory, hard reset at cuts.
5. `captions.py`/`render.py` — karaoke ASS (\kf) + SRT/VTT, Latin-only,
   captions as overlay (no reserved band).
6. `webapp.py`/`jobs.py` — Flask UI: serialized job queue (one CPU worker),
   fix-queue for flagged words, Latin edit sets `edited=true` (cyr is
   provenance-only), tier-0/tier-1 suggestions are accept/reject overlays.

## Contracts

`clipai/contracts/CONTRACTS.md` + `transcript.schema.json` are the source of
truth for transcript.json invariants; `clipai/types.py` enforces them.
77 tests in `tests/` must stay green.

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
