"""Flag words for the fix-queue: low ASR confidence OR dictionary miss.

Tier-0 of the correction cascade — always available, no model downloads.
Hunspell via spylls is optional: without dictionaries only confidence flagging
runs (contract: flagging never breaks the pipeline).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional, Set

from ..types import Transcript, Word

logger = logging.getLogger("clipai.correct.flags")

PROB_THRESHOLD = 0.65
TOKEN_RE = re.compile(r"[^\w'čćđšžČĆĐŠŽ]+", re.UNICODE)

_dict = None
_dict_loaded = False


def _load_dict(dic_dir: Optional[Path]) -> None:
    global _dict, _dict_loaded
    if _dict_loaded:
        return
    _dict_loaded = True
    if dic_dir is None:
        dic_dir = Path(__file__).resolve().parent.parent.parent / "eval" / "hunspell"
    try:
        from spylls.hunspell import Dictionary
        d = Dictionary.from_files(str(Path(dic_dir) / "sr-Latn"))
        _dict = d
        logger.info("Hunspell sr-Latn loaded (%s)", dic_dir)
    except Exception as e:
        logger.warning("Hunspell-sr unavailable, confidence-only flagging: %s", e)
        _dict = None


def _known(word: str) -> bool:
    if _dict is None:
        return True
    w = TOKEN_RE.sub("", word)
    if not w or len(w) <= 2:
        return True
    return bool(_dict.lookup(w) or _dict.lookup(w.lower()) or _dict.lookup(w.capitalize()))


def flag_words(t: Transcript, prob_below: float = PROB_THRESHOLD,
               dic_dir: Optional[Path] = None) -> list:
    """Return [(segment, word, reasons)] for the fix-queue."""
    _load_dict(dic_dir)
    out = []
    for seg, w in t.iter_words():
        reasons = []
        if w.prob is not None and w.prob < prob_below:
            reasons.append("low_prob")
        if not _known(w.w):
            reasons.append("dict_miss")
        if reasons:
            out.append((seg, w, reasons))
    return out


def apply_flags(t: Transcript, prob_below: float = PROB_THRESHOLD,
                dic_dir: Optional[Path] = None) -> int:
    """Annotate words in-place (word.flags += reasons); returns count flagged."""
    n = 0
    for seg, w, reasons in flag_words(t, prob_below, dic_dir):
        w.flags = sorted(set(w.flags) | set(reasons))
        n += 1
    return n
