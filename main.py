import os
import sys
import subprocess
import json
import math
import re
import argparse
import logging
from pathlib import Path
from typing import List, Dict, Optional

import whisperx
import cv2
import numpy as np

logger = logging.getLogger("clips-ai-tool")

SCRIPT_DIR = Path(__file__).parent.resolve()
INPUT_DIR = SCRIPT_DIR / "input"
OUTPUT_DIR = SCRIPT_DIR / "output"

# WhisperX device — force CPU since no GPU is available
DEVICE = "cpu"
COMPUTE_TYPE = "int8"

# Viral hook words / phrases (lower-case)
HOOK_WORDS = {
    # Curiosity gaps
    "what if", "secret", "nobody", "never guess", "you won't believe",
    "hidden", "revealed", "truth about", "the real reason", "nobody tells you",
    # Emotion
    "shocking", "incredible", "unbelievable", "amazing", "insane",
    "heartbreaking", "inspiring", "motivational", "powerful",
    # Urgency / CTA
    "wait for it", "watch until", "comment", "share", "don't skip",
    "last chance", "before it's too late",
    # Contrast / surprise
    "but then", "suddenly", "plot twist", "unexpected", "turns out",
}

# Simple sentiment word lists for lightweight sentiment scoring
POSITIVE_WORDS = {
    "good", "great", "amazing", "love", "best", "awesome", "beautiful",
    "happy", "perfect", "incredible", "fantastic", "wonderful", "brilliant",
    "excellent", "win", "success", "proud", "exciting", "joy", "hope",
}
NEGATIVE_WORDS = {
    "bad", "terrible", "worst", "hate", "awful", "sad", "horrible",
    "fail", "failure", "wrong", "broken", "angry", "fear", "pain",
    "loss", "dead", "kill", "fight", "danger", "crisis", "problem",
}

# Configurable keyword boost list (empty by default, loaded from config)
KEYWORD_BOOST_LIST: set = set()

# ASS style constants — modern social-media look
ASS_HEADER = """[Script Info]
Title: Auto Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,64,&H00FFFF,&H000000,&H000000,&H000000,1,0,0,0,100,100,0,0,1,4,0,8,20,20,120,0

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

VIDEO_EXTENSIONS = ("*.mp4", "*.mov", "*.avi", "*.mkv", "*.webm", "*.ts")

FACE_DETECTOR = None


def _load_face_detector():
    global FACE_DETECTOR
    if FACE_DETECTOR is None:
        try:
            proto = cv2.data.haarcascades + "deploy.prototxt"
            weights = cv2.data.haarcascades + "res10_300x300_ssd_iter_140000.caffemodel"
            FACE_DETECTOR = cv2.dnn.readNetFromCaffe(proto, weights)
        except (AttributeError, cv2.error):
            FACE_DETECTOR = "unavailable"
    return None if FACE_DETECTOR == "unavailable" else FACE_DETECTOR


def load_config(config_path: Optional[Path] = None) -> dict:
    """Load configuration from JSON file. Returns empty dict if not found."""
    if config_path is None:
        config_path = SCRIPT_DIR / "config.json"
    if not config_path.exists():
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_input_videos(batch: bool = False) -> List[Path]:
    """Find video files in the input directory. If batch, return all; else return first."""
    files = []
    for ext in VIDEO_EXTENSIONS:
        files.extend(INPUT_DIR.glob(ext))
    if not files:
        logger.error("No video file found in %s", INPUT_DIR.resolve())
        logger.error("Please place your video file in the input/ folder.")
        raise FileNotFoundError(f"No video files in {INPUT_DIR}")
    if batch:
        return sorted(files)
    return [files[0]]


def extract_audio(video_path: Path) -> Path:
    """Extract audio as MP3 for transcription."""
    audio_path = video_path.with_suffix(".mp3")
    if audio_path.exists():
        logger.info("Audio already extracted: %s", audio_path.name)
        return audio_path
    logger.info("Extracting audio with ffmpeg...")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path.resolve()),
        "-vn", "-ar", "16000", "-ac", "1",
        "-b:a", "32k",
        str(audio_path.resolve()),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logger.info("Audio extracted.")
    return audio_path


def transcribe(audio_path: Path, model_name: str = "medium", language: Optional[str] = None):
    """Transcribe audio using local WhisperX."""
    logger.info("Transcribing with WhisperX (%s model)...", model_name)
    model = whisperx.load_model(model_name, device=DEVICE, compute_type=COMPUTE_TYPE)
    audio = whisperx.load_audio(str(audio_path.resolve()))

    if language:
        result = model.transcribe(audio, language=language)
        logger.info("Forced language: %s", language)
    else:
        result = model.transcribe(audio)
        logger.info("Detected language: %s", result.get("language", "unknown"))

    # Try word alignment; fallback to segment-level timestamps if unsupported
    try:
        model_a, metadata = whisperx.load_align_model(
            language_code=result["language"], device=DEVICE
        )
        result = whisperx.align(result["segments"], model_a, metadata, audio, DEVICE)
        logger.info("Word-level alignment applied.")
    except (ValueError, Exception) as e:
        logger.info("No alignment model for this language, using segment timestamps. (%s)", e)

    logger.info("Transcription complete.")
    return result


def correct_segments_with_gpt4o(
    segments,
    gpt_model: str = "gpt-4o-mini",
    batch_size: int = 4,
    base_url: str = None,
    api_key_env: str = "OpenAI_APIKey4",
):
    """Post-correct transcript segments with GPT-4o-mini.

    Provider fallback chain:
      1. OpenAI (iterate OpenAI_API_KEY..OpenAI_API_KEY5, or use api_key_env if
         explicitly provided) — uses gpt_model.
      2. Groq (GROQ_API_KEY) — uses gpt_model via OpenAI-compatible endpoint.
      3. Gemini (GEMINI_API_KEY) — uses gpt_model via OpenAI-compatible endpoint.
      4. If no provider is available, return segments uncorrected.
    """
    from dotenv import load_dotenv
    load_dotenv()

    from openai import OpenAI

    # Build the list of OpenAI client candidates to try in order.
    # Each candidate is (provider_name, client, model_name).
    candidates = []

    openai_keys = []
    if api_key_env and api_key_env != "OpenAI_APIKey4":
        # Explicit env var requested — use only that one.
        val = os.getenv(api_key_env)
        if val:
            openai_keys = [val]
    else:
        # Default: try OpenAI_API_KEY through OpenAI_API_KEY5.
        for name in (
            "OpenAI_API_KEY",
            "OpenAI_API_KEY2",
            "OpenAI_API_KEY3",
            "OpenAI_API_KEY4",
            "OpenAI_API_KEY5",
        ):
            val = os.getenv(name)
            if val:
                openai_keys.append(val)

    for key in openai_keys:
        client_kwargs = {"api_key": key}
        if base_url:
            client_kwargs["base_url"] = base_url
        candidates.append(("OpenAI", OpenAI(**client_kwargs), gpt_model))

    # Groq fallback
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        groq_base = base_url or "https://api.groq.com/openai/v1"
        candidates.append(("Groq", OpenAI(api_key=groq_key, base_url=groq_base), gpt_model))

    # Gemini fallback
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        gemini_base = base_url or "https://generativelanguage.googleapis.com/v1beta/openai/"
        candidates.append(("Gemini", OpenAI(api_key=gemini_key, base_url=gemini_base), gpt_model))

    if not candidates:
        logger.warning("No LLM provider API key found. Skipping GPT correction.")
        return segments

    logger.info("Correcting transcript with %s (providers available: %s)...",
                gpt_model, ", ".join(name for name, _, _ in candidates))
    corrected = []
    total_batches = (len(segments) + batch_size - 1) // batch_size

    # Try providers in order; on quota/auth errors, fall back to the next.
    active_idx = 0
    provider_name, client, model_name = candidates[active_idx]
    logger.info("Using provider: %s", provider_name)

    for i in range(0, len(segments), batch_size):
        batch = segments[i:i + batch_size]
        batch_num = i // batch_size + 1
        logger.info("Correcting batch %d/%d...", batch_num, total_batches)

        lines = []
        for idx, seg in enumerate(batch):
            lines.append(f"[{idx}] {seg.get('text', '').strip()}")
        prompt_text = "\n".join(lines)

        # Retry the API call across providers on failure.
        success = False
        while True:
            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a language expert. Fix spelling, grammar, and "
                                "reconstruct these transcript segments into natural, realistic sentences. "
                                "Preserve the original meaning and approximate length. "
                                "Return ONLY the corrected text, one segment per line, prefixed with [index]. "
                                "Do NOT add explanations, notes, or extra formatting."
                            ),
                        },
                        {"role": "user", "content": prompt_text},
                    ],
                    temperature=0.3,
                    max_tokens=1000,
                )
                reply = response.choices[0].message.content.strip()
                for seg in batch:
                    seg_idx = batch.index(seg)
                    pattern = rf"\[{seg_idx}\]\s*(.+)"
                    match = re.search(pattern, reply, re.MULTILINE)
                    if match:
                        corrected_text = match.group(1).strip()
                        if corrected_text:
                            seg["text"] = corrected_text
                corrected.extend(batch)
                success = True
                break
            except Exception as e:
                logger.warning("API error in batch %d via %s: %s", batch_num, provider_name, e)
                # Try to fall back to the next provider.
                if active_idx + 1 < len(candidates):
                    active_idx += 1
                    provider_name, client, model_name = candidates[active_idx]
                    logger.warning("Falling back to provider: %s", provider_name)
                    continue
                # No more providers — give up on this batch, keep originals.
                logger.warning("All providers exhausted for batch %d; keeping original text.", batch_num)
                corrected.extend(batch)
                success = True  # break out of retry loop
                break

        if not success:
            # Should not reach here, but defensively keep originals.
            corrected.extend(batch)

    logger.info("GPT correction complete.")
    return corrected


def _score_hook_words(text: str) -> float:
    """Score text for viral hook words. Returns 1.0-3.0 multiplier."""
    text_lower = text.lower()
    matches = sum(1 for phrase in HOOK_WORDS if phrase in text_lower)
    if matches == 0:
        return 1.0
    return 1.0 + min(matches * 0.5, 2.0)


def _sentence_boundary_bonus(words: List[Dict], start: float, end: float) -> float:
    """Bonus if clip starts/ends on sentence boundaries."""
    window_words = [w for w in words if w["start"] >= start and w["end"] <= end]
    if not window_words:
        return 0.5
    first = window_words[0].get("word", "").strip()
    last = window_words[-1].get("word", "").strip()
    bonus = 1.0
    if first and first[0].isupper():
        bonus += 0.3
    if last and last[-1] in "!.?":
        bonus += 0.5
    return bonus


def _sentiment_score(text: str) -> float:
    """Lightweight sentiment analysis. Returns 0.8-1.2 multiplier based on emotional content."""
    text_lower = text.lower()
    words_set = set(text_lower.split())
    pos = len(words_set & POSITIVE_WORDS)
    neg = len(words_set & NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 1.0
    return min(1.0 + total * 0.1, 1.2)


def _keyword_boost(text: str) -> float:
    """Boost score if text contains configured keywords. Returns 1.0-1.5 multiplier."""
    if not KEYWORD_BOOST_LIST:
        return 1.0
    text_lower = text.lower()
    matches = sum(1 for kw in KEYWORD_BOOST_LIST if kw.lower() in text_lower)
    if matches == 0:
        return 1.0
    return min(1.0 + matches * 0.25, 1.5)


def detect_scene_cuts(video_path: Path) -> List[float]:
    """Detect scene cut timestamps using ffmpeg scene detection."""
    logger.info("Detecting scene cuts...")
    cmd = [
        "ffmpeg", "-i", str(video_path.resolve()),
        "-vf", "select='gt(scene,0.3)',showinfo",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    cuts = []
    for line in result.stderr.splitlines():
        match = re.search(r"pts_time:([\d.]+)", line)
        if match:
            cuts.append(float(match.group(1)))
    logger.info("Found %d scene cut(s).", len(cuts))
    return cuts


def _scene_cut_density(scene_cuts: List[float], start: float, end: float) -> float:
    """Count scene cuts within clip range. Returns 0.8-1.3 multiplier (more cuts = more dynamic)."""
    cuts_in_range = sum(1 for c in scene_cuts if start <= c <= end)
    if cuts_in_range == 0:
        return 0.8
    return min(0.8 + cuts_in_range * 0.15, 1.3)


def analyze_motion(video_path: Path, start: float, end: float) -> float:
    """Sample frames at start/mid/end of clip and compute mean frame difference."""
    cap = cv2.VideoCapture(str(video_path.resolve()))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        cap.release()
        return 0.0
    timestamps = [start + 1.0, (start + end) / 2, end - 1.0]
    frames = []
    for t in timestamps:
        frame_pos = int(t * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
        ret, frame = cap.read()
        if ret:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frames.append(gray)
    cap.release()
    if len(frames) < 2:
        return 0.0
    diffs = []
    for i in range(len(frames) - 1):
        diff = cv2.absdiff(frames[i], frames[i + 1])
        diffs.append(np.mean(diff))
    return float(np.mean(diffs)) if diffs else 0.0


def detect_face_center(video_path: Path, timestamp: float) -> float:
    """Return x-center of largest face at given timestamp (0-1 normalized). Returns 0.5 if no face."""
    cap = cv2.VideoCapture(str(video_path.resolve()))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        cap.release()
        return 0.5
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(timestamp * fps))
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return 0.5

    h, w = frame.shape[:2]
    net = _load_face_detector()
    if net is None:
        return 0.5
    blob = cv2.dnn.blobFromImage(frame, 1.0, (300, 300), (104.0, 177.0, 123.0))
    net.setInput(blob)
    detections = net.forward()

    best_conf = 0.0
    best_center = 0.5
    for i in range(detections.shape[2]):
        conf = detections[0, 0, i, 2]
        if conf > 0.5 and conf > best_conf:
            best_conf = conf
            x1 = int(detections[0, 0, i, 3] * w)
            x2 = int(detections[0, 0, i, 4] * w)
            best_center = ((x1 + x2) / 2) / w
    return best_center


def find_clips(result, num_clips=5, min_duration=15.0, max_duration=60.0, scene_cuts=None):
    logger.info("Finding best clips...")

    words = []
    has_word_timestamps = False
    for seg in result.get("segments", []):
        word_list = seg.get("words", [])
        if word_list:
            has_word_timestamps = True
            for w in word_list:
                if "start" in w and "end" in w:
                    words.append(w)
        else:
            if "start" in seg and "end" in seg:
                words.append({
                    "start": seg["start"],
                    "end": seg["end"],
                    "word": seg.get("text", ""),
                })

    if not words:
        logger.error("No timestamps found in transcription.")
        raise ValueError("No timestamps found in transcription result.")

    candidates = []
    step = 3.0
    window = min_duration
    total = words[-1]["end"] if words else 0

    while window <= max_duration:
        start = words[0]["start"]
        while start + window <= total:
            end = start + window
            seg_words = [w for w in words if w["start"] >= start and w["end"] <= end]
            if not seg_words:
                start += step
                continue

            duration = end - start
            text = " ".join(w.get("word", "") for w in seg_words).strip()
            actual_word_count = len(text.split()) if text else 0
            density = actual_word_count / duration if duration > 0 else 0

            completeness = 1.0 if text and text[-1] in "!.?" else 0.5
            boundary_bonus = _sentence_boundary_bonus(words, start, end)
            hook_multiplier = _score_hook_words(text)
            sentiment_mult = _sentiment_score(text)
            keyword_mult = _keyword_boost(text)
            scene_density_mult = _scene_cut_density(scene_cuts or [], start, end)

            min_density = 0.3 if has_word_timestamps else 0.05
            if density < min_density:
                start += step
                continue

            score = (
                density
                * completeness
                * boundary_bonus
                * hook_multiplier
                * sentiment_mult
                * keyword_mult
                * scene_density_mult
                * math.log1p(actual_word_count)
            )
            candidates.append({
                "start": start,
                "end": end,
                "text": text,
                "score": score,
                "word_count": actual_word_count,
            })
            start += step
        window += 5.0

    candidates.sort(key=lambda x: x["score"], reverse=True)

    clips = []
    for cand in candidates:
        if len(clips) >= num_clips:
            break
        overlap = False
        for existing in clips:
            if not (cand["end"] <= existing["start"] or cand["start"] >= existing["end"]):
                overlap = True
                break
        if not overlap:
            clips.append(cand)

    clips.sort(key=lambda x: x["start"])
    logger.info("Found %d clip(s).", len(clips))
    if not clips:
        logger.warning("No clips were found. Try a different video.")
        return []
    return clips


def _sec_to_ass(t: float) -> str:
    """Convert seconds to ASS time format H:MM:SS.cc"""
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _escape_ass(text: str) -> str:
    """Escape characters for ASS dialogue text."""
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "\\{")
    text = text.replace("}", "\\}")
    return text


def build_ass_captions(result, clip_start: float = 0.0, clip_end: Optional[float] = None) -> str:
    """Build ASS dialogue lines from WhisperX result, optionally filtered to clip range."""
    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            if "start" in w and "end" in w:
                if clip_end is None or (w["start"] >= clip_start and w["end"] <= clip_end):
                    words.append(w)
        if not seg.get("words") and "start" in seg and "end" in seg:
            if clip_end is None or (seg["start"] >= clip_start and seg["end"] <= clip_end):
                words.append({
                    "start": seg["start"],
                    "end": seg["end"],
                    "word": seg.get("text", ""),
                })

    if not words:
        return ASS_HEADER

    # Group into lines (max 6 words or ~35 chars)
    lines = []
    current = []
    current_len = 0
    for w in words:
        txt = w.get("word", "").strip()
        if not txt:
            continue
        if current and (current_len + len(txt) + 1 > 35 or len(current) >= 6):
            lines.append({
                "start": current[0]["start"],
                "end": current[-1]["end"],
                "text": " ".join(x["text"] for x in current),
            })
            current = [{"start": w["start"], "end": w["end"], "text": txt}]
            current_len = len(txt)
        else:
            current.append({"start": w["start"], "end": w["end"], "text": txt})
            current_len += len(txt) + 1
    if current:
        lines.append({
            "start": current[0]["start"],
            "end": current[-1]["end"],
            "text": " ".join(x["text"] for x in current),
        })

    # Build ASS dialogue entries with offset for clip start
    offset = clip_start
    ass_lines = []
    for line in lines:
        start = _sec_to_ass(line["start"] - offset)
        end = _sec_to_ass(line["end"] - offset)
        text = _escape_ass(line["text"])
        ass_lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    return ASS_HEADER + "\n".join(ass_lines) + "\n"


def resize_and_save(video_path: Path, clips: List[Dict], result, output_dir: Optional[Path] = None):
    """Crop to 9:16, burn ASS captions, and save clips with metadata."""
    if output_dir is None:
        output_dir = OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Analyzing visuals & resizing to 9:16...")

    # Probe video dimensions
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        str(video_path.resolve()),
    ]
    probe = subprocess.run(probe_cmd, capture_output=True, text=True)
    info = json.loads(probe.stdout)
    width = int(info["streams"][0]["width"])
    height = int(info["streams"][0]["height"])

    target_ratio = 9 / 16
    current_ratio = width / height

    if current_ratio > target_ratio:
        new_width = int(height * target_ratio)
        new_height = height
        crop_y = 0
    else:
        new_width = width
        new_height = int(width / target_ratio)
        crop_y = (height - new_height) // 2

    scene_cuts = detect_scene_cuts(video_path)

    for idx, clip in enumerate(clips, start=1):
        start_time = clip["start"]
        end_time = clip["end"]
        logger.info("Processing clip %d: %.2fs - %.2fs", idx, start_time, end_time)
        logger.info("  %s", clip['text'][:80])

        # Visual analysis
        motion = analyze_motion(video_path, start_time, end_time)
        has_scene_cut = any(start_time <= c <= end_time for c in scene_cuts)
        logger.info("  Motion: %.1f | Scene cut: %s", motion, has_scene_cut)

        # Face-aware crop offset
        face_center = detect_face_center(video_path, (start_time + end_time) / 2)
        if current_ratio > target_ratio:
            max_crop_x = width - new_width
            crop_x = int(max(0, min(max_crop_x, face_center * width - new_width / 2)))
        else:
            crop_x = 0

        # Build ASS captions for this clip
        ass_text = build_ass_captions(result, clip_start=start_time, clip_end=end_time)
        ass_path = output_dir / f"short_{idx:02d}.ass"
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_text)

        output_path = output_dir / f"short_{idx:02d}.mp4"
        vf = f"crop={new_width}:{new_height}:{crop_x}:{crop_y},scale=1080:1920"

        # Two-pass: first crop/scale, then burn ASS
        temp_path = output_dir / f"short_{idx:02d}_temp.mp4"
        cmd1 = [
            "ffmpeg", "-y",
            "-ss", str(start_time),
            "-to", str(end_time),
            "-i", str(video_path.resolve()),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            str(temp_path.resolve()),
        ]
        subprocess.run(cmd1, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Burn ASS captions
        cmd2 = [
            "ffmpeg", "-y",
            "-i", str(temp_path.resolve()),
            "-vf", f"ass={ass_path.name}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            str(output_path.resolve()),
        ]
        subprocess.run(cmd2, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(output_dir))

        # Clean up temp file
        temp_path.unlink(missing_ok=True)
        logger.info("  Saved: %s", output_path.name)

        # Save metadata
        meta = {
            "index": idx,
            "start": start_time,
            "end": end_time,
            "duration": end_time - start_time,
            "text": clip["text"],
            "score": clip["score"],
            "word_count": clip["word_count"],
            "motion_score": round(motion, 2),
            "has_scene_cut": has_scene_cut,
            "crop": {"x": crop_x, "y": crop_y, "width": new_width, "height": new_height},
        }
        meta_path = output_dir / f"short_{idx:02d}.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

    logger.info("Done! All shorts saved to %s", output_dir)


def process_video(video_path: Path, args, config: dict) -> bool:
    """Process a single video through the full pipeline."""
    logger.info("=" * 60)
    logger.info("Processing: %s", video_path.name)
    logger.info("=" * 60)

    # Per-video output directory for batch mode
    if args.batch:
        video_output = OUTPUT_DIR / video_path.stem
    else:
        video_output = OUTPUT_DIR
    video_output.mkdir(parents=True, exist_ok=True)

    try:
        audio_path = extract_audio(video_path)
        result = transcribe(
            audio_path,
            model_name=args.model,
            language=args.language
        )

        if args.gpt_correct:
            result["segments"] = correct_segments_with_gpt4o(
                result["segments"],
                gpt_model=args.gpt_model
            )

        # Pre-compute scene cuts for clip scoring
        scene_cuts = detect_scene_cuts(video_path)

        clips = find_clips(
            result,
            num_clips=args.num_clips,
            min_duration=args.min_duration,
            max_duration=args.max_duration,
            scene_cuts=scene_cuts
        )

        if not clips:
            logger.warning("No clips found for %s, skipping.", video_path.name)
            return False

        resize_and_save(video_path, clips, result, output_dir=video_output)
        return True

    except Exception as e:
        logger.error("Failed to process %s: %s", video_path.name, e)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Extract viral short clips from long videos with AI-powered transcription and captions."
    )
    parser.add_argument("input", nargs="?", default=None,
                        help="Path to video file (if omitted, uses input/ folder)")
    parser.add_argument("--batch", action="store_true",
                        help="Process all videos in input/ directory")
    parser.add_argument("--language", default=None,
                        help="Language code for WhisperX (e.g. sr, en). Auto-detect if omitted.")
    parser.add_argument("--gpt-correct", action="store_true",
                        help="Enable GPT-4o-mini transcript correction")
    parser.add_argument("--gpt-model", default="gpt-4o-mini",
                        help="GPT model for transcript correction")
    parser.add_argument("--num-clips", type=int, default=5,
                        help="Number of clips to extract (default: 5)")
    parser.add_argument("--min-duration", type=float, default=15.0,
                        help="Minimum clip duration in seconds (default: 15)")
    parser.add_argument("--max-duration", type=float, default=60.0,
                        help="Maximum clip duration in seconds (default: 60)")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Output directory (default: output/)")
    parser.add_argument("--model", type=str, default="medium",
                        help="WhisperX model size (default: medium)")
    parser.add_argument("--config", type=str, default=None,
                        help="Path to config.json file")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    # Load config
    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    # Apply config defaults (CLI args take priority)
    if args.language is None and "language" in config:
        args.language = config["language"]
    if not args.gpt_correct and config.get("gpt_correct", False):
        args.gpt_correct = True
    if args.model == "medium" and "model" in config:
        args.model = config["model"]
    if args.num_clips == 5 and "num_clips" in config:
        args.num_clips = config["num_clips"]
    if args.min_duration == 15.0 and "min_duration" in config:
        args.min_duration = config["min_duration"]
    if args.max_duration == 60.0 and "max_duration" in config:
        args.max_duration = config["max_duration"]

    # Load keyword boost list from config
    global KEYWORD_BOOST_LIST
    KEYWORD_BOOST_LIST = set(config.get("keyword_boost", []))

    # Override output dir if specified
    global OUTPUT_DIR
    if args.output_dir:
        OUTPUT_DIR = Path(args.output_dir)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Disable symlink warnings for HuggingFace on Windows
    os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

    # Determine input videos
    if args.input:
        video_paths = [Path(args.input)]
        if not video_paths[0].exists():
            logger.error("File not found: %s", args.input)
            sys.exit(1)
    else:
        try:
            video_paths = find_input_videos(batch=args.batch)
        except FileNotFoundError:
            sys.exit(1)

    logger.info("Processing %d video(s)...", len(video_paths))

    success_count = 0
    for vp in video_paths:
        ok = process_video(vp, args, config)
        if ok:
            success_count += 1

    logger.info("Completed: %d/%d videos processed successfully.", success_count, len(video_paths))


if __name__ == "__main__":
    main()
