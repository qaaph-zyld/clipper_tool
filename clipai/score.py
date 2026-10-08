"""Serbian clip scoring — ported from main.py, lexicons swapped to
clipai/lexicon/ (Latin). Same formula:
  density * completeness * boundary_bonus * hook * sentiment * keyword
  * scene_cut_density * log1p(word_count)
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Set

from .types import Transcript

logger = logging.getLogger("clipai.score")

LEXICON = Path(__file__).resolve().parent / "lexicon"


def _load_wordlist(name: str) -> Set[str]:
    p = LEXICON / name
    if not p.exists():
        logger.warning("lexicon missing: %s", name)
        return set()
    words = set()
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or (line.startswith("[") and line.endswith("]")):
            continue
        words.update(line.lower().split())
    return words


def _load_sections(name: str) -> Dict[str, Set[str]]:
    p = LEXICON / name
    sections: Dict[str, Set[str]] = {}
    cur = ""
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            cur = line[1:-1]
            sections.setdefault(cur, set())
            continue
        sections.setdefault(cur, set()).update(line.lower().split())
    return sections


def _load_phrases(name: str) -> Set[str]:
    """Comma-separated phrases — kept whole (substring matching), NOT split
    into words (that would explode 'pre nego' into stopwords)."""
    p = LEXICON / name
    if not p.exists():
        logger.warning("lexicon missing: %s", name)
        return set()
    out = set()
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0] if not raw.lstrip().startswith("#") else ""
        for phrase in line.split(","):
            phrase = phrase.strip().lower()
            if phrase:
                out.add(phrase)
    return out


HOOKS = _load_phrases("sr_hooks.txt")
_SENT = _load_sections("sr_sentiment.txt")
POSITIVE = _SENT.get("positive", set())
NEGATIVE = _SENT.get("negative", set())
FILLERS = _load_sections("fillers_sr.txt")


def _hook_mult(text: str) -> float:
    tl = text.lower()
    matches = sum(1 for p in HOOKS if p in tl)
    return 1.0 + min(matches * 0.5, 2.0) if matches else 1.0


def _sentiment_mult(text: str) -> float:
    ws = set(text.lower().split())
    total = len(ws & POSITIVE) + len(ws & NEGATIVE)
    return min(1.0 + total * 0.1, 1.2) if total else 1.0


def _boundary_bonus(words: List[dict], start: float, end: float) -> float:
    win = [w for w in words if w["start"] >= start and w["end"] <= end]
    if not win:
        return 0.5
    bonus = 1.0
    if win[0].get("word", "")[:1].isupper():
        bonus += 0.3
    if win[-1].get("word", "").rstrip()[-1:] in "!.?":
        bonus += 0.5
    return bonus


def _keyword_mult(text: str, keywords: Optional[Set[str]]) -> float:
    if not keywords:
        return 1.0
    tl = text.lower()
    m = sum(1 for k in keywords if k.lower() in tl)
    return min(1.0 + m * 0.25, 1.5) if m else 1.0


def _scene_density(cuts: List[float], start: float, end: float) -> float:
    n = sum(1 for c in cuts if start <= c <= end)
    return min(0.8 + n * 0.15, 1.3) if n else 0.8


def find_clips(t: Transcript, num_clips: int = 5, min_duration: float = 15.0,
               max_duration: float = 60.0, scene_cuts: Optional[List[float]] = None,
               keywords: Optional[Set[str]] = None, step: float = 3.0) -> List[dict]:
    """Greedy non-overlap top-N windows. Operates on the Transcript contract."""
    words = []
    for s in t.segments:
        for w in s.words:
            words.append({"start": w.start, "end": w.end, "word": w.w})
        if not s.words:
            words.append({"start": s.start, "end": s.end, "word": s.text})
    if not words:
        raise ValueError("transcript has no words/timestamps")
    total = words[-1]["end"]

    cands = []
    window = min_duration
    while window <= max_duration:
        start = words[0]["start"]
        while start + window <= total:
            end = start + window
            seg_words = [w for w in words if start <= w["start"] and w["end"] <= end]
            if not seg_words:
                start += step
                continue
            text = " ".join(w["word"] for w in seg_words).strip()
            n = len(text.split())
            density = n / (end - start)
            if density < 0.3:
                start += step
                continue
            score = (density
                     * (1.0 if text and text[-1] in "!.?" else 0.5)
                     * _boundary_bonus(words, start, end)
                     * _hook_mult(text)
                     * _sentiment_mult(text)
                     * _keyword_mult(text, keywords)
                     * _scene_density(scene_cuts or [], start, end)
                     * math.log1p(n))
            cands.append({"start": start, "end": end, "text": text,
                          "score": score, "word_count": n})
            start += step
        window += 5.0

    cands.sort(key=lambda c: c["score"], reverse=True)
    clips = []
    for c in cands:
        if len(clips) >= num_clips:
            break
        if all(c["end"] <= e["start"] or c["start"] >= e["end"] for e in clips):
            clips.append(c)
    return sorted(clips, key=lambda c: c["start"])
