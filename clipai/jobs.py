"""Job store + serialized CPU worker.

One worker thread: ASR/align/render all contend for the same 4 cores, so jobs
run strictly sequentially. State lives in jobs/<id>/status.json + transcript
checkpoints; the UI reads files, never shares model objects.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger("clipai.jobs")

ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = ROOT / "output" / "jobs"
INPUT_DIR = ROOT / "input"
CALIBRATION = ROOT / "eval" / "bakeoff_timing.json"

_queue: "queue.Queue[str]" = queue.Queue()
_worker_started = False
_lock = threading.Lock()

STAGES = ["extract_audio", "asr", "normalize", "align", "flags", "scoring", "render"]


def measured_rtf(engine: str = "sr-v3-ct2") -> float:
    """Warm RTF from the W0 bake-off; conservative fallback 5.0 (i7-4770)."""
    try:
        data = json.loads(CALIBRATION.read_text(encoding="utf-8"))
        rts = [f["rtf"] for f in data.get(engine, {}).get("files", {}).values()
               if isinstance(f, dict) and f.get("rtf")]
        if rts:
            return round(sum(rts) / len(rts) * 1.15, 2)  # +15% safety margin
    except Exception:
        pass
    return 5.0


def _status_path(job_id: str) -> Path:
    return JOBS_DIR / job_id / "status.json"


def read_status(job_id: str) -> Optional[dict]:
    p = _status_path(job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_status(job_id: str, **kw) -> dict:
    p = _status_path(job_id)
    st = read_status(job_id) or {}
    st.update(kw)
    st["updated"] = time.time()
    p.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return st


def list_jobs() -> list:
    out = []
    if JOBS_DIR.exists():
        for d in sorted(JOBS_DIR.iterdir(), reverse=True):
            st = read_status(d.name)
            if st:
                st["id"] = d.name
                out.append(st)
    return out


def create_job(video_path: Path, engine: str = "sr-v3-ct2",
               language: str = "sr", hotwords_topic: Optional[str] = None,
               smart_cut: str = "off", num_clips: int = 5) -> str:
    job_id = uuid.uuid4().hex[:10]
    d = JOBS_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    _write_status(
        job_id, state="queued", stage=None, progress=0.0,
        video=str(video_path), engine=engine, language=language,
        hotwords_topic=hotwords_topic, smart_cut=smart_cut,
        num_clips=num_clips, created=time.time(), eta_s=None, error=None)
    _queue.put(job_id)
    _ensure_worker()
    return job_id


def _ensure_worker() -> None:
    global _worker_started
    with _lock:
        if not _worker_started:
            th = threading.Thread(target=_worker, daemon=True, name="clipai-worker")
            th.start()
            _worker_started = True


def _audio_duration_s(wav: Path) -> float:
    try:
        import subprocess, json as _j
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(wav)], capture_output=True, text=True)
        return float(_j.loads(p.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def _worker() -> None:
    while True:
        job_id = _queue.get()
        try:
            _run_job(job_id)
        except Exception as e:
            logger.exception("job %s failed", job_id)
            _write_status(job_id, state="failed", error=str(e))
        finally:
            _queue.task_done()


def _run_job(job_id: str) -> None:
    from .transcribe import run as transcribe_run, extract_audio
    from .types import Transcript
    from .score import find_clips
    from .smartcut import propose_cuts, Strength

    st = read_status(job_id)
    video = Path(st["video"])
    out = JOBS_DIR / job_id
    rtf = measured_rtf(st.get("engine") or "sr-v3-ct2")

    _write_status(job_id, state="running", stage="extract_audio")
    wav = extract_audio(video, out)
    dur = _audio_duration_s(wav)
    eta_asr = dur * rtf
    _write_status(job_id, stage="asr", progress=0.05,
                  eta_s=round(eta_asr),
                  eta_note=f"ASR ~{rtf}x realtime on this CPU — "
                           f"{dur/60:.0f} min audio ≈ {eta_asr/60:.0f} min")

    t0 = time.time()

    def _progress(seg_end: float, total: float) -> None:
        if not total:
            return
        frac = min(seg_end / total, 1.0)
        elapsed = time.time() - t0
        remain = elapsed / max(frac, 1e-3) - elapsed if frac > 0.01 else None
        _write_status(job_id, stage="asr",
                      progress=round(0.05 + frac * 0.75, 3),
                      asr_frac=round(frac, 3),
                      eta_s=round(remain) if remain else round(eta_asr))

    t = transcribe_run(video, out, engine=st.get("engine"),
                       language=st.get("language", "sr"),
                       hotwords_topic=st.get("hotwords_topic"),
                       on_progress=_progress)
    asr_wall = time.time() - t0
    _write_status(job_id, stage="scoring", progress=0.85,
                  measured_rtf=round(asr_wall / max(dur, 1), 2))

    t_path = out / "transcript.json"
    t = Transcript.load(t_path)
    clips = find_clips(t, num_clips=st.get("num_clips", 5))
    cuts = []
    if st.get("smart_cut", "off") != "off":
        cuts = [c.dict() for c in
                propose_cuts(t, wav, Strength(st["smart_cut"]))]
    (out / "clips.json").write_text(
        json.dumps({"clips": clips, "proposed_cuts": cuts}, ensure_ascii=False,
                   indent=1), encoding="utf-8")

    _write_status(job_id, state="transcribed", stage="done", progress=1.0,
                  eta_s=0, n_segments=len(t.segments), n_clips=len(clips),
                  n_flagged=len(t.flagged_words()), n_cut_proposals=len(cuts))
