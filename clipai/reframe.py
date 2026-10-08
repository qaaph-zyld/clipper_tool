"""9:16 face-aware reframing — YuNet tracking, per-segment crop trajectories,
hard reset at cut boundaries (CONTRACTS #12).

Design: sample face x-centers at ~2fps inside each keep-segment, EMA-smooth,
and emit either a static crop (delta < threshold — the common talking-head
case) or a piecewise ffmpeg crop expression. No face -> center crop.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger("clipai.reframe")

YUNET_ONNX = Path(__file__).resolve().parent / "assets" / "models" / \
    "face_detection_yunet_2023mar.onnx"
SAMPLE_EVERY_S = 0.5
EMA_ALPHA = 0.35            # smoothing inside a segment
STATIC_DELTA_PCT = 0.12     # of src width: below -> static crop
JUMP_DELTA_PCT = 0.25       # smartcut guardrail: face moved more than this
                            # across a proposed cut -> keep the filler

_det = None


def _detector(w: int, h: int):
    global _det
    if _det is None:
        if not YUNET_ONNX.exists():
            logger.warning("YuNet model missing (%s) — center-crop fallback", YUNET_ONNX)
            _det = "unavailable"
        else:
            _det = cv2.FaceDetectorYN_create(str(YUNET_ONNX), "", (320, 320), 0.6)
    if _det == "unavailable":
        return None
    _det.setInputSize((w, h))
    return _det


def probe_size(video_path: Path) -> Tuple[int, int]:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json",
         str(video_path)], capture_output=True, text=True, check=True)
    import json
    st = json.loads(p.stdout)["streams"][0]
    return int(st["width"]), int(st["height"])


def face_centers(video_path: Path, start: float, end: float,
                 every: float = SAMPLE_EVERY_S) -> List[Tuple[float, float]]:
    """Sample (t, face_x_center 0..1). Empty -> caller falls back to 0.5."""
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    det = _detector(w, h)
    out = []
    if det is not None:
        t = start
        while t < end:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
            ok, frame = cap.read()
            if ok:
                _, faces = det.detect(frame)
                if faces is not None and len(faces):
                    # largest face
                    f = max(faces, key=lambda r: r[2] * r[3])
                    out.append((t, float((f[0] + f[2] / 2) / w)))
            t += every
    cap.release()
    return out


def smooth(track: List[Tuple[float, float]], alpha: float = EMA_ALPHA,
           default: float = 0.5) -> List[Tuple[float, float]]:
    """EMA over sampled centers; gaps >2s reset the filter (per-segment reset
    is the caller's job — this function handles detector dropouts)."""
    if not track:
        return []
    out = []
    prev_t, prev_x = track[0]
    for t, x in track:
        if t - prev_t > 2.0:
            prev_x = x                      # detector dropout -> re-init
        else:
            prev_x = alpha * x + (1 - alpha) * prev_x
        out.append((t, prev_x))
        prev_t = t
    return out


def crop_geometry(src_w: int, src_h: int,
                  aspect: float = 9 / 16) -> Tuple[int, int, int]:
    """(crop_w, crop_h, crop_y) for a 9:16 window inside src."""
    if src_w / src_h > aspect:
        cw, ch, cy = int(src_h * aspect), src_h, 0
    else:
        cw, ch, cy = src_w, int(src_w / aspect), (src_h - int(src_w / aspect)) // 2
    return cw, ch, cy


def crop_plan(video_path: Path, start: float, end: float,
              keep_segments: Optional[List[Tuple[float, float]]] = None
              ) -> dict:
    """Per-clip crop plan: static crop_x or a piecewise expression over the
    keep-segments. Hard-reset: each segment's trajectory is smoothed
    independently, so a cut never interpolates across the discontinuity."""
    src_w, src_h = probe_size(video_path)
    cw, ch, cy = crop_geometry(src_w, src_h)
    max_x = src_w - cw

    segs = keep_segments or [(start, end)]
    plans = []
    for s, e in segs:
        tr = smooth(face_centers(video_path, s, e))
        if not tr:
            plans.append({"start": s, "end": e, "mode": "static",
                          "x": int(max_x // 2)})
            continue
        xs = [x for _, x in tr]
        if max(xs) - min(xs) < STATIC_DELTA_PCT:
            cx = int(np.clip(np.mean(xs) * src_w - cw / 2, 0, max_x))
            plans.append({"start": s, "end": e, "mode": "static", "x": cx})
        else:
            # piecewise: one step per sample, x already smoothed
            steps = [{"t": t, "x": int(np.clip(x * src_w - cw / 2, 0, max_x))}
                     for t, x in tr]
            plans.append({"start": s, "end": e, "mode": "track", "steps": steps})
    return {"src_w": src_w, "src_h": src_h, "crop_w": cw, "crop_h": ch,
            "crop_y": cy, "segments": plans}


def face_jump_between(video_path: Path, t_before: float, t_after: float) -> float:
    """|x_after - x_before| — smartcut guardrail input (JUMP_DELTA_PCT)."""
    a = face_centers(video_path, max(0, t_before - 0.4), t_before, every=0.2)
    b = face_centers(video_path, t_after, t_after + 0.4, every=0.2)
    if not a or not b:
        return 0.0
    return abs(b[-1][1] - a[-1][1])


def x_expression(plan_seg: dict, clip_start: float) -> str:
    """ffmpeg crop x= expression for one segment plan (piecewise steps)."""
    if plan_seg["mode"] == "static":
        return str(plan_seg["x"])
    steps = plan_seg["steps"]
    expr = str(steps[-1]["x"])
    for st in reversed(steps[:-1]):
        expr = f"if(lt(t\\,{st['t'] - clip_start:.3f})\\,{st['x']}\\,{expr})"
    return expr
