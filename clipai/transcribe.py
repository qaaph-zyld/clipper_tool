"""Pipeline orchestrator: audio -> ASR -> normalize -> align -> flags ->
transcript.json, with per-stage checkpointing for crash-resume on multi-hour
inputs (CONTRACTS: schema-validated on every save)."""
from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .correct.flags import apply_flags
from .normalize import normalize_display, transliterate_words
from .types import Segment, Transcript, TranscriptMeta, Word

logger = logging.getLogger("clipai.transcribe")

STAGES = ["asr", "normalize", "align", "flags"]


def extract_audio(video_path: Path, out_dir: Path) -> Path:
    """ffmpeg -> 16kHz mono wav beside outputs."""
    wav = out_dir / "audio_16k.wav"
    if wav.exists():
        return wav
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-vn", "-ar", "16000", "-ac", "1",
         str(wav)], check=True, capture_output=True)
    return wav


class Checkpoint:
    def __init__(self, workdir: Path):
        self.dir = workdir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / "checkpoint.json"

    def done(self, stage: str) -> bool:
        if not self.file.exists():
            return False
        try:
            return json.loads(self.file.read_text()).get(stage) == "done"
        except Exception:
            return False

    def mark(self, stage: str, extra: Optional[dict] = None) -> None:
        data = json.loads(self.file.read_text()) if self.file.exists() else {}
        data[stage] = "done"
        data.update(extra or {})
        self.file.write_text(json.dumps(data), encoding="utf-8")


def _to_transcript(raw: dict, engine: str, hotwords_topic: Optional[str],
                   source_video: Optional[str]) -> Transcript:
    segs = []
    for i, s in enumerate(raw["segments"]):
        words = [Word(w=w["word"], start=w["start"], end=w["end"], prob=w.get("prob"))
                 for w in s.get("words", [])]
        segs.append(Segment(id=s.get("id", i), start=s["start"], end=s["end"],
                            text=s["text"].strip(), words=words))
    return Transcript(
        lang=raw.get("language", "sr"), script="cyrillic",
        meta=TranscriptMeta(model=engine, hotwords_topic=hotwords_topic,
                            source_video=source_video,
                            created=datetime.now(timezone.utc).isoformat(),
                            align_method="fw-word-ts"),
        segments=segs)


def _normalize(t: Transcript) -> Transcript:
    for seg in t.segments:
        if seg.words:
            lat, cyr = transliterate_words([w.w for w in seg.words])
            for w, lw, cw in zip(seg.words, lat, cyr):
                w.w, w.cyr = lw, cw or w.cyr
            seg.text = normalize_display(seg.text)
        else:
            seg.text = normalize_display(seg.text)
    t.script = "latin"
    return t


def run(video_path: Path, out_dir: Path, engine: Optional[str] = None,
        language: str = "sr", hotwords_topic: Optional[str] = None,
        do_align: bool = True) -> Transcript:
    from . import asr as asr_mod

    out_dir = Path(out_dir)
    ck = Checkpoint(out_dir)
    audio = extract_audio(Path(video_path), out_dir)

    engine = asr_mod.resolve_engine(language, engine)
    raw_path = out_dir / "asr_raw.json"
    if ck.done("asr") and raw_path.exists():
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        logger.info("resume: asr loaded from checkpoint")
    else:
        raw = asr_mod.transcribe(str(audio), engine=engine, language=language,
                                 hotwords_topic=hotwords_topic)
        raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        ck.mark("asr")

    t = _to_transcript(raw, engine, hotwords_topic, str(video_path))

    if not ck.done("normalize"):
        t = _normalize(t)
        ck.mark("normalize")
    else:
        t = _normalize(t)  # deterministic; always reapply (cheap)

    if do_align and not ck.done("align"):
        from .align import align
        try:
            align(t, str(audio))
        except Exception as e:
            logger.warning("align stage failed: %s", e)
        ck.mark("align")
    else:
        logger.info("resume: align skipped (done or disabled)")

    if not ck.done("flags"):
        apply_flags(t)
        ck.mark("flags")

    t.save(out_dir / "transcript.json")
    logger.info("transcript.json written (%d segments)", len(t.segments))
    return t
