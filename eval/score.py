#!/usr/bin/env python3
"""W0 scoring: per-excerpt WER per engine, normalized to Latin lowercase.

Usage: python eval/score.py
Reads: eval/ref/<ex>.txt (Latin reference), eval/hyp/<engine>/<ex>.json
Writes: eval/wer_results.json + prints table
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(r"D:\Projects\Tools\clips-ai-tool")
sys.path.insert(0, str(ROOT))

import cyrtranslit  # noqa: E402
import jiwer  # noqa: E402

PUNCT = re.compile(r"[^\w\s'čćđšžČĆĐŠŽ]+", re.UNICODE)
CYR = re.compile(r"[Ѐ-ӿ]")


def to_latin(text: str) -> str:
    return cyrtranslit.to_latin(text) if CYR.search(text) else text


def normalize(text: str) -> str:
    t = to_latin(text).lower()
    t = "".join(c for c in unicodedata.normalize("NFC", t))
    t = PUNCT.sub(" ", t)
    return " ".join(t.split())


def hyp_text(path: Path) -> str:
    d = json.loads(path.read_text(encoding="utf-8"))
    return " ".join(s["text"] for s in d["segments"])


def main():
    refs = {p.stem: normalize(p.read_text(encoding="utf-8")) for p in (ROOT / "eval" / "ref").glob("*.txt")}
    if not refs:
        sys.exit("no references in eval/ref/")
    engines = sorted(p.name for p in (ROOT / "eval" / "hyp").iterdir() if p.is_dir())
    rows = {}
    for eng in engines:
        rows[eng] = {}
        for ex, ref in refs.items():
            hp = ROOT / "eval" / "hyp" / eng / f"{ex}.json"
            if not hp.exists():
                rows[eng][ex] = None
                continue
            h = normalize(hyp_text(hp))
            if not h.strip():
                rows[eng][ex] = {"wer": 1.0, "n_ref_words": len(ref.split()), "empty_hyp": True}
                continue
            m = jiwer.compute_measures(ref, h)
            rows[eng][ex] = {
                "wer": round(m["wer"], 4),
                "mer": round(m["mer"], 4),
                "n_ref_words": len(ref.split()),
            }
    (ROOT / "eval" / "wer_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    exs = sorted(refs)
    print(f"{'engine':14} " + " ".join(f"{e[:12]:>12}" for e in exs) + "   mean")
    for eng, r in rows.items():
        vals = [r[e]["wer"] for e in exs if r.get(e) and "wer" in r[e]]
        mean = sum(vals) / len(vals) if vals else None
        cells = " ".join(f"{r[e]['wer']:12.3f}" if r.get(e) and 'wer' in r[e] else f"{'—':>12}" for e in exs)
        print(f"{eng:14} {cells}   {mean:.3f}" if mean is not None else f"{eng:14} {cells}   —")


if __name__ == "__main__":
    main()
