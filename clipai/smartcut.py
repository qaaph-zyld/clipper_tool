"""Smart Cut — proposal engine (never auto-applies; CONTRACTS #12).

Cut points snap to VAD silence midpoints; escalation ladder:
  ±250ms -> ±1s -> mark 'no-clean-cut' (filler kept or J/L-cut in render).
Strength dial: off|gentle|aggressive — aggressive tolerates no-silence cuts.
"""
from __future__ import annotations

import logging
import re
import subprocess
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

from pydantic import BaseModel

from .score import FILLERS
from .types import Transcript, Word

logger = logging.getLogger("clipai.smartcut")

SAFE_FILLERS = FILLERS.get("safe", set())
CTX_FILLERS = FILLERS.get("context", set())


class Strength(str, Enum):
    OFF = "off"
    GENTLE = "gentle"
    AGGRESSIVE = "aggressive"


class CutProposal(BaseModel):
    start: float
    end: float
    words: List[str]           # display words being removed
    reason: str                # filler | silence_gap | operator_range
    quality: str               # clean | snapped | no-clean-cut
    snap_ms: Optional[int] = None  # distance from raw word edge to silence mid


def detect_silences(audio_path: Path, noise_db: int = -35,
                    min_dur: float = 0.35) -> List[Tuple[float, float]]:
    """ffmpeg silencedetect -> [(start,end)] on the 16k wav timeline."""
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(audio_path),
         "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
        capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", p.stderr)]
    return list(zip(starts, ends))


def _nearest_silence_mid(t: float, silences: List[Tuple[float, float]],
                         max_dist: float) -> Optional[Tuple[float, float]]:
    best = None
    for s, e in silences:
        mid = (s + e) / 2
        if abs(mid - t) <= max_dist and (best is None or abs(mid - t) < abs(best[0] - t)):
            best = (mid, abs(mid - t))
    return best


def propose_cuts(t: Transcript, audio_path: Path,
                 strength: Strength = Strength.GENTLE) -> List[CutProposal]:
    """Filler-removal proposals for [safe] fillers adjacent to silence."""
    if strength == Strength.OFF:
        return []
    silences = detect_silences(audio_path)
    proposals = []
    for seg, w in t.iter_words():
        low = w.w.lower().strip(".,!?;:")
        if low not in SAFE_FILLERS:
            continue
        # word must be bounded by silence-ish gaps (start or end within 400ms of a silence)
        near = _nearest_silence_mid(w.start, silences, 0.4) or \
            _nearest_silence_mid(w.end, silences, 0.4)
        if near is None:
            if strength == Strength.AGGRESSIVE:
                proposals.append(CutProposal(
                    start=w.start, end=w.end, words=[w.w],
                    reason="filler", quality="no-clean-cut", snap_ms=None))
            continue
        proposals.append(CutProposal(
            start=w.start, end=w.end, words=[w.w],
            reason="filler", quality="clean" if near[1] < 0.25 else "snapped",
            snap_ms=int(near[1] * 1000)))
    return proposals


def snap_cut_edge(t_edge: float, silences: List[Tuple[float, float]],
                  ladder: Tuple[float, ...] = (0.25, 1.0)) -> Tuple[float, str]:
    """Escalation ladder for a raw cut edge -> (snapped_t, quality)."""
    for window in ladder:
        hit = _nearest_silence_mid(t_edge, silences, window)
        if hit:
            mid, dist = hit
            return mid, "clean" if dist <= 0.25 else "snapped"
    return t_edge, "no-clean-cut"
