"""python -m clipai — CLI entry."""
import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    p = argparse.ArgumentParser(prog="clipai", description="Serbian Clip Studio pipeline")
    p.add_argument("video", nargs="?", help="input video (default: first file in input/)")
    p.add_argument("--lang", default="sr")
    p.add_argument("--engine", default=None, help="ASR engine (default: sr-v3-ct2 for --lang sr)")
    p.add_argument("--hotwords-topic", default=None)
    p.add_argument("--no-align", action="store_true", help="skip wav2vec2 alignment")
    p.add_argument("--out", default=None, help="output dir (default: output/<stem>)")
    args = p.parse_args()

    from .transcribe import run

    video = Path(args.video) if args.video else next(
        (Path(__file__).resolve().parent.parent / "input").glob("*.*"))
    out = Path(args.out) if args.out else (
        Path(__file__).resolve().parent.parent / "output" / video.stem)
    t = run(video, out, engine=args.engine, language=args.lang,
            hotwords_topic=args.hotwords_topic, do_align=not args.no_align)
    print(f"transcript: {out/'transcript.json'} ({len(t.segments)} segments, "
          f"script={t.script}, align={t.meta.align_method})")


if __name__ == "__main__":
    sys.exit(main())
