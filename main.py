import os
import sys
import subprocess
import json
import math
from pathlib import Path
import whisperx

SCRIPT_DIR = Path(__file__).parent.resolve()
INPUT_DIR = SCRIPT_DIR / "input"
OUTPUT_DIR = SCRIPT_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# WhisperX device — force CPU since no GPU is available
device = "cpu"
compute_type = "int8"


def find_input_video() -> Path:
    """Find the first video file in the input directory."""
    extensions = ("*.mp4", "*.mov", "*.avi", "*.mkv", "*.webm", "*.ts")
    files = []
    for ext in extensions:
        files.extend(INPUT_DIR.glob(ext))
    if not files:
        print(f"ERROR: No video file found in {INPUT_DIR.resolve()}.")
        print("Please place your video file in the input/ folder.")
        sys.exit(1)
    return files[0]


def extract_audio(video_path: Path) -> Path:
    """Extract audio as MP3 for fast upload to Whisper API."""
    audio_path = video_path.with_suffix(".mp3")
    if audio_path.exists():
        return audio_path
    print("[1/4] Extracting audio with ffmpeg...")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path.resolve()),
        "-vn", "-ar", "16000", "-ac", "1",
        "-b:a", "32k",
        str(audio_path.resolve()),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("     Audio extracted.")
    return audio_path


def transcribe(audio_path: Path):
    """Transcribe audio using local WhisperX (base model)."""
    print("[2/4] Transcribing with WhisperX (base model)...")
    model = whisperx.load_model("base", device=device, compute_type=compute_type)
    audio = whisperx.load_audio(str(audio_path.resolve()))
    result = model.transcribe(audio)

    # Try word alignment; fallback to segment-level timestamps if unsupported
    try:
        model_a, metadata = whisperx.load_align_model(
            language_code=result["language"], device=device
        )
        result = whisperx.align(result["segments"], model_a, metadata, audio, device)
    except ValueError:
        print("     No alignment model for this language, using segment timestamps.")

    print("     Transcription complete.")
    return result


def find_clips(result, num_clips=5, min_duration=15.0, max_duration=60.0):
    print("[3/4] Finding best clips...")

    # WhisperX result format: result["segments"] each have "words" list
    words = []
    for seg in result.get("segments", []):
        # Word-level timestamps available after alignment
        word_list = seg.get("words", [])
        if word_list:
            for w in word_list:
                if "start" in w and "end" in w:
                    words.append(w)
        else:
            # Fallback: treat each segment as one "word" block
            if "start" in seg and "end" in seg:
                words.append({
                    "start": seg["start"],
                    "end": seg["end"],
                    "word": seg.get("text", ""),
                })

    if not words:
        print("No word-level timestamps found.")
        sys.exit(1)

    # Build candidate windows and score them
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
            # Count actual words in text (handles both word-level and segment-level data)
            actual_word_count = len(text.split()) if text else 0
            density = actual_word_count / duration if duration > 0 else 0

            # Prefer segments that end with punctuation (complete thoughts)
            completeness = 1.0 if text and text[-1] in "!.?" else 0.5

            # Avoid very low-density sections (pauses, music, etc.)
            # Segment-level timestamps need lower threshold than word-level
            min_density = 0.3 if any("words" in seg for seg in result.get("segments", [])) else 0.05
            if density < min_density:
                start += step
                continue

            score = density * completeness * math.log1p(actual_word_count)
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
        # Avoid overlapping clips
        overlap = False
        for existing in clips:
            if not (cand["end"] <= existing["start"] or cand["start"] >= existing["end"]):
                overlap = True
                break
        if not overlap:
            clips.append(cand)

    clips.sort(key=lambda x: x["start"])
    print(f"     Found {len(clips)} clip(s).")
    if not clips:
        print("No clips were found. Try a different video.")
        sys.exit(1)
    return clips


def resize_and_save(video_path: Path, clips):
    print("[4/4] Resizing clips to 9:16...")

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

    # Calculate center crop for 9:16
    target_ratio = 9 / 16
    current_ratio = width / height

    if current_ratio > target_ratio:
        # Video is wider than 9:16 — crop width
        new_width = int(height * target_ratio)
        new_height = height
        crop_x = (width - new_width) // 2
        crop_y = 0
    else:
        # Video is taller than 9:16 — crop height
        new_width = width
        new_height = int(width / target_ratio)
        crop_x = 0
        crop_y = (height - new_height) // 2

    for idx, clip in enumerate(clips, start=1):
        start_time = clip["start"]
        end_time = clip["end"]
        print(f"     Processing clip {idx}: {start_time:.2f}s - {end_time:.2f}s")
        print(f"         {clip['text'][:80]}...")

        output_path = OUTPUT_DIR / f"short_{idx:02d}.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_time),
            "-to", str(end_time),
            "-i", str(video_path.resolve()),
            "-vf", f"crop={new_width}:{new_height}:{crop_x}:{crop_y},scale=1080:1920",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path.resolve()),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"     Saved: {output_path.name}")

    print("     Done! All shorts saved to output/")


def main():
    if len(sys.argv) > 1:
        video_path = Path(sys.argv[1])
        if not video_path.exists():
            print(f"ERROR: File not found: {video_path}")
            sys.exit(1)
    else:
        video_path = find_input_video()

    audio_path = extract_audio(video_path)
    result = transcribe(audio_path)
    clips = find_clips(result)
    resize_and_save(video_path, clips)


if __name__ == "__main__":
    main()
