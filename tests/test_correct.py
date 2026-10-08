"""correct/ flags + tier0 — flagging and suggestion cascade."""
from pathlib import Path

import pytest

from clipai.correct.flags import apply_flags, flag_words
from clipai.correct.tier0 import suggest
from clipai.types import Segment, Transcript, TranscriptMeta, Word

DIC = Path(__file__).resolve().parent.parent / "eval" / "hunspell"


def _t():
    return Transcript(
        meta=TranscriptMeta(model="sr-v3-ct2"),
        segments=[Segment(id=0, start=0, end=3, text="Ovo је лагаторе zivotar",
                          words=[
                              Word(w="Ovo", start=0.0, end=0.3, prob=0.99),
                              Word(w="јe", start=0.3, end=0.5, prob=0.95, cyr="је"),
                              Word(w="lagatore", start=0.5, end=1.0, prob=0.4),
                              Word(w="zivotar", start=1.0, end=1.5, prob=0.3),
                              Word(w="života", start=1.5, end=2.0, prob=0.95),
                          ])])


def test_flags_low_prob_and_dict_miss():
    t = _t()
    n = apply_flags(t, prob_below=0.65, dic_dir=DIC)
    assert n >= 2
    lw = {w.w: w.flags for _, w in t.iter_words() if w.flags}
    assert "low_prob" in lw["lagatore"]
    assert "low_prob" in lw["zivotar"]
    # high-prob known words are not flagged
    assert "života" not in lw


def test_flag_words_returns_reasons():
    t = _t()
    rows = flag_words(t, 0.65, DIC)
    assert all(len(r) == 3 for r in rows)
    assert any("dict_miss" in r[2] for r in rows)


def test_tier0_suggest_never_raises():
    w = Word(w="zivotar", start=0, end=1, prob=0.3)
    sugg = suggest(w, dic_dir=DIC)
    assert isinstance(sugg, list)
    assert all(s.source in ("dict", "fuzzy", "phonetic") for s in sugg)
    texts = [s.text for s in sugg]
    assert len(texts) == len(set(texts))  # dedup


def test_tier0_suggest_short_words_empty():
    assert suggest(Word(w="a", start=0, end=1), dic_dir=DIC) == []
