# Serbian Clip Studio — implementation status (sr-clip-studio branch)

_Last updated: bake-off resuming; W1–W5 code complete, 75 tests green._

## What exists (all committed)

| Module | Role | State |
|---|---|---|
| `clipai/types.py` | pydantic contracts (schema v1.0) | ✅ enforced, 75 tests |
| `clipai/contracts/` | CONTRACTS.md + transcript.schema.json | ✅ source of truth |
| `clipai/normalize.py` | Cyr→Lat, all-caps digraph fix (ЉУБАВ→LJUBAV), align tokens | ✅ |
| `clipai/asr.py` | engine registry; `--lang sr`→`sr-v3-ct2`; per-segment progress cb | ✅ |
| `clipai/align.py` | wav2vec2-sr (whisperx model_name) → stable-ts → fw-word-ts; word-count mismatch marks weak | ✅ |
| `clipai/transcribe.py` | checkpointed orchestrator; resume-after-align loads transcript.json | ✅ |
| `clipai/correct/` | flags (prob<0.65|dict_miss), tier0 (dict→fuzzy→phonetic), tier1 (SRBerta fill-mask) | ✅ tier1 opt-in |
| `clipai/score.py` | Serbian lexicons; hooks are PHRASES (comma-separated, not exploded) | ✅ |
| `clipai/smartcut.py` | VAD-snap cut proposals, escalation ladder | ✅ proposals only |
| `clipai/splice.py` | keep-invert + concat/crossfade filtergraphs | ✅ |
| `clipai/captions.py` | karaoke `\kf` ASS + SRT + VTT, Latin-only | ✅ tested |
| `clipai/reframe.py` | YuNet onnx (bundled 232KB) + EMA crop track, per-segment | ✅ |
| `clipai/render.py` | 2-pass ffmpeg; cut-aware caption time remap; absolute paths; hard-reset crop x-expr | ✅ E2E on real mp4 |
| `clipai/jobs.py` | serialized job worker, measured-RTF ETA | ✅ |
| `clipai/webapp.py` | Flask :7860 — jobs, fix-queue, click-seek audio, dblclick edit, accept/reject suggestions, delete-ranges, render | ✅ smoke-tested |
| `clipai/assets/` | DejaVu fonts + YuNet onnx | ✅ committed |
| `eval/` | bakeoff.py (resumable), score.py, report.py, spikes | running |

## Decisions locked

- Latin-only captions; Cyrillic is provenance-only (`word.cyr`), edits never
  reverse-transliterate (`edited:true`).
- Smart-cut = proposals + operator accept; render applies union of accepted
  proposals and operator delete-ranges.
- Tier-1 = SRBerta (`RobertaForMaskedLM`) opt-in per word. BERTić is an
  ELECTRA discriminator — rescore role only, never generates.
- i7-4770 CPU: measured RTF 3.1–10.5×; honest ETA = dur×RTF×1.15.
- Bake-off RTF numbers recorded under some CPU contention — treat as upper
  bounds.

## In-flight / TODO

- `eval/bakeoff.py` running (resumed, skips done excerpts): ex4/ex5 for
  sr-v3-ct2, then fw-medium/large-v3/turbo — ~1.5–2h.
- After it: `python -X utf8 eval/score.py` → `python eval/report.py` →
  `eval/w0_report.md`; write proxy refs for ex4/ex5 (transliterate
  sr-v3-ct2 hyp, hand-correct).
- E2E `transcribe.run` on nenad mp4 → `output/_e2e/` (running; verifies
  checkpoint + align + flags on real audio).
- Remaining: main.py thin-shim to new pipeline (legacy stays), real-podcast
  full run, adversarial W6 pass.

## How to resume

```bash
cd D:\Projects\Tools\clips-ai-tool && git checkout sr-clip-studio
python -m pytest tests -x -q     # expect 75+ green
python -X utf8 -m clipai.webapp  # UI smoke: http://127.0.0.1:7860
```
