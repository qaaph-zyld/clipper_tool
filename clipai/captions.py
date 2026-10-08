"""Caption rendering: karaoke ASS + SRT + VTT from a Transcript.

Captions are an OVERLAY composited on the reframed video — never a reserved
band (CONTRACTS #13). Latin Serbian display text only. Karaoke uses \\kf
(word-fill centiseconds). Bundled DejaVu Sans covers č ć đ š ž.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from .types import Transcript, Word

FONTS_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
FONT = "DejaVu Sans"

MAX_WORDS_PER_LINE = 6
MAX_CHARS_PER_LINE = 32

ASS_HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,{FONT},62,&H00FFFFFF,&H0000C8FF,&H00141414,&H96000000,-1,0,0,0,100,100,0,0,1,3.2,1.6,2,60,60,180,1
Style: Rail,{FONT},54,&H00F0F0F0,&H000000FF,&H00141414,&H96000000,0,0,0,0,100,100,0,0,1,2.8,1.4,2,60,60,160,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _sec_to_ass(t: float) -> str:
    if t < 0:
        t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _sec_to_srt(t: float) -> str:
    if t < 0:
        t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def _escape_ass(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _clip_words(t: Transcript, start: float, end: float) -> List[Word]:
    out = []
    for _, w in t.iter_words():
        if w.start >= start - 1e-3 and w.end <= end + 1e-3:
            out.append(w)
    return out


def _group_lines(words: List[Word]) -> List[List[Word]]:
    """Chunk into caption lines: <=6 words AND <=32 chars, break at .,!?"""
    lines: List[List[Word]] = []
    cur: List[Word] = []
    cur_len = 0
    for w in words:
        wl = len(w.w)
        if cur and (cur_len + wl + 1 > MAX_CHARS_PER_LINE
                    or len(cur) >= MAX_WORDS_PER_LINE
                    or cur[-1].w.rstrip()[-1:] in ".!?"):
            lines.append(cur)
            cur, cur_len = [], 0
        cur.append(w)
        cur_len += wl + 1
    if cur:
        lines.append(cur)
    return lines


def build_ass(t: Transcript, clip_start: float, clip_end: float,
              karaoke: bool = True, offset: Optional[float] = None) -> str:
    """Karaoke ASS for [clip_start, clip_end]; times re-based to clip start."""
    off = clip_start if offset is None else offset
    words = _clip_words(t, clip_start, clip_end)
    out = [ASS_HEADER]
    for line in _group_lines(words):
        start = _sec_to_ass(line[0].start - off)
        end = _sec_to_ass(line[-1].end - off)
        style = "Karaoke" if karaoke else "Rail"
        if karaoke:
            parts = []
            for w in line:
                kf = max(1, round((w.end - w.start) * 100))  # centiseconds
                parts.append(f"{{\\kf{kf}}}{_escape_ass(w.w)}")
            text = " ".join(parts)
        else:
            text = _escape_ass(" ".join(w.w for w in line))
        out.append(f"Dialogue: 0,{start},{end},{style},,0,0,0,,{text}")
    return "\n".join(out) + "\n"


def build_srt(t: Transcript, clip_start: float = 0.0,
              clip_end: Optional[float] = None) -> str:
    end = clip_end if clip_end is not None else float("inf")
    words = _clip_words(t, clip_start, end)
    lines = []
    for i, line in enumerate(_group_lines(words), 1):
        lines.append(f"{i}\n{_sec_to_srt(line[0].start - clip_start)} --> "
                     f"{_sec_to_srt(line[-1].end - clip_start)}\n"
                     f"{' '.join(w.w for w in line)}\n")
    return "\n".join(lines)


def build_vtt(t: Transcript, clip_start: float = 0.0,
              clip_end: Optional[float] = None) -> str:
    srt = build_srt(t, clip_start, clip_end)
    body = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", srt)
    body = re.sub(r"^\d+\n(?=\d{2}:)", "", body, flags=re.M)
    return "WEBVTT\n\n" + body
