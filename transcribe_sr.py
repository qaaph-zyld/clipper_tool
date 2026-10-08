#!/usr/bin/env python3
"""Serbian transcription using fine-tuned Whisper large-v3 via faster-whisper.

Usage:
    python transcribe_sr.py <audio_file> [--output <path>] [--model-dir <path>] [--language <code>] [--beam-size <n>]
"""
import argparse
import json
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("transcribe_sr")

DEFAULT_MODEL_DIR = str(Path(__file__).parent / "models" / "sr-v3-ct2")

_SECTION_HEADER_RE = re.compile(r"^\[.+\]$")


def parse_hotwords_file(path: Path, topic: str = None) -> str:
    """Parse a hotwords file, stripping comments and section headers.

    File format:
        # comments
        [boxing]
        word1 word2 word3

        [farming]
        word4 word5

        [general]
        word6 word7

    Lines starting with `#` are comments and skipped. Blank lines are skipped.
    Section headers (`[name]`) delimit groups; the header lines themselves are
    never included in the output.

    Args:
        path: Path to the hotwords file (utf-8).
        topic: Optional section name (without brackets). When provided, only
            words under that section are returned. When None, words from all
            sections are combined (headers ignored).

    Returns:
        A single space-separated string of hotwords (no headers, no comments).
        Empty string if no words matched (e.g. unknown topic).
    """
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                continue
            if _SECTION_HEADER_RE.match(line):
                current_section = line[1:-1].strip()
                sections.setdefault(current_section, [])
                continue
            if current_section is None:
                # Lines before any section header: treat as a default/unnamed section.
                current_section = ""
                sections.setdefault(current_section, [])
            sections[current_section].append(line)

    if topic is not None:
        words = sections.get(topic.strip(), [])
    else:
        words = []
        for section_words in sections.values():
            words.extend(section_words)

    return " ".join(words)


def transcribe(
    audio_path: str,
    model_dir: str,
    language: str = "sr",
    beam_size: int = 5,
    hotwords: str = None,
    initial_prompt: str = None,
):
    from faster_whisper import WhisperModel

    logger.info("Loading model from %s (cpu, int8)...", model_dir)
    model = WhisperModel(model_dir, device="cpu", compute_type="int8")

    logger.info("Transcribing %s (language=%s, beam_size=%d)...", audio_path, language, beam_size)
    if hotwords:
        logger.info("Using hotwords: %s", hotwords)
    if initial_prompt:
        logger.info("Using initial_prompt: %s", initial_prompt)
    segments, info = model.transcribe(
        audio_path,
        language=language,
        beam_size=beam_size,
        word_timestamps=True,
        vad_filter=True,
        hotwords=hotwords,
        initial_prompt=initial_prompt,
    )

    detected_lang = info.language
    lang_prob = info.language_probability
    logger.info("Detected language: %s (%.2f%% confidence)", detected_lang, lang_prob * 100)

    results = []
    total_text = []
    for seg in segments:
        seg_dict = {
            "id": seg.id,
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
            "words": [],
        }
        if seg.words:
            for w in seg.words:
                seg_dict["words"].append({
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                    "word": w.word.strip(),
                    "probability": round(w.probability, 4),
                })
        results.append(seg_dict)
        total_text.append(seg.text.strip())
        logger.info("[%.1fs -> %.1fs] %s", seg.start, seg.end, seg.text.strip())

    return {
        "language": detected_lang,
        "language_probability": round(lang_prob, 4),
        "segments": results,
        "full_text": " ".join(total_text),
    }


def main():
    parser = argparse.ArgumentParser(description="Serbian transcription with fine-tuned Whisper large-v3")
    parser.add_argument("audio", help="Path to audio file")
    parser.add_argument("--output", "-o", default=None, help="Output JSON path (default: same dir as audio)")
    parser.add_argument("--model-dir", "-m", default=DEFAULT_MODEL_DIR, help="CTranslate2 model directory")
    parser.add_argument("--language", "-l", default="sr", help="Language code (default: sr)")
    parser.add_argument("--beam-size", "-b", type=int, default=5, help="Beam size (default: 5)")
    parser.add_argument(
        "--hotwords",
        default=None,
        help="Inline hotwords string (space-separated) passed to faster-whisper",
    )
    parser.add_argument(
        "--hotwords-file",
        default=None,
        help="Path to a file with hotwords (takes precedence over --hotwords)",
    )
    parser.add_argument(
        "--hotwords-topic",
        default=None,
        help="Optional section name in --hotwords-file to select words from (e.g. 'boxing'). "
        "When omitted, words from all sections are combined.",
    )
    parser.add_argument(
        "--initial-prompt",
        default="Ово је српски подкаст.",
        help="Initial prompt for the model (default: Serbian podcast prompt)",
    )
    args = parser.parse_args()

    audio_path = str(Path(args.audio).resolve())
    if not Path(audio_path).exists():
        logger.error("Audio file not found: %s", audio_path)
        sys.exit(1)

    model_dir = str(Path(args.model_dir).resolve())
    if not Path(model_dir).exists():
        logger.error("Model directory not found: %s", model_dir)
        logger.error("Run ct2-transformers-converter first to create the model.")
        sys.exit(1)

    # Resolve hotwords: --hotwords-file takes precedence over --hotwords
    hotwords = args.hotwords
    if args.hotwords_file:
        hotwords_path = Path(args.hotwords_file).resolve()
        if not hotwords_path.exists():
            logger.error("Hotwords file not found: %s", hotwords_path)
            sys.exit(1)
        hotwords = parse_hotwords_file(hotwords_path, topic=args.hotwords_topic)
        if args.hotwords_topic and not hotwords:
            logger.error(
                "Hotwords topic '%s' not found in file: %s", args.hotwords_topic, hotwords_path
            )
            sys.exit(1)
        if args.hotwords_topic:
            logger.info(
                "Loaded hotwords from file %s (topic=%s): %s",
                hotwords_path, args.hotwords_topic, hotwords,
            )
        else:
            logger.info("Loaded hotwords from file %s (all sections): %s", hotwords_path, hotwords)

    output_path = args.output or str(Path(audio_path).with_suffix(".transcript.json"))

    result = transcribe(
        audio_path,
        model_dir,
        language=args.language,
        beam_size=args.beam_size,
        hotwords=hotwords,
        initial_prompt=args.initial_prompt,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info("Transcript saved to %s", output_path)
    logger.info("Total segments: %d", len(result["segments"]))


if __name__ == "__main__":
    main()
