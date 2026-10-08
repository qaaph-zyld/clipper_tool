"""ASR engine registry — faster-whisper backends, Serbian-first defaults.

`--lang sr` MUST route here (sr-v3-ct2). The whisperx-medium path that produced
garbled mixed-script output is gone; whisperx is only used for alignment.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("clipai.asr")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SR_MODEL = ROOT / "models" / "sr-v3-ct2"
HOTWORDS_FILE = ROOT / "hotwords_sr.txt"
DEFAULT_PROMPT_SR = "Ово је српски подкаст."

ENGINES: Dict[str, dict] = {
    # name -> faster-whisper model spec. "default" resolves per language.
    "sr-v3-ct2": {"model": str(DEFAULT_SR_MODEL), "kind": "ct2-dir"},
    "large-v3": {"model": "large-v3", "kind": "systran"},
    "turbo": {"model": "deepdml/faster-whisper-large-v3-turbo-ct2", "kind": "systran"},
    "medium": {"model": "medium", "kind": "systran"},
    "small": {"model": "small", "kind": "systran"},
}

DEFAULT_ENGINE_FOR_LANG = {"sr": "sr-v3-ct2"}


def resolve_engine(language: Optional[str], engine: Optional[str]) -> str:
    if engine:
        return engine
    return DEFAULT_ENGINE_FOR_LANG.get(language or "", "medium")


def parse_hotwords_file(path: Path, topic: Optional[str] = None) -> str:
    """Shared hotwords parser (headers/comments stripped); mirrors the proven
    transcribe_sr.py implementation."""
    sections: Dict[str, List[str]] = {}
    current = ""
    header = re.compile(r"^\[.+\]$")
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if header.match(line):
            current = line[1:-1].strip()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    if topic is not None:
        return " ".join(sections.get(topic.strip(), []))
    return " ".join(w for ws in sections.values() for w in ws)


def transcribe(audio_path: str, engine: str, language: str = "sr",
               beam_size: int = 5, hotwords_topic: Optional[str] = None,
               initial_prompt: Optional[str] = None,
               on_segment=None) -> dict:
    """Run a faster-whisper engine; returns whisper-style dict with word ts.
    on_segment(seg_end_s, total_duration_s) fires per decoded segment —
    drives live job progress + rolling ETA."""
    from faster_whisper import WhisperModel

    spec = ENGINES[engine]
    hw = None
    if language == "sr" and HOTWORDS_FILE.exists():
        hw = parse_hotwords_file(HOTWORDS_FILE, topic=hotwords_topic)
        if hotwords_topic and not hw:
            raise ValueError(f"hotwords topic '{hotwords_topic}' empty/missing")
    prompt = initial_prompt or (DEFAULT_PROMPT_SR if language == "sr" else None)

    logger.info("ASR engine=%s model=%s lang=%s", engine, spec["model"], language)
    model = WhisperModel(spec["model"], device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        audio_path, language=language, beam_size=beam_size,
        word_timestamps=True, vad_filter=True,
        hotwords=hw, initial_prompt=prompt,
    )
    segs = []
    for seg in segments:
        if on_segment:
            try:
                on_segment(seg.end, info.duration or 0)
            except Exception:
                pass
        segs.append({
            "id": seg.id, "start": round(seg.start, 3), "end": round(seg.end, 3),
            "text": seg.text.strip(),
            "words": [
                {"word": w.word.strip(), "start": round(w.start, 3),
                 "end": round(w.end, 3), "prob": round(w.probability, 4)}
                for w in (seg.words or [])
            ],
        })
    return {"language": info.language, "language_probability": round(info.language_probability, 4),
            "segments": segs, "engine": engine,
            "hotwords_topic": hotwords_topic, "duration": info.duration}
