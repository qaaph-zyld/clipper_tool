#!/usr/bin/env python3
"""W0 spike: wav2vec2-xls-r-juznevesti-sr via whisperx load_align_model.

Verifies: (a) model loads through the whisperx HF path with model_name override,
(b) its vocab is Latin and covers sr diacritics, (c) whisperx.align() runs on a
real segment + real audio and returns word timestamps.
"""
import json
import sys
import time

MODEL = "classla/wav2vec2-xls-r-juznevesti-sr"
AUDIO = r"D:\Projects\Tools\clips-ai-tool\eval\excerpts\ex0_nenad.wav"
HYP = r"D:\Projects\Tools\clips-ai-tool\eval\hyp\sr-v3-ct2\ex0_nenad.json"


def main():
    t0 = time.time()
    import whisperx
    model_a, meta = whisperx.load_align_model(
        language_code="sr", device="cpu", model_name=MODEL)
    print(f"align model loaded in {time.time()-t0:.0f}s; dict chars: {len(meta['dictionary'])}")

    vocab = sorted(meta["dictionary"].keys())
    latin_diac = [c for c in vocab if c in "šđčćžŠĐČĆŽ"]
    print("diacritic coverage:", latin_diac)
    cyr = [c for c in vocab if "Ѐ" <= c <= "ӿ"]
    print("cyrillic chars in vocab:", len(cyr), cyr[:10])

    segs = json.load(open(HYP, encoding="utf-8"))["segments"]
    import cyrtranslit
    import re
    cyr_re = re.compile(r"[Ѐ-ӿ]")
    for s in segs:
        if cyr_re.search(s["text"]):
            s["text"] = cyrtranslit.to_latin(s["text"])
        s.pop("words", None)

    audio = whisperx.load_audio(AUDIO)
    t0 = time.time()
    out = whisperx.align(segs[:4], model_a, meta, audio, "cpu",
                       interpolate_method="nearest", return_char_alignments=False)
    dt = time.time() - t0
    n_words = sum(len(s.get("words", [])) for s in out["segments"])
    timed = sum(1 for s in out["segments"] for w in s.get("words", [])
                if w.get("start") is not None)
    print(f"aligned {timed}/{n_words} words in {dt:.1f}s")
    for s in out["segments"][:2]:
        print(" ".join(f"{w['word']}@{w.get('start')}" for w in s.get("words", [])[:8]))


if __name__ == "__main__":
    main()
