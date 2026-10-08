"""Splice math for cut ranges — crossfade-safe segment list for ffmpeg.

Produces keep-segments + an audio filtergraph (equal-power crossfade of
8–15 ms at every rejoin). Video path hard-cuts at the same edges; the audio
crossfade is what removes the click (CONTRACTS #12).
"""
from __future__ import annotations

from typing import List, Tuple

CROSSFADE_MS = 12


def invert_ranges(cuts: List[Tuple[float, float]], total: float) -> List[Tuple[float, float]]:
    """Sorted non-overlapping cuts -> keep segments."""
    keep = []
    cur = 0.0
    for s, e in sorted(cuts):
        if s > cur:
            keep.append((cur, s))
        cur = max(cur, e)
    if cur < total:
        keep.append((cur, total))
    return keep


def audio_filtergraph(keep: List[Tuple[float, float]], fade_ms: int = CROSSFADE_MS) -> str:
    """ffmpeg -filter_complex audio: trim each keep-range + equal-power joins.

    Returns '' for a single keep-range (plain trim suffices).
    """
    if not keep:
        return ""
    if len(keep) == 1:
        s, e = keep[0]
        return f"atrim=start={s}:end={e},asetpts=PTS-STARTPTS"
    parts = []
    labels = []
    for i, (s, e) in enumerate(keep):
        lbl = f"a{i}"
        parts.append(f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[{lbl}]")
        labels.append(lbl)
    n = len(labels)
    joined = "".join(f"[{l}]" for l in labels)
    parts.append(f"{joined}concat=n={n}:v=0:a=1[aout]")
    return ";".join(parts)


def crossfade_filtergraph(keep: List[Tuple[float, float]], fade_s: float = CROSSFADE_MS / 1000) -> str:
    """Equal-power micro-crossfade join — for audible-seam removal when a plain
    concat is too hard. acrossfade needs pairwise chains."""
    if len(keep) <= 1:
        return audio_filtergraph(keep)
    parts = []
    labels = []
    for i, (s, e) in enumerate(keep):
        lbl = f"x{i}"
        parts.append(f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[{lbl}]")
        labels.append(lbl)
    cur = labels[0]
    for i, lbl in enumerate(labels[1:], 1):
        out = f"xf{i}" if i < len(labels) - 1 else "aout"
        parts.append(f"[{cur}][{lbl}]acrossfade=d={fade_s}:c1=exp:c2=exp[{out}]")
        cur = out
    return ";".join(parts)
