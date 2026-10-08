"""Word-level alignment with per-segment fallback chain (CONTRACTS #10).

Chain per segment: wav2vec2-sr (whisperx HF path) -> stable-ts DTW ->
faster-whisper word ts -> segment interpolation. Operates on normalized Latin
tokens; timings map back to display words by index.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from .types import Segment, Transcript

logger = logging.getLogger("clipai.align")

WAV2VEC_SR = "classla/wav2vec2-xls-r-juznevesti-sr"
MIN_WORD_DUR, MAX_WORD_DUR = 0.03, 3.0
UNALIGNED_RATIO_ABORT = 0.15


def _align_quality(seg: Segment) -> float:
    """0..1: fraction of words with plausible timestamps."""
    if not seg.words:
        return 0.0
    bad = 0
    for w in seg.words:
        d = w.end - w.start
        if d < MIN_WORD_DUR or d > MAX_WORD_DUR or w.start < seg.start - 0.5 or w.end > seg.end + 0.5:
            bad += 1
    return 1.0 - bad / len(seg.words)


def align_whisperx(t: Transcript, audio_path: str, device: str = "cpu") -> Transcript:
    """Primary: wav2vec2-sr through whisperx. Returns transcript with aligned
    word timings; segments that fall below quality keep their originals and get
    align_quality recorded."""
    import whisperx

    model_a, meta = whisperx.load_align_model(
        language_code="sr", device=device, model_name=WAV2VEC_SR)
    audio = whisperx.load_audio(audio_path)

    for seg in t.segments:
        orig = [(w.start, w.end) for w in seg.words]
        try:
            out = whisperx.align(
                [{"start": seg.start, "end": seg.end, "text": seg.text}],
                model_a, meta, audio, device,
                interpolate_method="nearest", return_char_alignments=False,
            )
            aw = out["segments"][0].get("words", []) if out.get("segments") else []
            if len(aw) == len(seg.words):
                for w, a in zip(seg.words, aw):
                    if a.get("start") is not None and a.get("end") is not None:
                        w.start, w.end = round(a["start"], 3), round(a["end"], 3)
            else:
                # aligner re-split text differently -> index map invalid;
                # mark weak so the fallback chain handles this segment.
                logger.info("seg %d align word mismatch (%d vs %d) -> fallback",
                            seg.id, len(aw), len(seg.words))
                seg.align_quality = 0.0
                continue
            q = _align_quality(seg)
            seg.align_quality = round(q, 3)
            if q < 1 - UNALIGNED_RATIO_ABORT:
                for w, (s, e) in zip(seg.words, orig):
                    w.start, w.end = s, e  # restore ASR timings for fallback
                seg.align_quality = round(q, 3)
                logger.info("seg %d align weak (q=%.2f) -> fallback", seg.id, q)
        except Exception as e:
            logger.warning("seg %d wav2vec2 align failed: %s", seg.id, e)
            seg.align_quality = 0.0
    t.meta.align_method = "wav2vec2-sr"
    return t


def align_stable_ts(t: Transcript, audio_path: str) -> Transcript:
    """Fallback: stable-ts DTW alignment of the segment texts (no extra model)."""
    import stable_whisper
    model = stable_whisper.load_faster_whisper("base", device="cpu")
    text = "\n".join(s.text for s in t.segments)
    res = model.align(audio_path, text, language="sr")
    words = [w for w in res.all_words()]
    flat = [w for s in t.segments for w in s.words]
    if len(words) == len(flat):
        for w, sw in zip(flat, words):
            if sw.start is not None and sw.end is not None:
                w.start, w.end = round(sw.start, 3), round(sw.end, 3)
        for s in t.segments:
            s.align_quality = round(_align_quality(s), 3)
        t.meta.align_method = "stable-ts"
    else:
        logger.warning("stable-ts word count mismatch (%d vs %d); skipped",
                       len(words), len(flat))
    return t


def align(t: Transcript, audio_path: str, device: str = "cpu") -> Transcript:
    """Full chain: try wav2vec2-sr; segments still weak -> stable-ts -> keep
    faster-whisper timings (already present); never crashes the pipeline."""
    try:
        align_whisperx(t, audio_path, device)
    except Exception as e:
        logger.warning("wav2vec2-sr align unavailable: %s", e)
        t.meta.align_method = "fw-word-ts"

    weak = [s for s in t.segments if s.align_quality is not None and s.align_quality < 1 - UNALIGNED_RATIO_ABORT]
    if weak and t.meta.align_method == "wav2vec2-sr":
        try:
            sub = Transcript(lang=t.lang, meta=t.meta, segments=weak)
            align_stable_ts(sub, audio_path)
            for dst, src in zip(weak, sub.segments):
                for w_dst, w_src in zip(dst.words, src.words):
                    w_dst.start, w_dst.end = w_src.start, w_src.end
                dst.align_quality = src.align_quality
        except Exception as e:
            logger.warning("stable-ts fallback failed: %s", e)
    if t.meta.align_method is None:
        t.meta.align_method = "fw-word-ts"
    return t
