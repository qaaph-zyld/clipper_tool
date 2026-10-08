# clips-ai-tool

Extract viral short clips from long videos with AI-powered transcription, caption burning, and smart clip scoring.

## Features

- **WhisperX transcription** — local, CPU-based, supports multiple languages
- **GPT-4o-mini correction** — optional transcript post-correction for better accuracy
- **Smart clip scoring** — density, hook words, sentence boundaries, sentiment, keyword boost, scene cut density
- **9:16 crop with face detection** — auto-centers on faces for vertical format
- **ASS caption burning** — timed, styled subtitles burned into output video
- **Batch processing** — process all videos in `input/` in one run
- **Per-video output** — batch mode creates subdirectories per video

## Setup

```bash
pip install -r requirements.txt
```

Requires [ffmpeg](https://ffmpeg.org/) in PATH.

Copy `.env.example` to `.env` and add your OpenAI API key (only needed for `--gpt-correct`):

```bash
cp .env.example .env
```

## Usage

### Single video

```bash
python main.py input/my_video.mp4
```

### Batch process all videos in input/

```bash
python main.py --batch
```

### With Serbian language and GPT correction

```bash
python main.py --batch --language sr --gpt-correct --num-clips 3
```

### All options

```
python main.py --help
```

| Flag | Default | Description |
|------|---------|-------------|
| `input` | (auto) | Path to video file (omit to use input/ folder) |
| `--batch` | off | Process all videos in input/ |
| `--language` | auto | Language code (sr, en, etc.) |
| `--gpt-correct` | off | Enable GPT-4o-mini transcript correction |
| `--gpt-model` | gpt-4o-mini | GPT model for correction |
| `--num-clips` | 5 | Number of clips to extract |
| `--min-duration` | 15.0 | Minimum clip duration (seconds) |
| `--max-duration` | 60.0 | Maximum clip duration (seconds) |
| `--output-dir` | output/ | Output directory |
| `--model` | medium | WhisperX model size |
| `--config` | config.json | Path to config file |
| `--verbose` | off | Debug logging |

## Config File

`config.json` provides defaults overridable by CLI args:

```json
{
  "language": "sr",
  "gpt_correct": false,
  "model": "medium",
  "num_clips": 5,
  "keyword_boost": ["your", "custom", "keywords"]
}
```

## Output

Each clip produces:
- `short_NN.mp4` — 9:16 vertical clip with burned captions
- `short_NN.ass` — ASS subtitle file
- `short_NN.json` — metadata (timestamps, score, text, crop info)

In batch mode, outputs go to `output/<video_name>/`.

## How Clip Scoring Works

Each candidate clip window is scored by:

```
score = density * completeness * boundary_bonus * hook_multiplier
        * sentiment_score * keyword_boost * scene_cut_density * log1p(word_count)
```

- **Density** — words per second
- **Completeness** — bonus for ending on sentence punctuation
- **Boundary bonus** — bonus for starting on capital letter
- **Hook multiplier** — 1.0-3.0x for viral hook phrases
- **Sentiment score** — 0.8-1.2x for emotional content
- **Keyword boost** — 1.0-1.5x for configured keywords
- **Scene cut density** — 0.8-1.3x for visual dynamism

Non-overlapping top-N clips are selected.
