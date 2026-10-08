"""Clip renderer: splice (cut ranges) -> reframe (9:16 face-aware) -> burn
karaoke ASS -> write mp4 + ass + srt + vtt + json.

Two ffmpeg passes per clip (crop/scale then subtitle burn), matching the
proven main.py pattern. Smart-cut deletions remap caption times onto the
output timeline; per-segment crop plans hard-reset at cut edges.
"""
from __future__ import annotations

import logging
import subprocess
from bisect import bisect_right
from pathlib import Path
from typing import List, Optional, Tuple

from . import captions as cap_mod
from . import reframe
from .splice import audio_filtergraph, invert_ranges
from .types import Transcript

logger = logging.getLogger("clipai.render")

VIDEO_PRESET = ["-c:v", "libx264", "-preset", "fast", "-crf", "23"]
AUDIO_CODEC = ["-c:a", "aac", "-b:a", "128k"]


def remap_time(t: float, cuts: List[Tuple[float, float]]) -> float:
    """Source-time -> output-time after removing cut ranges (sorted)."""
    out = t
    for s, e in cuts:
        if t > e:
            out -= e - s
        elif t > s:
            out = s - sum(en - st for st, en in cuts if en <= s)
            break
        else:
            break
    return out


def _in_cuts(t: float, cuts: List[Tuple[float, float]]) -> bool:
    return any(s < t < e for s, e in cuts)


def _shifted_transcript(t: Transcript, cuts: List[Tuple[float, float]],
                        clip_start: float) -> Transcript:
    """Deep-copy the transcript with word/segment times remapped to the output
    timeline. Words whose midpoint lies inside a deleted range are dropped;
    emptied segments are removed."""
    import copy
    tc = copy.deepcopy(t)
    kept = []
    for s in tc.segments:
        s.words = [w for w in s.words if not _in_cuts((w.start + w.end) / 2, cuts)]
        for w in s.words:
            w.start = remap_time(w.start, cuts) - clip_start
            w.end = remap_time(w.end, cuts) - clip_start
        s.start = remap_time(s.start, cuts) - clip_start
        s.end = remap_time(s.end, cuts) - clip_start
        if s.words or s.end > s.start:
            kept.append(s)
    tc.segments = kept
    return tc


def render_clip(video_path: Path, t: Transcript, clip: dict,
                out_dir: Path, index: int,
                cuts: Optional[List[Tuple[float, float]]] = None,
                karaoke: bool = True) -> dict:
    """Render one scored clip. `cuts` = smart-cut deletions inside the clip."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    start, end = clip["start"], clip["end"]
    cuts = sorted(cuts or [])
    keep = [(max(s, start), min(e, end))
            for s, e in invert_ranges(cuts, end)
            if e > start and s < end and min(e, end) - max(s, start) > 0.01]

    # caption timing basis: output timeline
    t_out = _shifted_transcript(t, cuts, clip_start=start)
    ass_path = out_dir / f"short_{index:02d}.ass"
    ass_path.write_text(cap_mod.build_ass(t_out, 0, end - start,
                                          karaoke=karaoke, offset=0),
                        encoding="utf-8")
    srt_path = out_dir / f"short_{index:02d}.srt"
    srt_path.write_text(cap_mod.build_srt(t_out, 0, end - start), encoding="utf-8")
    vtt_path = out_dir / f"short_{index:02d}.vtt"
    vtt_path.write_text(cap_mod.build_vtt(t_out, 0, end - start), encoding="utf-8")

    plan = reframe.crop_plan(video_path, start, end, keep_segments=keep)
    seg_plan = plan["segments"][0]
    x_expr = reframe.x_expression(seg_plan, start)
    vf = (f"crop={plan['crop_w']}:{plan['crop_h']}:{x_expr}:{plan['crop_y']},"
          f"scale=1080:1920")

    tmp = out_dir / f"short_{index:02d}_tmp.mp4"
    out = out_dir / f"short_{index:02d}.mp4"

    af = audio_filtergraph(keep) if len(keep) > 1 else None
    cmd1 = ["ffmpeg", "-y", "-ss", str(start), "-to", str(end),
            "-i", str(video_path)]
    if af:
        cmd1 += ["-filter_complex", af + f"[aout]", "-map", "0:v", "-map", "[aout]"]
    cmd1 += ["-vf", vf] + VIDEO_PRESET + AUDIO_CODEC + [str(tmp)]
    subprocess.run(cmd1, check=True, capture_output=True)

    cmd2 = ["ffmpeg", "-y", "-i", str(tmp),
            "-vf", f"ass='{ass_path.name}'",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy", str(out)]
    subprocess.run(cmd2, check=True, capture_output=True, cwd=str(out_dir))
    tmp.unlink(missing_ok=True)

    meta = {"index": index, "start": start, "end": end,
            "duration": end - start, "text": clip.get("text", ""),
            "score": clip.get("score"), "word_count": clip.get("word_count"),
            "cuts_removed": len(cuts),
            "crop": {"w": plan["crop_w"], "h": plan["crop_h"],
                     "mode": seg_plan["mode"]}}
    (out_dir / f"short_{index:02d}.json").write_text(
        __import__("json").dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("rendered %s", out.name)
    return meta
