#!/usr/bin/env python3
"""W0 bake-off: run ASR engines over eval excerpts, record hypotheses + timing.

Writes eval/hyp/<engine>/<excerpt>.json and eval/bakeoff_timing.json.
Sequential execution so wall-clock RTF is comparable (CPU-only box).
"""
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(r"D:\Projects\Tools\clips-ai-tool")
EXCERPTS = sorted((ROOT / "eval" / "excerpts").glob("*.wav"))
HYP = ROOT / "eval" / "hyp"
sys.path.insert(0, str(ROOT))
from transcribe_sr import parse_hotwords_file  # noqa: E402

HOTWORDS = parse_hotwords_file(ROOT / "hotwords_sr.txt")
INITIAL_PROMPT = "Ово је српски подкаст."

ENGINES = [
    {
        "name": "sr-v3-ct2",
        "model": str(ROOT / "models" / "sr-v3-ct2"),
        "hotwords": HOTWORDS,
        "initial_prompt": INITIAL_PROMPT,
    },
    {
        "name": "fw-medium",
        "model": "medium",
        "hotwords": None,
        "initial_prompt": INITIAL_PROMPT,
    },
    {
        "name": "fw-large-v3",
        "model": "large-v3",
        "hotwords": None,
        "initial_prompt": INITIAL_PROMPT,
    },
    {
        "name": "fw-turbo",
        "model": "deepdml/faster-whisper-large-v3-turbo-ct2",
        "hotwords": None,
        "initial_prompt": INITIAL_PROMPT,
    },
]


def run_engine(cfg):
    from faster_whisper import WhisperModel

    out_dir = HYP / cfg["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    log = open(out_dir / "_run.log", "w", encoding="utf-8")

    def lg(*a):
        print(cfg["name"], *a, flush=True)
        print(*a, file=log, flush=True)

    t0 = time.time()
    try:
        model = WhisperModel(cfg["model"], device="cpu", compute_type="int8")
    except Exception as e:
        lg(f"MODEL LOAD FAILED: {e}")
        log.close()
        return {"status": "load_failed", "error": str(e)}
    lg(f"model loaded in {time.time()-t0:.1f}s")

    per_file = {}
    for wav in EXCERPTS:
        if (out_dir / (wav.stem + ".json")).exists():
            lg(f"{wav.stem}: SKIP (already done)")
            continue
        try:
            t1 = time.time()
            segments, info = model.transcribe(
                str(wav), language="sr", beam_size=5,
                word_timestamps=True, vad_filter=True,
                hotwords=cfg["hotwords"], initial_prompt=cfg["initial_prompt"],
            )
            segs = []
            for seg in segments:
                segs.append({
                    "start": round(seg.start, 3), "end": round(seg.end, 3),
                    "text": seg.text.strip(),
                    "words": [
                        {"start": round(w.start, 3), "end": round(w.end, 3),
                         "word": w.word.strip(), "prob": round(w.probability, 4)}
                        for w in (seg.words or [])
                    ],
                })
            wall = time.time() - t1
            dur = info.duration or 0
            (out_dir / (wav.stem + ".json")).write_text(
                json.dumps({"segments": segs, "lang": info.language,
                            "lang_prob": info.language_probability},
                           ensure_ascii=False, indent=1), encoding="utf-8")
            per_file[wav.stem] = {"audio_s": round(dur, 1), "wall_s": round(wall, 1),
                                  "rtf": round(wall / dur, 2) if dur else None}
            lg(f"{wav.stem}: {wall:.0f}s wall / {dur:.0f}s audio = {wall/dur:.2f}x RT")
        except Exception as e:
            lg(f"{wav.stem} FAILED: {e}")
            traceback.print_exc(file=log)
            per_file[wav.stem] = {"error": str(e)}
    log.close()
    return {"status": "ok", "files": per_file}


def main():
    timing = {}
    for cfg in ENGINES:
        t0 = time.time()
        timing[cfg["name"]] = run_engine(cfg)
        timing[cfg["name"]]["engine_wall_s"] = round(time.time() - t0, 1)
    (ROOT / "eval" / "bakeoff_timing.json").write_text(
        json.dumps(timing, ensure_ascii=False, indent=1), encoding="utf-8")
    print("BAKEOFF DONE")


if __name__ == "__main__":
    main()
